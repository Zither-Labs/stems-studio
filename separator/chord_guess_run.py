"""Runs one of the extra chord guessers on a WAV file and writes the chords it heard as JSON.

It runs inside the chord-guesser environment (.venv-chords), which tools/install_chord_guessers.py
makes, so TensorFlow and madmom never load into the app itself:

    python chord_guess_run.py <engine> <tools folder> <input.wav> <output.json>
    python chord_guess_run.py --check <engine> <tools folder>

The output is {"engine": ..., "segments": [{"start", "end", "label"}]}, with each guesser's own
chord labels (Chordino writes "Am7b5/G", the others write "A:hdim7"). Lines starting with
PROGRESS tell the app how far along it is. Only the standard library is imported up here, so the
app can borrow the sonic-annotator helpers without loading any of the guessers.
"""
import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import wave

NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}
SAMPLE_RATE = 44100


def progress(percent, message):
    print(f"PROGRESS {int(percent)} {message}", flush=True)


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


def load_autochord(tools):
    import tf_keras
    return tf_keras.models.load_model(os.path.join(tools, "autochord", "chroma-seq-bilstm-crf-v1"))


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
    model = load_autochord(tools)
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
    decoded = model.predict(np.stack(pieces), batch_size=128, verbose=0)[0]
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


def madmom(tools, wav):
    progress(5, "madmom is listening...")
    features, recogniser = load_madmom()
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
    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    model = BTC_model(config=config.model).to(device)
    checkpoint = torch.load(os.path.join(folder, "test", "btc_model_large_voca.pt"),
                            map_location=device, weights_only=False)
    model.load_state_dict(checkpoint["model"])
    model.eval()
    return model, config, checkpoint["mean"], checkpoint["std"], device


def btc(tools, wav):
    import librosa
    import numpy as np
    import torch
    progress(5, "BTC is loading its model...")
    model, config, mean, std, device = load_btc(tools)
    progress(15, "BTC is reading the harmony...")
    rate = config.mp3["song_hz"]
    samples, _ = librosa.load(wav, sr=rate, mono=True)
    chunk = int(rate * config.mp3["inst_len"])
    parts = []
    for start in range(0, max(len(samples), 1), chunk):
        piece = samples[start:start + chunk]
        if len(piece) == 0:
            break
        parts.append(librosa.cqt(piece, sr=rate, n_bins=config.feature["n_bins"],
                                 bins_per_octave=config.feature["bins_per_octave"],
                                 hop_length=config.feature["hop_length"]))
    feature = np.log(np.abs(np.concatenate(parts, axis=1)) + 1e-6).T
    feature = (feature - mean) / std
    frame_seconds = config.mp3["inst_len"] / config.model["timestep"]
    steps = config.model["timestep"]
    frames = feature.shape[0]
    feature = np.pad(feature, ((0, (-frames) % steps), (0, 0)))
    progress(55, "BTC is naming the chords...")
    labels = []
    with torch.no_grad():
        tensor = torch.tensor(feature, dtype=torch.float32).unsqueeze(0).to(device)
        for start in range(0, tensor.shape[1], steps):
            attended, _ = model.self_attn_layers(tensor[:, start:start + steps, :])
            prediction, _ = model.output_layer(attended)
            labels.extend(int(value) for value in prediction.reshape(-1).tolist())
    labels = labels[:frames]
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
        load_btc(tools)
    print(f"  {engine} loads.", flush=True)


def main(argv):
    if argv and argv[0] == "--check":
        check(argv[1], argv[2])
        return 0
    engine, tools, wav, out = argv
    segments = ENGINES[engine](tools, wav)
    tmp = out + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump({"engine": engine, "segments": segments}, handle)
    os.replace(tmp, out)
    progress(100, "Done.")
    return 0


if __name__ == "__main__":
    os.environ.setdefault("TF_CPP_MIN_LOG_LEVEL", "2")
    sys.exit(main(sys.argv[1:]))
