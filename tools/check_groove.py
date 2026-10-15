"""The beat and the meter keep a walking bass from inventing a new chord on every note."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "separator"))
import music_analysis as ma  # noqa: E402


def clicks(meter, bars, accent=1.0, weak=0.4):
    lag = 22
    length = lag * meter * bars
    onset = np.zeros(length)
    for bar in range(bars):
        for beat in range(meter):
            at = bar * lag * meter + beat * lag
            onset[at] = accent if beat == 0 else weak
            if at + 1 < length:
                onset[at + 1] = onset[at] * 0.35
    return onset


four = ma.estimate_groove(clicks(4, 16), frame_seconds=ma.ONSET_FRAME)
assert four is not None, four
assert four["beats_per_bar"] == 4, four
assert 100 <= four["bpm"] <= 140, four

three = ma.estimate_groove(clicks(3, 16), frame_seconds=ma.ONSET_FRAME)
assert three is not None, three
assert three["beats_per_bar"] == 3, three

# One bar of G, the bass walking G B D E, the guitar holding G B D.
beat = 0.5
frames_per_beat = int(round(beat / ma.FRAME_SECONDS))
bass = np.zeros((frames_per_beat * 4, 12), dtype=np.float32)
harmony = np.zeros_like(bass)
for frame in range(len(bass)):
    harmony[frame, 7] = 1
    harmony[frame, 11] = 1
    harmony[frame, 2] = 1
for beat_index, pitch in enumerate((7, 11, 2, 4)):
    bass[beat_index * frames_per_beat:(beat_index + 1) * frames_per_beat, pitch] = 1
root = ma.root_for_span(bass, harmony, 0.0, beat * 4, beat, 4)
assert root == 7, root

# No guitar. The downbeat is still G, so the walk does not become four chords.
root = ma.root_for_span(bass, None, 0.0, beat * 4, beat, 4)
assert root == 7, root

# Next bar the guitar moves to Em and the bass walks off the root. The bar stays Em.
em = np.zeros_like(bass)
for frame in range(len(em)):
    em[frame, 4] = 1
    em[frame, 7] = 1
    em[frame, 11] = 1
walk = np.zeros_like(bass)
for beat_index, pitch in enumerate((4, 7, 11, 2)):
    walk[beat_index * frames_per_beat:(beat_index + 1) * frames_per_beat, pitch] = 1
both_bass = np.vstack([bass, walk])
both_harmony = np.vstack([harmony, em])
groove = {"bpm": 120, "beats_per_bar": 4, "beat_seconds": beat, "phase_seconds": 0.0}
runs = ma.bars_as_runs(both_bass, both_harmony, groove)
assert [run["root"] for run in runs] == [7, 4], runs

# Two chords in one 4/4 bar: G for two beats, then D. The walk inside each half stays put.
half = np.zeros((frames_per_beat * 4, 12), dtype=np.float32)
half_bass = np.zeros_like(half)
for beat_index, pitches in enumerate(((7, 11), (7, 2), (2, 6), (2, 9))):
    sl = slice(beat_index * frames_per_beat, (beat_index + 1) * frames_per_beat)
    half_bass[sl, pitches[1]] = 1
    for pitch in ((7, 11, 2) if beat_index < 2 else (2, 6, 9)):
        half[sl, pitch] = 1
split = ma.bars_as_runs(half_bass, half, groove)
assert [run["root"] for run in split] == [7, 2], split

print("groove ok", four["bpm"], "bpm", four["beats_per_bar"])
