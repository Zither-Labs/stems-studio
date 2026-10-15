"""
Key and chord detection from the separated stems.

Working on separated stems is what makes this more reliable than analysing a full mix:

  * the BASS stem says which note the music rests on. A walking bass is not a new chord on
    every note: the downbeat and the rhythm guitar hold the chord while the bass moves;
  * the HARMONY stems (guitar, piano and the "other" stem, whatever the song has) carry the
    chords and so tell major from minor, which a vocal melody alone often cannot;
  * the VOCAL pitch track (already found for the highway) adds the melody's notes.

Each of these is turned into a "chromagram" (how much of each of the 12 note names is sounding,
frame by frame, with the octave ignored, after correcting for a song that is a little sharp or
flat). The key comes from comparing the combined note counts with the typical major and minor
profiles (Krumhansl-Schmuckler). Chords come from matching every moment against major, minor,
7th and minor-7th shapes, helped by the bass note and the key, and smoothed with a Viterbi
search so the chord does not flicker.
"""

import json
import os

import numpy as np

ANALYSIS_VERSION = 3          # 3 lines bass notes up to the beat, so a walking bass is not a new chord

ONSET_SR = 22050
ONSET_HOP = 512
ONSET_FRAME = ONSET_HOP / ONSET_SR

HARMONY_SR = 22050
HARMONY_HOP = 2048
BASS_SR = 11025
BASS_HOP = 1024
N_FFT = 8192
FRAME_SECONDS = HARMONY_HOP / HARMONY_SR     # about 0.093 s; the same for the bass analysis

SHARP_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
FLAT_NAMES = ["C", "Db", "D", "Eb", "E", "F", "Gb", "G", "Ab", "A", "Bb", "B"]

# Krumhansl-Kessler key profiles: how much each note name tends to be used in a major / minor key.
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

MAJOR_SCALE = (0, 2, 4, 5, 7, 9, 11)
MINOR_SCALE = (0, 2, 3, 5, 7, 8, 10)

# Keys that are normally written with flats.
FLAT_MAJOR_TONICS = {5, 10, 3, 8, 1, 6}
FLAT_MINOR_TONICS = {2, 7, 0, 5, 10, 3}

# Key weights for the three sources (they are each scaled to the same size first).
WEIGHT_HARMONY = 0.45
WEIGHT_BASS = 0.30
WEIGHT_VOCAL = 0.25

CHORD_SHAPES = {          # quality: (note offsets from the root, weight of each, penalty)
    "": ((0, 4, 7), (1.0, 0.9, 0.9), 0.0),
    "m": ((0, 3, 7), (1.0, 0.9, 0.9), 0.0),
    "7": ((0, 4, 7, 10), (1.0, 0.9, 0.9, 0.6), 0.08),
    "m7": ((0, 3, 7, 10), (1.0, 0.9, 0.9, 0.6), 0.08),
}
CHORD_SWITCH_COST = 0.30      # how much better a new chord must be to be worth switching to
MIN_CHORD_SECONDS = 0.45
BASS_IN_CHORD_BONUS = 0.12
DIATONIC_BONUS = 0.04


# --- audio to chroma ---------------------------------------------------------------

def read_mono(path, sample_rate):
    import soundfile as sf
    import soxr

    audio, rate = sf.read(path, dtype="float32", always_2d=True)
    mono = audio.mean(axis=1)
    if rate != sample_rate:
        mono = soxr.resample(mono, rate, sample_rate)
    return mono.astype(np.float32)


