"""Runs one of the extra chord guessers on a WAV file and writes the chords it heard as JSON.

It runs with the app's own Python, as a process of its own, so none of the guessers loads into the
app itself. tools/install_chord_guessers.py puts their programs, models and the few extra Python
packages (in "python") into the tools folder. madmom and BTC use the graphics card the stems use
(NVIDIA, or a Mac's own GPU), and the CPU when there is none:

    python chord_guess_run.py <engine> <tools folder> <input.wav> <output.json>
    python chord_guess_run.py --check <engine> <tools folder>

The output is {"engine": ..., "segments": [{"start", "end", "label"}]}, with each guesser's own
chord labels (Chordino writes "Am7b5/G", the others write "A:hdim7"). Lines starting with
PROGRESS tell the app how far along it is. Only the standard library is imported up here, so the
app can borrow the sonic-annotator helpers without loading any of the guessers.
"""
import csv
import functools
import io
import json
import os
import struct
import subprocess
import sys
import tempfile
import wave

NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
SAMPLE_RATE = 44100


def progress(percent, message):
    print(f"PROGRESS {int(percent)} {message}", flush=True)


def torch_device():
    """The graphics card the stem maker would use: NVIDIA (CUDA), a Mac's own GPU (MPS), or the CPU.

    STEMS_STUDIO_DEVICE (cpu, cuda or mps) chooses it by hand, as it does for the stems.
    """
    import torch
    forced = os.environ.get("STEMS_STUDIO_DEVICE", "").strip().lower()
    if forced in ("cpu", "cuda", "mps"):
        return torch.device(forced)
    if torch.cuda.is_available():
        return torch.device("cuda")
    mps = getattr(torch.backends, "mps", None)
    if mps is not None and mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


def on_device(work, device):
    """Run work(device); if the graphics card cannot do one of its steps, do it on the CPU instead."""
    import torch
    if device.type != "cpu":
        try:
            return work(device)
        except Exception as exc:
            print(f"The graphics card could not finish ({type(exc).__name__}: {exc}); using the CPU.",
                  file=sys.stderr, flush=True)
    return work(torch.device("cpu"))


def sonic_annotator(tools):
    base = os.path.join(tools, "sonic-annotator")
    for candidate in (os.path.join(base, "sonic-annotator.exe"),
                      os.path.join(base, "squashfs-root", "AppRun"),
                      os.path.join(base, "sonic-annotator")):
        if os.path.isfile(candidate):
            return candidate
    return None


def chordino_ready(tools):
    plugins = os.path.join(tools, "vamp")
    return bool(sonic_annotator(tools)) and os.path.isdir(plugins) and any(
        name.startswith("nnls-chroma.") for name in os.listdir(plugins))


def run_sonic(tools, args):
    program = sonic_annotator(tools)
    if not program:
        raise RuntimeError("sonic-annotator is not installed")
    done = subprocess.run([program, *args], capture_output=True, text=True, timeout=900,
                          env={**os.environ, "VAMP_PATH": os.path.join(tools, "vamp")}, **NO_WINDOW)
    if done.returncode != 0:
        raise RuntimeError("sonic-annotator failed: " + (done.stderr or "")[-300:])
    return done.stdout


def csv_rows(text):
    """sonic-annotator's CSV: the first column names the file on the first row only."""
    rows = []
    for row in csv.reader(io.StringIO(text)):
        if len(row) >= 2:
            rows.append(row[1:])
    return rows


def wav_seconds(path):
    with wave.open(path, "rb") as handle:
        return handle.getnframes() / float(handle.getframerate())


def segments_from_changes(changes, end_time):
    """[(time, label), ...] at each change, to segments that last until the next change."""
    segments = []
    for index, (start, label) in enumerate(changes):
        end = changes[index + 1][0] if index + 1 < len(changes) else end_time
        if end > start:
            segments.append({"start": round(start, 3), "end": round(end, 3), "label": label})
    return segments


def frames_to_segments(times, labels, step, end_time):
    changes = []
    for time, label in zip(times, labels):
        if not changes or changes[-1][1] != label:
            changes.append((float(time), label))
    return segments_from_changes(changes, min(end_time, float(times[-1]) + step) if len(times) else end_time)


# --- Chordino: NNLS chroma and an HMM over a chord dictionary (Mauch & Dixon, 2010) -----------

