#!/usr/bin/env python3
"""The chord guessers (Chordino, madmom, autochord, BTC) hear the chords a made-up song plays.

The labels each guesser writes ("Am7b5/G", "A:hdim7", "C:maj/3") are read the same way every time.
Then every guesser that is installed (tools/install_chord_guessers.py) listens to a song of guitar
chords over a bass, Em G C D twice, and most of the song has to come back with the right root.
Guessers that are not installed are skipped.

Run:  python tools/check_chord_guessers.py
"""
import os
import shutil
import sys
import tempfile

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "separator"))
import chord_guessers as cg  # noqa: E402

RATE = 44100
# (root pitch class, chord tones above the root, bass MIDI note)
PROGRESSION = [(4, (0, 3, 7), 40), (7, (0, 4, 7), 43), (0, (0, 4, 7), 36), (2, (0, 4, 7), 38)]
SECONDS_PER_CHORD = 2.4


def check_labels():
    cases = {
        "Am7b5/G": (9, "m7b5", 7),
        "Ebm": (3, "m", None),
        "Bmaj7": (11, "maj7", None),
        "F#/C#": (6, "", 1),
        "A:hdim7": (9, "m7b5", None),
        "E:min": (4, "m", None),
        "C:maj/3": (0, "", 4),
        "G": (7, "", None),
        "D#:min7": (3, "m7", None),
        "Bb:maj": (10, "", None),
        "C:sus4": (0, "sus4", None),
    }
    for label, (root, quality, bass) in cases.items():
        parsed = cg.parse_label(label)
        assert parsed == {"root": root, "quality": quality, "bass": bass}, (label, parsed)
    for silent in ("N", "X", "", None):
        assert cg.parse_label(silent) is None, silent

    tidied = cg.tidy([
        {"start": 0.0, "end": 0.4, "label": "N"},
        {"start": 0.4, "end": 2.0, "label": "E:min"},
        {"start": 2.0, "end": 2.1, "label": "B"},
        {"start": 2.1, "end": 4.0, "label": "E:min"},
        {"start": 4.0, "end": 6.0, "label": "G"},
    ])
    assert [(c["start"], c["end"], c["root"], c["quality"]) for c in tidied] == \
        [(0.4, 4.0, 4, "m"), (4.0, 6.0, 7, "")], tidied
    print("ok   labels from all four guessers read the same way")


def tone(freq, seconds):
    t = np.arange(int(RATE * seconds)) / RATE
    wave = sum(amp * np.sin(2 * np.pi * freq * (k + 1) * t) for k, amp in enumerate((1.0, 0.5, 0.33, 0.25, 0.2)))
    envelope = np.minimum(1.0, t / 0.01) * np.exp(-t * 0.6)
    return wave * envelope


def hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12.0)


def make_song(folder, repeats=2):
    guitar, bass, truth = [], [], []
    at = 0.0
    for _ in range(repeats):
        for root, shape, bass_note in PROGRESSION:
            low = 52 + ((root - 4) % 12)
            guitar.append(sum(tone(hz(low + step), SECONDS_PER_CHORD) for step in shape + (12,)) * 0.2)
            bass.append(tone(hz(bass_note), SECONDS_PER_CHORD) * 0.5)
            truth.append((at, at + SECONDS_PER_CHORD, root))
            at += SECONDS_PER_CHORD
    sf.write(os.path.join(folder, "guitar.wav"), np.concatenate(guitar).astype(np.float32), RATE)
    sf.write(os.path.join(folder, "bass.wav"), np.concatenate(bass).astype(np.float32), RATE)
    sf.write(os.path.join(folder, "drums.wav"), np.zeros(int(at * RATE), dtype=np.float32), RATE)
    return truth


def agreement(chords, truth):
    """Share of the song (inner part of each chord, away from the edges) where the root is right."""
    right = total = 0.0
    for start, end, root in truth:
        for step in np.arange(start + 0.3, end - 0.3, 0.05):
            total += 1
            here = [c for c in chords if c["start"] <= step < c["end"]]
            if here and here[0]["root"] == root:
                right += 1
    return right / total if total else 0.0


def check_guessers():
    ready = [item["id"] for item in cg.listing() if item["ready"] and item["id"] != "app"]
    skipped = [item["id"] for item in cg.listing() if not item["ready"]]
    if skipped:
        print(f"skip {', '.join(skipped)} (not installed: python tools/install_chord_guessers.py)")
    if not ready:
        return True
    folder = tempfile.mkdtemp(prefix="stems-guessers-")
    passed = True
    try:
        truth = make_song(folder)
        assert cg.harmony_stems(folder) == ["bass", "guitar"], cg.harmony_stems(folder)
        for engine in ready:
            segments = cg.guess(folder, engine)
            chords = cg.tidy(segments)
            score = agreement(chords, truth)
            names = " ".join(c["name"] for c in chords[:10])
            ok = score >= 0.7
            passed &= ok
            print(f"{'ok  ' if ok else 'FAIL'} {engine:<9} {score:4.0%} of the song has the right root  ({names})")
            assert cg.load_if_fresh(folder, engine) == segments, "the answer is kept with the song"
        os.utime(os.path.join(folder, "bass.wav"), (1, 1))
        assert cg.load_if_fresh(folder, ready[0]) is None, "a changed stem is heard again"
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    return passed


def main():
    check_labels()
    return 0 if check_guessers() else 1


if __name__ == "__main__":
    sys.exit(main())