def spectrogram(x, n_fft, hop, progress=None):
    """Magnitude spectrogram, (frames, bins). Hann window.

    progress, when given, is called with the fraction finished (0 to 1). This loop is the slow part.
    """
    if len(x) < n_fft:
        x = np.pad(x, (0, n_fft - len(x)))
    window = np.hanning(n_fft + 1)[:-1].astype(np.float32)
    n_frames = 1 + (len(x) - n_fft) // hop
    out = np.empty((n_frames, n_fft // 2 + 1), dtype=np.float32)
    for first in range(0, n_frames, 256):
        last = min(n_frames, first + 256)
        index = (np.arange(first, last) * hop)[:, None] + np.arange(n_fft)[None, :]
        out[first:last] = np.abs(np.fft.rfft(x[index] * window, axis=1))
        if progress is not None and n_frames:
            progress(last / n_frames)
    return out


def estimate_tuning(mag, sr, fmin, fmax):
    """How far the song is from standard pitch, in semitones (-0.5 to 0.5)."""
    freqs = np.arange(mag.shape[1]) * sr / N_FFT
    keep = (freqs >= fmin) & (freqs <= fmax)
    midi = 69 + 12 * np.log2(freqs[keep] / 440.0)
    total = mag[:, keep].sum(axis=0)
    best, best_energy = 0.0, -1.0
    for tuning in np.arange(-0.5, 0.5, 0.05):
        shifted = midi - tuning
        weight = np.cos(np.pi * (shifted - np.round(shifted))) ** 2
        energy = float(np.sum(weight * total))
        if energy > best_energy:
            best, best_energy = float(tuning), energy
    return best


def chromagram(mag, sr, fmin, fmax, tuning):
    """Fold a spectrogram into the 12 note names. Returns (frames, 12)."""
    freqs = np.arange(mag.shape[1]) * sr / N_FFT
    keep = (freqs >= fmin) & (freqs <= fmax)
    midi = 69 + 12 * np.log2(freqs[keep] / 440.0) - tuning
    pitch_class = np.round(midi).astype(int) % 12
    weight = np.cos(np.pi * (midi - np.round(midi))) ** 2     # bins between two notes count less
    fold = np.zeros((int(keep.sum()), 12), dtype=np.float32)
    fold[np.arange(len(pitch_class)), pitch_class] = weight
    return (np.sqrt(mag[:, keep]) @ fold).astype(np.float32)   # sqrt: loud partials do not dominate


def _normalise_rows(a):
    return a / (np.linalg.norm(a, axis=1, keepdims=True) + 1e-9)


# --- key ------------------------------------------------------------------------------

def key_scores(vector):
    """Correlation of a 12-note profile with all 24 keys. Returns a list sorted best first."""
    results = []
    for mode, profile in (("major", MAJOR_PROFILE), ("minor", MINOR_PROFILE)):
        for tonic in range(12):
            template = np.roll(profile, tonic)
            score = float(np.corrcoef(template, vector)[0, 1])
            results.append({"tonic": tonic, "mode": mode, "score": round(score, 4)})
    return sorted(results, key=lambda r: r["score"], reverse=True)


def uses_flats(tonic, mode):
    return tonic in (FLAT_MAJOR_TONICS if mode == "major" else FLAT_MINOR_TONICS)


def note_name(pitch_class, flats):
    return (FLAT_NAMES if flats else SHARP_NAMES)[pitch_class % 12]


def key_name(tonic, mode):
    return f"{note_name(tonic, uses_flats(tonic, mode))} {mode}"


def detect_key(harmony_vec, bass_vec, vocal_vec):
    """Combine the three sources' note counts and pick the best-matching key."""
    parts = [(harmony_vec, WEIGHT_HARMONY), (bass_vec, WEIGHT_BASS), (vocal_vec, WEIGHT_VOCAL)]
    total = np.zeros(12)
    used = 0.0
    for vec, weight in parts:
        if vec is not None and vec.sum() > 0:
            total += weight * (vec / vec.sum())
            used += weight
    if used == 0:
        return None
    ranked = key_scores(total)
    best, second = ranked[0], ranked[1]
    margin = best["score"] - second["score"]
    # The relative key uses exactly the same notes, so no note count can fully rule it out.
    rel_mode = "minor" if best["mode"] == "major" else "major"
    rel_tonic = (best["tonic"] + 9) % 12 if best["mode"] == "major" else (best["tonic"] + 3) % 12
    return {
        "relative": {"tonic": rel_tonic, "mode": rel_mode, "name": key_name(rel_tonic, rel_mode)},
        "tonic": best["tonic"],
        "mode": best["mode"],
        "name": key_name(best["tonic"], best["mode"]),
        "flats": uses_flats(best["tonic"], best["mode"]),
        "score": best["score"],
        "margin": round(margin, 4),
        "certainty": "confident" if margin >= 0.06 else "fairly sure" if margin >= 0.02 else "unsure",
        "alternatives": [
            {"tonic": r["tonic"], "mode": r["mode"], "name": key_name(r["tonic"], r["mode"]), "score": r["score"]}
            for r in ranked[1:4]
        ],
    }


# --- chords ----------------------------------------------------------------------------

def _chord_table(flats):
    """All chords as (root, quality, name, unit-length template)."""
    table = []
    for quality, (offsets, weights, penalty) in CHORD_SHAPES.items():
        for root in range(12):
            template = np.zeros(12)
            for offset, weight in zip(offsets, weights):
                template[(root + offset) % 12] = weight
            template /= np.linalg.norm(template)
            table.append({
                "root": root, "quality": quality, "penalty": penalty,
                "name": note_name(root, flats) + quality,
                "notes": {(root + o) % 12 for o in offsets},
                "template": template,
            })
    return table


def detect_chords(harmony, bass, key):
    """harmony, bass: (frames, 12) chromagrams. Returns a list of {start, end, root, quality, name}."""
    n = min(len(harmony), len(bass))
    harmony, bass = harmony[:n], bass[:n]
    flats = key["flats"] if key else False
    table = _chord_table(flats)
    scale = set((key["tonic"] + d) % 12 for d in (MAJOR_SCALE if key["mode"] == "major" else MINOR_SCALE)) if key else set()
    if key and key["mode"] == "minor":
        scale.add((key["tonic"] + 11) % 12)          # the raised 7th of the harmonic minor (the V chord)

    h = _normalise_rows(harmony)
    b = _normalise_rows(bass)
    mix = _normalise_rows(h + 0.5 * b)

    templates = np.stack([c["template"] for c in table])                # chords x 12
    scores = mix @ templates.T                                           # frames x chords
    roots = np.array([c["root"] for c in table])
    scores += BASS_IN_CHORD_BONUS * b[:, roots]
    scores -= np.array([c["penalty"] for c in table])[None, :]
    if scale:
        diatonic = np.array([1.0 if c["notes"] <= scale else 0.0 for c in table])
        scores += DIATONIC_BONUS * diatonic[None, :]

    # "No chord" wins only where there is practically no sound.
    energy = harmony.sum(axis=1) + bass.sum(axis=1)
    quiet = energy < 0.08 * np.median(energy[energy > 0]) if np.any(energy > 0) else np.ones(n, dtype=bool)
    emission = np.concatenate([scores, np.where(quiet, 1.5, 0.0)[:, None]], axis=1)   # last column = no chord

    # Viterbi: staying on a chord is free, changing costs CHORD_SWITCH_COST.
    states = emission.shape[1]
    delta = emission[0].copy()
    back = np.zeros((n, states), dtype=np.int32)
    for t in range(1, n):
        best_prev = int(np.argmax(delta))
        switch = delta[best_prev] - CHORD_SWITCH_COST
        stay = delta >= switch
        back[t] = np.where(stay, np.arange(states), best_prev)
        delta = np.where(stay, delta, switch) + emission[t]
    path = np.zeros(n, dtype=np.int32)
    path[-1] = int(np.argmax(delta))
    for t in range(n - 1, 0, -1):
        path[t - 1] = back[t, path[t]]

    # Runs of the same chord; very short ones are absorbed into the previous chord.
    runs = []
    for i, state in enumerate(path):
        if runs and runs[-1][0] == state:
            runs[-1][2] = i + 1
        else:
            runs.append([int(state), i, i + 1])
    min_frames = max(1, int(round(MIN_CHORD_SECONDS / FRAME_SECONDS)))
    merged = []
    for run in runs:
        if merged and (run[2] - run[1] < min_frames or merged[-1][0] == run[0]):
            merged[-1][2] = run[2]
        else:
            merged.append(run)

    chords = []
    for state, start, end in merged:
        if state == len(table):
            continue                                                       # no chord here
        chord = table[state]
        chords.append({
            "start": round(start * FRAME_SECONDS, 2),
            "end": round(end * FRAME_SECONDS, 2),
            "root": chord["root"],
            "quality": chord["quality"],
            "name": chord["name"],
        })
    return chords


# --- putting it together -----------------------------------------------------------------

HARMONY_STEMS = ("guitar", "guitar_lead", "guitar_rhythm", "piano", "other")


def _sum_stems(paths, sample_rate):
    mix = None
    for path in paths:
        x = read_mono(path, sample_rate)
        if mix is None:
            mix = x
        else:
            n = min(len(mix), len(x))
            mix = mix[:n] + x[:n]
    return mix


def vocal_histogram(vocal_midi, tuning):
    """How long the singer spent on each note name, from the highway's pitch track."""
    if vocal_midi is None:
        return None
    midi = np.asarray(vocal_midi, dtype=np.float64)
    midi = midi[midi > 0] - tuning
    if len(midi) < 20:
        return None
    return np.bincount(np.round(midi).astype(int) % 12, minlength=12).astype(np.float64)


def onset_envelope(mono):
    """How hard each moment is hit, from a rise in loudness. Used to find the beat."""
    frame = 1024
    if mono is None or len(mono) < frame * 4:
        return np.zeros(0, dtype=np.float64)
    count = 1 + (len(mono) - frame) // ONSET_HOP
    squared = np.asarray(mono, dtype=np.float64) ** 2
    running = np.empty(len(squared) + 1, dtype=np.float64)
    running[0] = 0.0
    np.cumsum(squared, out=running[1:])
    starts = np.arange(count) * ONSET_HOP
    energy = np.sqrt((running[starts + frame] - running[starts]) / frame + 1e-12)
    rise = np.maximum(0.0, np.diff(energy, prepend=energy[0]))
    return np.convolve(rise, np.array([0.2, 0.6, 0.2]), mode="same")


def estimate_groove(onset, frame_seconds=ONSET_FRAME):
    """The tempo and the meter (3/4, 4/4, and the other common ones).

    Returns None when there is no beat to hear. The downbeat is the beat that is hit harder
    than the others in the bar.
    """
    onset = np.asarray(onset, dtype=np.float64)
    if len(onset) < 32 or float(np.max(onset)) <= 0:
        return None
    onset = np.maximum(0.0, onset)
    onset = onset / (float(onset.max()) + 1e-9)
    size = 1 << int(np.ceil(np.log2(len(onset) * 2)))
    correlation = np.fft.irfft(np.abs(np.fft.rfft(onset - onset.mean(), size)) ** 2)[:len(onset)]
    min_lag = max(2, int(round(60 / 180 / frame_seconds)))
    max_lag = min(len(correlation) - 2, int(round(60 / 55 / frame_seconds)))
    if max_lag <= min_lag + 2:
        return None
    lag_score = correlation[min_lag:max_lag + 1]
    peak = min_lag + int(np.argmax(lag_score))
    candidates = set()
    for lag in (peak, peak // 2, peak * 2, int(round(peak / 1.5)), int(round(peak * 1.5))):
        if min_lag <= lag <= max_lag:
            candidates.add(int(lag))
    peaks = []
    for i in range(1, len(lag_score) - 1):
        if lag_score[i] >= lag_score[i - 1] and lag_score[i] > lag_score[i + 1]:
            peaks.append((float(lag_score[i]), min_lag + i))
    peaks.sort(reverse=True)
    for _, lag in peaks[:5]:
        candidates.add(int(lag))

    positions = np.arange(len(onset))

    def column_means(bar):
        """Mean hit strength at each spot in the bar."""
        if bar < 4 or bar > len(onset) // 3:
            return None
        total = np.zeros(bar, dtype=np.float64)
        count = np.zeros(bar, dtype=np.float64)
        # bincount already folded by the full length; fold again into this bar.
        total += np.bincount(positions % bar, weights=onset, minlength=bar)
        count += np.bincount(positions % bar, minlength=bar)
        if count.min() < 4:
            return None
        return total / count

    best = None
    for lag in candidates:
        for meter in (2, 3, 4, 5, 6):
            bar = lag * meter
            columns = column_means(bar)
            if columns is None:
                continue
            phases = np.arange(bar)
            offsets = (phases[:, None] + (np.arange(meter) * lag)) % bar
            levels = columns[offsets]
            low = levels.min(axis=1)
            high = np.maximum(levels.max(axis=1), 1e-12)
            down = levels[:, 0]
            other = (levels.sum(axis=1) - down) / (meter - 1)
            score = down - 0.75 * other
            if meter == 4:
                score = score + 0.02
            elif meter == 3:
                score = score + 0.015
            # Every beat in the bar has to land on a hit. A lag that falls
            # between the notes is not the pulse, even if the downbeat looks loud.
            score = np.where(low >= 0.35 * high, score, -np.inf)
            phase = int(np.argmax(score))
            if not np.isfinite(score[phase]):
                continue
            found = (float(score[phase]), int(lag), int(meter), phase, float(down[phase]), float(other[phase]))
            if best is None or found[0] > best[0]:
                best = found
    if best is None or best[4] <= best[5] * 1.08:
        return None
    _, lag, meter, phase, _, _ = best
    beat_seconds = lag * frame_seconds
    return {
        "bpm": round(60.0 / beat_seconds, 1),
        "beats_per_bar": int(meter),
        "beat_seconds": round(beat_seconds, 4),
        "phase_seconds": round(phase * frame_seconds, 4),
    }


def harmony_root(profile):
    """The chord the rhythm guitar is holding, or None when the bar is too muddy to call."""
    if profile is None:
        return None
    profile = np.asarray(profile, dtype=np.float64)
    if profile.sum() <= 0:
        return None
    profile = profile / profile.sum()
    ranked = []
    for root in range(12):
        for quality in ("", "m"):
            intervals, weights, _penalty = CHORD_SHAPES[quality]
            score = 0.0
            covered = 0.0
            for interval, weight in zip(intervals, weights):
                heard = float(profile[(root + interval) % 12])
                score += heard * weight
                covered += heard
            score -= 0.45 * (1.0 - covered)
            ranked.append((score, root))
    ranked.sort(reverse=True)
    if ranked[0][0] - ranked[1][0] < 0.015:
        return None
    return ranked[0][1]


def _chroma_span(chroma, start, end):
    if chroma is None or len(chroma) == 0:
        return None
    first = max(0, min(len(chroma) - 1, int(round(start / FRAME_SECONDS))))
    last = max(first + 1, min(len(chroma), int(round(end / FRAME_SECONDS))))
    total = np.asarray(chroma[first:last], dtype=np.float64).sum(axis=0)
    if float(total.sum()) <= 0:
        return None
    return total


def root_for_span(bass, harmony, start, end, beat, meter):
    """One bar's root. A clear rhythm-guitar chord wins over a bass line that walks around it."""
    guessed = harmony_root(_chroma_span(harmony, start, end))
    if guessed is not None:
        return int(guessed)
    weight = np.zeros(12, dtype=np.float64)
    for beat_index in range(meter):
        beat_at = start + beat_index * beat
        beat_end = min(end, beat_at + beat)
        if beat_index == 0:
            beat_at = max(0.0, beat_at - beat / 3.0)
        piece = _chroma_span(bass, beat_at, beat_end)
        if piece is None:
            continue
        accent = 3.0 if beat_index == 0 else 2.0 if meter % 2 == 0 and beat_index == meter // 2 else 1.0
        weight += accent * piece
    if float(weight.sum()) <= 0:
        return None
    return int(np.argmax(weight))


def _beat_groups(meter):
    """4/4 can change chord halfway through the bar. A waltz usually holds the bar."""
    if meter == 4:
        return [(0, 2), (2, 4)]
    if meter == 6:
        return [(0, 3), (3, 6)]
    if meter == 2:
        return [(0, 1), (1, 2)]
    return [(0, meter)]


def bars_as_runs(bass_chroma, harmony_chroma, groove):
    """Roots on the bar, or on each half of a 4/4 bar. Notes between the beats are not roots."""
    beat = float(groove["beat_seconds"])
    meter = int(groove["beats_per_bar"])
    bar = beat * meter
    if beat <= 0 or bar <= 0:
        return []
    frames = max(len(bass_chroma) if bass_chroma is not None else 0,
                 len(harmony_chroma) if harmony_chroma is not None else 0)
    if frames == 0:
        return []
    duration = frames * FRAME_SECONDS
    t = float(groove["phase_seconds"]) % bar
    runs = []
    while t < duration - beat * 0.45:
        for beat_from, beat_to in _beat_groups(meter):
            start = t + beat_from * beat
            end = min(duration, t + beat_to * beat)
            if start >= duration - beat * 0.25 or end - start < beat * 0.45:
                continue
            root = root_for_span(bass_chroma, harmony_chroma, start, end, beat, beat_to - beat_from)
            if root is None:
                continue
            if runs and runs[-1]["root"] == root and start - runs[-1]["end"] < 0.2:
                runs[-1]["end"] = round(end, 3)
            else:
                runs.append({"start": round(start, 3), "end": round(end, 3), "root": int(root)})
        t += bar
    return runs


def bass_root_runs(bass_chroma):
    """Stretches where the bass holds one note. Quiet moments are left out."""
    if bass_chroma is None or len(bass_chroma) == 0:
        return []
    energy = bass_chroma.sum(axis=1)
    loud = energy[energy > 0]
    floor = float(0.2 * np.median(loud)) if len(loud) else 0.0
    roots = np.argmax(bass_chroma, axis=1)
    runs = []
    for i, root in enumerate(roots):
        pc = int(root) if energy[i] >= floor else None
        start = round(i * FRAME_SECONDS, 3)
        end = round((i + 1) * FRAME_SECONDS, 3)
        if runs and runs[-1]["root"] == pc:
            runs[-1]["end"] = end
        else:
            runs.append({"start": start, "end": end, "root": pc})
    return [
        {"start": run["start"], "end": run["end"], "root": int(run["root"])}
        for run in runs
        if run["root"] is not None and run["end"] - run["start"] >= 0.35
    ]


def analyze_song(song_dir, vocal_midi=None, progress=None):
    """Find the key and chords of a separated song. Returns a JSON-ready dict.

    progress, when given, is called with (percent, message) as the slow reads finish.
    """
    def report(percent, message):
        if progress is not None:
            progress(max(0, min(100, int(percent))), message)

    def read_spec(audio, hop, start, span, message):
        def tick(fraction):
            report(start + span * fraction, f"{message} {int(fraction * 100)}%")
        return spectrogram(audio, N_FFT, hop, progress=tick)

    def stem(name):
        path = os.path.join(song_dir, name + ".wav")
        return path if os.path.isfile(path) else None

    harmony_paths = [p for p in (stem(n) for n in HARMONY_STEMS) if p]
    bass_path = stem("bass")
    if not harmony_paths and not bass_path:
        raise ValueError("This song has no harmony or bass stems to analyse.")

    harmony_chroma = bass_chroma = None
    harmony_mag = bass_mag = None
    tuning = 0.0

    report(1, "Reading the instruments...")
    if harmony_paths:
        harmony_mag = read_spec(_sum_stems(harmony_paths, HARMONY_SR), HARMONY_HOP, 2, 38, "Reading the instruments...")
        tuning = estimate_tuning(harmony_mag, HARMONY_SR, 110.0, 2000.0)
        harmony_chroma = chromagram(harmony_mag, HARMONY_SR, 110.0, 2000.0, tuning)
    if bass_path:
        report(42, "Reading the bass...")
        bass_mag = read_spec(read_mono(bass_path, BASS_SR), BASS_HOP, 42, 26, "Reading the bass...")
        if harmony_chroma is None:
            tuning = estimate_tuning(bass_mag, BASS_SR, 40.0, 400.0)
        bass_chroma = chromagram(bass_mag, BASS_SR, 40.0, 400.0, tuning)

    report(70, "Finding the key...")
    vec = lambda c: None if c is None else c.sum(axis=0).astype(np.float64)    # noqa: E731
    key = detect_key(vec(harmony_chroma), vec(bass_chroma), vocal_histogram(vocal_midi, tuning))

    chords = []
    if key and harmony_chroma is not None:
        bass_for_chords = bass_chroma if bass_chroma is not None else np.zeros_like(harmony_chroma)
        chords = detect_chords(harmony_chroma, bass_for_chords, key)

    # The rhythm guitar holds the chord. A lead guitar line jumps around the way a bass can,
    # so it does not get to decide the bar.
    rhythm_names = ["guitar_rhythm", "piano", "other"]
    if stem("guitar_rhythm") is None:
        rhythm_names.insert(0, "guitar")
    rhythm_paths = [p for p in (stem(name) for name in rhythm_names) if p]
    rhythm_chroma = harmony_chroma
    if rhythm_paths and rhythm_paths != harmony_paths:
        report(74, "Reading the rhythm guitar...")
        rhythm_mag = read_spec(_sum_stems(rhythm_paths, HARMONY_SR), HARMONY_HOP, 74, 16, "Reading the rhythm guitar...")
        rhythm_chroma = chromagram(rhythm_mag, HARMONY_SR, 110.0, 2000.0, tuning)

    report(92, "Finding the beat...")
    onset = None
    pulse = stem("drums") or (rhythm_paths[0] if rhythm_paths else bass_path)
    if pulse:
        onset = onset_envelope(read_mono(pulse, ONSET_SR))
    groove = estimate_groove(onset) if onset is not None and len(onset) else None
    if groove is not None:
        runs = bars_as_runs(bass_chroma, rhythm_chroma, groove)
        if len(runs) < 2:
            runs = bass_root_runs(bass_chroma)
            groove = None
    else:
        runs = bass_root_runs(bass_chroma)
    report(100, "Beat and key are ready.")

    return {
        "version": ANALYSIS_VERSION,
        "tuning_cents": round(tuning * 100),
        "sources": {"harmony": bool(harmony_paths), "bass": bool(bass_path), "vocal": vocal_midi is not None},
        "key": key,
        "chords": chords,
        "bass_runs": runs,
        "meter": groove,
    }


def load_if_fresh(song_dir, cache_path, vocal_midi=None):
    """The saved analysis when it still matches these stems, otherwise None."""
    stems = sorted(f for f in os.listdir(song_dir) if f.endswith(".wav"))
    signature = [[f, os.path.getmtime(os.path.join(song_dir, f))] for f in stems]
    try:
        with open(cache_path, "r", encoding="utf-8") as handle:
            saved = json.load(handle)
    except (OSError, ValueError):
        return None
    if saved.get("version") == ANALYSIS_VERSION and saved.get("signature") == signature \
            and saved.get("sources", {}).get("vocal") == (vocal_midi is not None):
        return saved
    return None


def cached_analysis(song_dir, cache_path, vocal_midi=None, progress=None):
    """analyze_song(), remembered next to the song so it only has to run once."""
    saved = load_if_fresh(song_dir, cache_path, vocal_midi)
    if saved is not None:
        if progress is not None:
            progress(100, "Beat and key are ready.")
        return saved
    stems = sorted(f for f in os.listdir(song_dir) if f.endswith(".wav"))
    signature = [[f, os.path.getmtime(os.path.join(song_dir, f))] for f in stems]
    result = analyze_song(song_dir, vocal_midi, progress=progress)
    result["signature"] = signature
    tmp = cache_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(result, handle)
    os.replace(tmp, cache_path)
    return result