def chordino(tools, wav):
    progress(10, "Chordino is listening...")
    text = run_sonic(tools, ["-d", "vamp:nnls-chroma:chordino:simplechord", "-w", "csv", "--csv-stdout", wav])
    changes = [(float(row[0]), row[1].strip()) for row in csv_rows(text)]
    return segments_from_changes(changes, wav_seconds(wav))


# --- autochord: NNLS chroma into a bi-LSTM-CRF (Bayron, 2021) --------------------------------

BOTHCHROMA = """@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
@prefix vamp: <http://purl.org/ontology/vamp/> .
@prefix : <#> .

:transform_plugin a vamp:Plugin ;
    vamp:identifier "nnls-chroma" .

:transform_library a vamp:PluginLibrary ;
    vamp:identifier "nnls-chroma" ;
    vamp:available_plugin :transform_plugin .

:transform a vamp:Transform ;
    vamp:plugin :transform_plugin ;
    vamp:step_size "2048"^^xsd:int ;
    vamp:block_size "16384"^^xsd:int ;
    vamp:parameter_binding [
        vamp:parameter [ vamp:identifier "rollon" ] ;
        vamp:value "1"^^xsd:float ;
    ] ;
    vamp:output [ vamp:identifier "bothchroma" ] .
"""
AUTOCHORD_NOTES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]
AUTOCHORD_CLASSES = ["N"] + [f"{note}:maj" for note in AUTOCHORD_NOTES] + [f"{note}:min" for note in AUTOCHORD_NOTES]
AUTOCHORD_SEQ = 128


def _varint(data, at):
    value = shift = 0
    while True:
        byte = data[at]
        at += 1
        value |= (byte & 0x7F) << shift
        shift += 7
        if byte < 0x80:
            return value, at


def _table_entries(data, offset, size):
    """Keys and values of one block of a LevelDB-style table (TensorFlow's checkpoint index)."""
    block = data[offset:offset + size]
    restarts = struct.unpack_from("<I", block, len(block) - 4)[0]
    end = len(block) - 4 * (restarts + 1)
    at, key = 0, b""
    while at < end:
        shared, at = _varint(block, at)
        unshared, at = _varint(block, at)
        length, at = _varint(block, at)
        key = key[:shared] + block[at:at + unshared]
        at += unshared
        yield key, block[at:at + length]
        at += length


def _fields(message):
    """Fields of a protobuf message: {field number: [values]} (varints and nested bytes)."""
    out, at = {}, 0
    while at < len(message):
        tag, at = _varint(message, at)
        kind = tag & 7
        if kind == 0:
            value, at = _varint(message, at)
        elif kind == 2:
            length, at = _varint(message, at)
            value, at = message[at:at + length], at + length
        elif kind == 5:
            value, at = message[at:at + 4], at + 4
        elif kind == 1:
            value, at = message[at:at + 8], at + 8
        else:
            raise ValueError("unexpected protobuf field")
        out.setdefault(tag >> 3, []).append(value)
    return out


def read_checkpoint(prefix):
    """The float tensors of a TensorFlow checkpoint, read without TensorFlow: {name: array}."""
    import numpy as np
    with open(prefix + ".index", "rb") as handle:
        index = handle.read()
    with open(prefix + ".data-00000-of-00001", "rb") as handle:
        data = handle.read()
    footer = index[-48:]
    _meta_offset, at = _varint(footer, 0)
    _meta_size, at = _varint(footer, at)
    index_offset, at = _varint(footer, at)
    index_size, at = _varint(footer, at)
    tensors = {}
    for _last_key, handle_bytes in _table_entries(index, index_offset, index_size):
        block_offset, at = _varint(handle_bytes, 0)
        block_size, at = _varint(handle_bytes, at)
        for key, value in _table_entries(index, block_offset, block_size):
            entry = _fields(value)
            if not key or entry.get(1, [0])[0] != 1:    # the header, and anything not float32
                continue
            dims = [_fields(dim).get(1, [0])[0] for dim in _fields(entry.get(2, [b""])[0]).get(2, [])]
            start, size = entry.get(4, [0])[0], entry.get(5, [0])[0]
            tensors[key.decode("utf-8")] = np.frombuffer(data[start:start + size], dtype="<f4").reshape(dims)
    return tensors


