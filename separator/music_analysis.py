"""
Key and chord detection from the separated stems.

Working on separated stems is what makes this more reliable than analysing a full mix:

  * the BASS stem says which note the music rests on (the bass plays roots far more often
    than anything else), which is the best clue to the key's home note;
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

ANALYSIS_VERSION = 1

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


def spectrogram(x, n_fft, hop):
    """Magnitude spectrogram, (frames, bins). Hann window."""
    if len(x) < n_fft:
        x = np.pad(x, (0, n_fft - len(x)))
    window = np.hanning(n_fft + 1)[:-1].astype(np.float32)
    n_frames = 1 + (len(x) - n_fft) // hop
    out = np.empty((n_frames, n_fft // 2 + 1), dtype=np.float32)
    for first in range(0, n_frames, 256):
        last = min(n_frames, first + 256)
        index = (np.arange(first, last) * hop)[:, None] + np.arange(n_fft)[None, :]
        out[first:last] = np.abs(np.fft.rfft(x[index] * window, axis=1))
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


def analyze_song(song_dir, vocal_midi=None):
    """Find the key and chords of a separated song. Returns a JSON-ready dict."""
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

    if harmony_paths:
        harmony_mag = spectrogram(_sum_stems(harmony_paths, HARMONY_SR), N_FFT, HARMONY_HOP)
        tuning = estimate_tuning(harmony_mag, HARMONY_SR, 110.0, 2000.0)
        harmony_chroma = chromagram(harmony_mag, HARMONY_SR, 110.0, 2000.0, tuning)
    if bass_path:
        bass_mag = spectrogram(read_mono(bass_path, BASS_SR), N_FFT, BASS_HOP)
        if harmony_chroma is None:
            tuning = estimate_tuning(bass_mag, BASS_SR, 40.0, 400.0)
        bass_chroma = chromagram(bass_mag, BASS_SR, 40.0, 400.0, tuning)

    vec = lambda c: None if c is None else c.sum(axis=0).astype(np.float64)    # noqa: E731
    key = detect_key(vec(harmony_chroma), vec(bass_chroma), vocal_histogram(vocal_midi, tuning))

    chords = []
    if key and harmony_chroma is not None:
        bass_for_chords = bass_chroma if bass_chroma is not None else np.zeros_like(harmony_chroma)
        chords = detect_chords(harmony_chroma, bass_for_chords, key)

    return {
        "version": ANALYSIS_VERSION,
        "tuning_cents": round(tuning * 100),
        "sources": {"harmony": bool(harmony_paths), "bass": bool(bass_path), "vocal": vocal_midi is not None},
        "key": key,
        "chords": chords,
    }


def cached_analysis(song_dir, cache_path, vocal_midi=None):
    """analyze_song(), remembered next to the song so it only has to run once."""
    stems = sorted(f for f in os.listdir(song_dir) if f.endswith(".wav"))
    signature = [[f, os.path.getmtime(os.path.join(song_dir, f))] for f in stems]
    try:
        with open(cache_path, "r", encoding="utf-8") as handle:
            saved = json.load(handle)
        if saved.get("version") == ANALYSIS_VERSION and saved.get("signature") == signature \
                and saved.get("sources", {}).get("vocal") == (vocal_midi is not None):
            return saved
    except (OSError, ValueError):
        pass
    result = analyze_song(song_dir, vocal_midi)
    result["signature"] = signature
    tmp = cache_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(result, handle)
    os.replace(tmp, cache_path)
    return result
