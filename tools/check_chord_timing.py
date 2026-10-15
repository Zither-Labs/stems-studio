#!/usr/bin/env python3
"""Chord changes land when the bass and the guitar change, not a beat early.

Made-up songs: drums on every beat, a power-chord guitar and a bass that move together
between E and G. Every chord in the listen has to be the one actually sounding.
"""

import os
import sys
import tempfile

import numpy as np
import soundfile as sf

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "separator"))
import music_analysis as ma  # noqa: E402

RATE = 44100


def note(freq, seconds, partials):
    t = np.arange(int(RATE * seconds)) / RATE
    wave = sum(amp * np.sin(2 * np.pi * freq * (k + 1) * t) for k, amp in enumerate(partials))
    fade = min(len(wave) // 4, int(0.01 * RATE))
    if fade:
        wave[:fade] *= np.linspace(0, 1, fade)
        wave[-fade:] *= np.linspace(1, 0, fade)
    return wave


def hz(midi):
    return 440.0 * 2 ** ((midi - 69) / 12.0)


def song(folder, beats, beats_per_chord):
    """beats: the time of every beat. E5 and G5 trade every beats_per_chord beats; the bass plays E1 and G1."""
    chords = [(40, 28), (43, 31)]
    guitar, bass, truth = [], [], []
    changes = beats[::beats_per_chord]
    for index, start in enumerate(changes[:-1]):
        span = changes[index + 1] - start
        guitar_root, bass_note = chords[index % 2]
        tones = (guitar_root, guitar_root + 7, guitar_root + 12)
        guitar.append(sum(note(hz(m), span, (1.0, 0.5, 0.3, 0.2)) for m in tones) * 0.25)
        bass.append(note(hz(bass_note), span, (0.6, 1.0, 0.5, 0.25)) * 0.5)
        truth.append((start, changes[index + 1], guitar_root % 12, bass_note))
    guitar = np.concatenate(guitar)
    bass = np.concatenate(bass)
    n = min(len(guitar), len(bass))
    drums = np.zeros(n)
    hit = int(0.03 * RATE)
    rng = np.random.default_rng(0)
    for count, at_time in enumerate(beats):
        at = int(at_time * RATE)
        if at >= n:
            break
        size = min(hit, n - at)
        loud = 1.0 if count % 4 == 0 else 0.5
        drums[at:at + size] += loud * rng.standard_normal(size) * np.exp(-np.linspace(0, 6, size))
    sf.write(os.path.join(folder, "guitar.wav"), guitar[:n].astype(np.float32), RATE)
    sf.write(os.path.join(folder, "bass.wav"), bass[:n].astype(np.float32), RATE)
    sf.write(os.path.join(folder, "drums.wav"), drums.astype(np.float32), RATE)
    return truth


def root_at(runs, time):
    for run in runs:
        if run["start"] <= time < run["end"]:
            return run["root"]
    return None


def wrong_chords(result, truth):
    runs = result["bass_runs"]
    assert runs
    wrong = []
    for start, end, root, _ in truth:
        for fraction in (0.25, 0.5, 0.75):
            time = start + (end - start) * fraction
            found = root_at(runs, time)
            if found is not None and found != root:
                wrong.append((round(time, 2), found, root))
    return wrong


def bass_line(truth):
    dt = 256 / 16000
    frames = int(truth[-1][1] / dt) + 1
    midi = np.zeros(frames)
    for start, end, _, bass_note in truth:
        midi[int(start / dt):int(end / dt)] = bass_note
    return {"t0": 0.0, "dt": dt, "midi": midi.tolist()}


cases = {
    "steady 120, change every beat": (list(np.arange(0, 24, 0.5)), 1),
    "steady 130, change every beat": (list(np.arange(0, 24, 0.46)), 1),
    "steady 143, change every two beats": (list(np.arange(0, 24, 0.42)), 2),
}
# A band that is not playing to a click: 116 bpm drifting up to 128 and back.
beat_lengths = 60.0 / (122 + 6 * np.sin(np.linspace(0, 2 * np.pi, 60)))
cases["drifting 116 to 128, change every two beats"] = (list(np.concatenate([[0.0], np.cumsum(beat_lengths)])), 2)

for label, (beats, every) in cases.items():
    with tempfile.TemporaryDirectory() as folder:
        truth = song(folder, beats, every)
        result = ma.analyze_song(folder)
        wrong = wrong_chords(result, truth)
        assert len(wrong) <= 2, (label, "spectrum bass", wrong[:8])
        result = ma.analyze_song(folder, bass_line=bass_line(truth))
        wrong = wrong_chords(result, truth)
        assert len(wrong) <= 2, (label, "highway bass", wrong[:8])
        assert result["sources"]["bass_line"] is not None

# The beat tracker follows a tempo that moves, where one fixed grid slides off it.
onset = np.zeros(int(sum(beat_lengths) / ma.ONSET_FRAME) + 40)
times = np.concatenate([[0.0], np.cumsum(beat_lengths)])
for t in times:
    i = int(round(t / ma.ONSET_FRAME))
    if i < len(onset):
        onset[i] = 1.0
tracked = ma.track_beats(onset, float(np.median(beat_lengths)))
offset = (1024 - ma.ONSET_HOP / 2) / ma.ONSET_SR
errors = [min(abs(b - offset - t) for t in times) for b in tracked]
assert max(errors) < 0.03, max(errors)

print("chord timing ok")