def load_autochord(tools):
    """autochord's bi-LSTM-CRF weights, in the order the model lists them."""
    prefix = os.path.join(tools, "autochord", "chroma-seq-bilstm-crf-v1", "variables", "variables")
    tensors = read_checkpoint(prefix)
    weights = [tensors[f"variables/{index}/.ATTRIBUTES/VARIABLE_VALUE"] for index in range(11)]
    names = ("forward_kernel", "forward_recurrent", "forward_bias", "backward_kernel", "backward_recurrent",
             "backward_bias", "transitions", "start", "end", "dense_kernel", "dense_bias")
    return dict(zip(names, weights))


def _lstm(inputs, kernel, recurrent, bias):
    """A Keras LSTM over [batch, time, features] (gates in Keras order: input, forget, cell, output)."""
    import numpy as np
    batch, steps, _ = inputs.shape
    units = recurrent.shape[0]
    projected = inputs @ kernel + bias
    hidden = np.zeros((batch, units), dtype=np.float32)
    cell = np.zeros((batch, units), dtype=np.float32)
    out = np.empty((batch, steps, units), dtype=np.float32)
    sigmoid = lambda x: 1.0 / (1.0 + np.exp(-x))
    for step in range(steps):
        gates = projected[:, step] + hidden @ recurrent
        i, f, c, o = np.split(gates, 4, axis=1)
        cell = sigmoid(f) * cell + sigmoid(i) * np.tanh(c)
        hidden = sigmoid(o) * np.tanh(cell)
        out[:, step] = hidden
    return out


def autochord_decode(weights, pieces):
    """Chord numbers for each frame of each [128, 24] piece: bi-LSTM, then the CRF's best path."""
    import numpy as np
    forward = _lstm(pieces, weights["forward_kernel"], weights["forward_recurrent"], weights["forward_bias"])
    backward = _lstm(pieces[:, ::-1], weights["backward_kernel"], weights["backward_recurrent"],
                     weights["backward_bias"])[:, ::-1]
    scores = np.concatenate([forward, backward], axis=2) @ weights["dense_kernel"] + weights["dense_bias"]
    scores[:, 0] += weights["start"]
    scores[:, -1] += weights["end"]
    transitions = weights["transitions"]
    paths = []
    for piece in scores:
        best = piece[0].copy()
        back = np.zeros(piece.shape, dtype=int)
        for step in range(1, len(piece)):
            options = best[:, None] + transitions
            back[step] = options.argmax(axis=0)
            best = options.max(axis=0) + piece[step]
        path = [int(best.argmax())]
        for step in range(len(piece) - 1, 0, -1):
            path.append(int(back[step][path[-1]]))
        paths.append(path[::-1])
    return np.array(paths)


def autochord(tools, wav):
    import numpy as np
    progress(5, "autochord is reading the harmony...")
    with tempfile.TemporaryDirectory() as work:
        transform = os.path.join(work, "bothchroma.n3")
        with open(transform, "w", encoding="utf-8") as handle:
            handle.write(BOTHCHROMA)
        text = run_sonic(tools, ["-t", transform, "-w", "csv", "--csv-stdout", wav])
    rows = csv_rows(text)
    if not rows:
        return []
    times = np.array([float(row[0]) for row in rows])
    chroma = np.array([[float(value) for value in row[1:25]] for row in rows], dtype=np.float32)
    progress(45, "autochord is naming the chords...")
    weights = load_autochord(tools)
    count = len(chroma)
    # Whole 128-frame pieces. The last piece overlaps the one before it, so no frame is padding.
    starts = list(range(0, max(count - AUTOCHORD_SEQ, 0) + 1, AUTOCHORD_SEQ))
    if count > AUTOCHORD_SEQ and starts[-1] + AUTOCHORD_SEQ < count:
        starts.append(count - AUTOCHORD_SEQ)
    pieces = []
    for start in starts:
        piece = chroma[start:start + AUTOCHORD_SEQ]
        if len(piece) < AUTOCHORD_SEQ:
            piece = np.pad(piece, ((0, AUTOCHORD_SEQ - len(piece)), (0, 0)))
        pieces.append(piece)
    decoded = autochord_decode(weights, np.stack(pieces))
    labels = np.zeros(count, dtype=int)
    for start, row in zip(starts, decoded):
        stop = min(start + AUTOCHORD_SEQ, count)
        labels[start:stop] = np.asarray(row).reshape(-1)[:stop - start]
    step = 2048.0 / SAMPLE_RATE
    return frames_to_segments(times, [AUTOCHORD_CLASSES[int(label)] for label in labels], step, wav_seconds(wav))


