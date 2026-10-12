"""Checks the key and chord finder on made-up songs whose answer is known."""
import os
import sys
import tempfile

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "separator"))
import music_analysis as ma  # noqa: E402

RATE = 44100
NAMES = ma.SHARP_NAMES


def tone(freq, seconds, partials=5):
    t = np.arange(int(RATE * seconds)) / RATE
    out = sum(np.sin(2 * np.pi * freq * (h + 1) * t) / (h + 1) for h in range(partials))
    env = np.minimum(1, np.minimum(t * 40, (seconds - t) * 20))
    return out * env


def midi_hz(midi, cents=0):
    return 440.0 * 2 ** ((midi - 69 + cents / 100.0) / 12)


def make_song(progression, tonic, cents, loops=4, seconds=2.0, seed=0):
    """progression: list of (scale-degree semitone offset, 'maj'|'min'). Returns (bass, harmony, truth)."""
    rng = np.random.default_rng(seed)
    bass, harmony, truth = [], [], []
    for _ in range(loops):
        for offset, quality in progression:
            root = tonic + offset
            third = 4 if quality == "maj" else 3
            notes = [60 + (root % 12), 60 + (root % 12) + third, 60 + (root % 12) + 7]
            harmony.append(sum(tone(midi_hz(n, cents), seconds) for n in notes) * 0.3)
            bass.append(tone(midi_hz(36 + (root % 12), cents), seconds, partials=3) * 0.8)
            truth.append(NAMES[root % 12] + ("m" if quality == "min" else ""))
    bass = np.concatenate(bass)
    harmony = np.concatenate(harmony)
    harmony += rng.normal(0, 0.02, len(harmony))
    return bass.astype(np.float32), harmony.astype(np.float32), truth


def run(label, progression, tonic, cents, expect_key):
    bass, harmony, truth = make_song(progression, tonic, cents)
    with tempfile.TemporaryDirectory() as folder:
        for name, data in (("bass", bass), ("other", harmony)):
            sf.write(os.path.join(folder, name + ".wav"), np.stack([data, data], 1) * 0.5, RATE, subtype="PCM_16")
        result = ma.analyze_song(folder)
    key = result["key"]
    found = [c["name"] for c in result["chords"]]
    # Compare the chord at the middle of each 2-second chord.
    hit = 0
    for i, want in enumerate(truth):
        mid = i * 2.0 + 1.0
        got = next((c["name"] for c in result["chords"] if c["start"] <= mid < c["end"]), None)
        hit += got == want
    # A progression like F#m-D-A-E is honestly ambiguous between F# minor and its relative, A major.
    relative = {"A major": "F# minor", "F# minor": "A major"}.get(expect_key)
    ok = key["name"] in (expect_key, relative)
    print(f"{label}: key {key['name']} ({key['certainty']}, margin {key['margin']}) expected {expect_key} -> {'OK' if ok else 'WRONG'};"
          f" tuning {result['tuning_cents']} cents (real {cents}); chords right {hit}/{len(truth)}; first chords {found[:6]}")


# I-vi-IV-V in C major; and i-VI-III-VII in F# minor, 30 cents sharp.
run("C major, in tune", [(0, "maj"), (9, "min"), (5, "maj"), (7, "maj")], 0, 0, "C major")
run("G major, 30 cents flat", [(0, "maj"), (5, "maj"), (7, "maj"), (0, "maj")], 7, -30, "G major")
run("F# minor, 30 cents sharp", [(0, "min"), (8, "maj"), (3, "maj"), (10, "maj")], 6, 30, "F# minor")
run("A minor (Am-G-F-E)", [(0, "min"), (10, "maj"), (8, "maj"), (7, "maj")], 9, 0, "A minor")