# --- madmom: a deep chroma CNN and a CRF (Korzeniowski & Widmer, 2016) -----------------------

def load_madmom():
    from madmom.features.chords import CNNChordFeatureProcessor, CRFChordRecognitionProcessor
    return CNNChordFeatureProcessor(), CRFChordRecognitionProcessor()


def _madmom_steps(network, device):
    """madmom's chord network (convolutions, batch norm, max pooling) as PyTorch steps on device.

    madmom runs these layers one channel at a time in NumPy. The arithmetic here is the same.
    """
    import torch
    import torch.nn.functional as F
    steps = []
    for layer in network.layers:
        kind = type(layer).__name__
        if kind == "ConvolutionalLayer":
            if layer.pad != "valid" or layer.stride not in (None, 1, (1, 1)):
                raise ValueError("unexpected madmom convolution")
            # madmom convolves (the kernel is flipped) with weights [in, out, time, freq].
            kernel = torch.tensor(layer.weights[:, :, ::-1, ::-1].transpose(1, 0, 2, 3).copy(), device=device)
            bias = float(layer.bias.reshape(-1)[0])
            steps.append(lambda x, k=kernel, b=bias: F.conv2d(x, k) + b)
        elif kind == "BatchNormLayer":
            scale = torch.tensor(layer.gamma * layer.inv_std, device=device).view(1, -1, 1, 1)
            shift = torch.tensor(layer.beta - layer.mean * layer.gamma * layer.inv_std, device=device).view(1, -1, 1, 1)
            relu = getattr(layer.activation_fn, "__name__", "") == "relu"
            steps.append(lambda x, s=scale, t=shift, r=relu: torch.relu(x * s + t) if r else x * s + t)
        elif kind == "MaxPoolLayer":
            steps.append(lambda x, size=tuple(layer.size), stride=tuple(layer.stride): F.max_pool2d(x, size, stride))
        else:
            raise ValueError(f"unexpected madmom layer {kind}")
    return steps


def madmom_network(network, device):
    """A drop-in for madmom's NeuralNetwork step that runs on the graphics card."""
    import torch
    _madmom_steps(network, torch.device("cpu"))     # an unexpected layer is reported now, before the song is read

    def run(data):
        def work(where):
            x = torch.tensor(data, dtype=torch.float32, device=where)[None, None]
            for step in _madmom_steps(network, where):
                x = step(x)
            return x[0].permute(1, 2, 0).contiguous().cpu().numpy()
        return on_device(work, device)

    return run


def madmom(tools, wav):
    progress(5, "madmom is listening...")
    features, recogniser = load_madmom()
    try:
        processors = list(features.processors)
        at = next(i for i, step in enumerate(processors) if type(step).__name__ == "NeuralNetwork")
        processors[at] = madmom_network(processors[at], torch_device())
        features.processors = processors
    except Exception as exc:
        print(f"madmom stays on its own CPU code ({exc}).", file=sys.stderr, flush=True)
    found = recogniser(features(wav))
    progress(90, "madmom is naming the chords...")
    return [{"start": round(float(row[0]), 3), "end": round(float(row[1]), 3), "label": str(row[2])}
            for row in found if float(row[1]) > float(row[0])]


# --- BTC: a bi-directional transformer over a constant-Q spectrum (Park et al., 2019) ---------

BTC_ROOTS = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
BTC_QUALITIES = ["min", "maj", "dim", "aug", "min6", "maj6", "min7", "minmaj7", "maj7", "7", "dim7", "hdim7",
                 "sus2", "sus4"]


def btc_label(index):
    if index == 169:
        return "N"
    if index == 168:
        return "X"
    root, quality = BTC_ROOTS[index // 14], BTC_QUALITIES[index % 14]
    return root if quality == "maj" else f"{root}:{quality}"


def load_audio(wav, rate):
    """A WAV file as mono float32 at rate, the way librosa.load reads it (soxr, high quality)."""
    import numpy as np
    import soundfile
    import soxr
    samples, native = soundfile.read(wav, dtype="float32", always_2d=True)
    samples = samples.mean(axis=1)
    if native == rate:
        return samples
    size = int(np.ceil(len(samples) * rate / native))
    out = soxr.resample(samples, native, rate, quality="soxr_hq")
    return np.pad(out, (0, max(0, size - len(out))))[:size].astype(np.float32)


def _downsample(samples, factor):
    """1/factor of the sample rate, scaled as librosa does between the octaves of a constant-Q transform."""
    import numpy as np
    import soxr
    size = int(np.ceil(len(samples) / factor))
    out = soxr.resample(samples, factor, 1, quality="soxr_hq")
    out = np.pad(out, (0, max(0, size - len(out))))[:size]
    return (out * np.sqrt(factor)).astype(samples.dtype)


def _cqt_filters(freqs, alpha, rate):
    """One octave of librosa's constant-Q filters (Hann-windowed, sparse), as an FFT basis."""
    import numpy as np
    import scipy.fft
    import scipy.signal
    freqs, alpha = np.array(freqs), np.array(alpha)
    lengths = rate / (alpha * freqs)
    n_fft = int(2.0 ** np.ceil(np.log2(lengths.max())))
    basis = np.zeros((len(freqs), n_fft), dtype=np.complex64)
    for row, (length, freq) in enumerate(zip(lengths, freqs)):
        wave_ = np.exp(1j * np.arange(-length // 2, length // 2) * 2 * np.pi * freq / rate)
        wave_ *= scipy.signal.get_window("hann", len(wave_), fftbins=True)
        left = (n_fft - len(wave_)) // 2
        basis[row, left:left + len(wave_)] = wave_ / np.abs(wave_).sum()
    basis *= (lengths / n_fft)[:, None]
    spectrum = scipy.fft.fft(basis, axis=1)[:, :n_fft // 2 + 1]
    # Drop the weakest values that together hold 1% of each filter.
    magnitude = np.abs(spectrum)
    ordered = np.sort(magnitude, axis=1)
    share = np.cumsum(ordered / magnitude.sum(axis=1, keepdims=True), axis=1)
    threshold = ordered[np.arange(len(ordered)), np.argmin(share < 0.01, axis=1)]
    return (spectrum * (magnitude >= threshold[:, None])).astype(np.complex64), n_fft


@functools.lru_cache(maxsize=None)
def _sparse_filters(freqs, alpha, rate, scale):
    import numpy as np
    import scipy.sparse
    basis, n_fft = _cqt_filters(freqs, alpha, rate)
    return scipy.sparse.csr_array(basis * np.float32(scale)), n_fft


def cqt_magnitude(samples, rate, hop, n_bins, bins_per_octave):
    """|librosa.cqt(...)| with librosa's defaults (from C1, scaled), in NumPy, SciPy and soxr.

    The same filters, one octave at a time from the top, halving the sample rate between octaves.
    BTC was trained on this, and it saves installing librosa and its compiler (about 300 MB).
    """
    import numpy as np
    import scipy.fft
    freqs = 32.703195662574814 * 2.0 ** (np.arange(n_bins) / bins_per_octave)
    logf = np.log2(freqs)
    per_octave = np.empty_like(freqs)
    per_octave[0], per_octave[-1] = 1 / (logf[1] - logf[0]), 1 / (logf[-1] - logf[-2])
    per_octave[1:-1] = 2 / (logf[2:] - logf[:-2])
    alpha = (2.0 ** (2 / per_octave) - 1) / (2.0 ** (2 / per_octave) + 1)
    cutoff = max(freqs * (1 + 0.5 * 1.50018310546875 * alpha))
    octaves = int(np.ceil(n_bins / bins_per_octave))
    twos = (hop & -hop).bit_length() - 1
    early = min(max(0, int(np.ceil(np.log2(rate / 2.0 / cutoff)) - 1) - 1), max(0, twos - octaves + 1))
    if early:
        samples = _downsample(samples, 2 ** early)
        rate, hop = rate / 2 ** early, hop // 2 ** early
    base_rate = rate
    responses = []
    for octave in range(octaves):
        top = n_bins - bins_per_octave * octave
        band = slice(max(top - bins_per_octave, 0), top)
        basis, n_fft = _sparse_filters(tuple(freqs[band]), tuple(alpha[band]), rate, np.sqrt(base_rate / rate))
        padded = np.pad(samples, n_fft // 2)
        count = 1 + (len(padded) - n_fft) // hop
        frames = np.lib.stride_tricks.as_strided(
            padded, (count, n_fft), (padded.strides[0] * hop, padded.strides[0]), writeable=False)
        responses.append(basis @ scipy.fft.rfft(frames, axis=1).T)
        if octave < octaves - 1 and hop % 2 == 0 and freqs[band.start - 1] <= rate / 5:
            samples, rate, hop = _downsample(samples, 2), rate / 2, hop // 2
    columns = min(response.shape[1] for response in responses)
    out = np.concatenate([response[:, :columns] for response in reversed(responses)], axis=0)
    return np.abs(out) / np.sqrt(base_rate / (alpha * freqs))[:, None]


def load_btc(tools):
    import torch
    import yaml
    folder = os.path.join(tools, "btc")
    if folder not in sys.path:
        sys.path.insert(0, folder)
    from btc_model import BTC_model
    from utils.hparams import HParams
    with open(os.path.join(folder, "run_config.yaml"), "r", encoding="utf-8") as handle:
        config = HParams(**yaml.safe_load(handle))
    config.feature["large_voca"] = True
    config.model["num_chords"] = 170
    model = BTC_model(config=config.model)
    checkpoint = torch.load(os.path.join(folder, "test", "btc_model_large_voca.pt"),
                            map_location="cpu", weights_only=False)
    model.load_state_dict(checkpoint["model"])
    model.eval()
    return model, config, checkpoint["mean"], checkpoint["std"], torch_device()


def btc(tools, wav):
    import numpy as np
    import torch
    progress(5, "BTC is loading its model...")
    model, config, mean, std, device = load_btc(tools)
    progress(15, "BTC is reading the harmony...")
    rate = config.mp3["song_hz"]
    samples = load_audio(wav, rate)
    chunk = int(rate * config.mp3["inst_len"])
    parts = [cqt_magnitude(samples[start:start + chunk], rate, config.feature["hop_length"],
                           config.feature["n_bins"], config.feature["bins_per_octave"])
             for start in range(0, len(samples), chunk)]
    feature = np.log(np.concatenate(parts, axis=1) + 1e-6).T
    feature = (feature - mean) / std
    frame_seconds = config.mp3["inst_len"] / config.model["timestep"]
    steps = config.model["timestep"]
    frames = feature.shape[0]
    feature = np.pad(feature, ((0, (-frames) % steps), (0, 0)))
    progress(55, "BTC is naming the chords...")
    def infer(where):
        # Each 10-second window is read on its own, so the windows can go through together.
        labels = []
        model.to(where)
        with torch.no_grad():
            windows = torch.tensor(feature, dtype=torch.float32).reshape(-1, steps, feature.shape[1]).to(where)
            for start in range(0, len(windows), 32):
                attended, _ = model.self_attn_layers(windows[start:start + 32])
                prediction, _ = model.output_layer(attended)
                labels.extend(int(value) for value in prediction.reshape(-1).tolist())
        return labels

    labels = on_device(infer, device)[:frames]
    times = [index * frame_seconds for index in range(frames)]
    return frames_to_segments(times, [btc_label(index) for index in labels], frame_seconds, wav_seconds(wav))


ENGINES = {"chordino": chordino, "autochord": autochord, "madmom": madmom, "btc": btc}


def check(engine, tools):
    """Load an engine without a song, so the installer can tell whether it works."""
    if engine in ("chordino", "autochord") and not chordino_ready(tools):
        raise RuntimeError("the Chordino plugin is not installed")
    if engine == "autochord":
        load_autochord(tools)
    elif engine == "madmom":
        load_madmom()
    elif engine == "btc":
        import numpy as np
        load_btc(tools)
        cqt_magnitude(np.zeros(22050, dtype=np.float32), 22050, 2048, 144, 24)
    print(f"  {engine} loads.", flush=True)


def main(argv):
    if argv and argv[0] == "--check":
        sys.path.append(os.path.join(argv[2], "python"))
        check(argv[1], argv[2])
        return 0
    engine, tools, wav, out = argv
    # madmom, PyYAML and mido, installed next to the guessers. Last, so the app's own packages win.
    sys.path.append(os.path.join(tools, "python"))
    segments = ENGINES[engine](tools, wav)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump({"engine": engine, "segments": segments}, handle)
    os.replace(tmp, out)
    progress(100, "Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
