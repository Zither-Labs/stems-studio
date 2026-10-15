#!/usr/bin/env python3
"""The low strings of a bass are reported at their own pitch, not an octave higher."""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "separator"))
import pitch_track as pt


def tone(freq, seconds=1.6, rate=44100, harmonics=(1.0,)):
    t = np.arange(int(seconds * rate)) / rate
    wave = np.zeros_like(t)
    for k, amp in enumerate(harmonics):
        wave += amp * np.sin(2 * np.pi * freq * (k + 1) * t)
    return wave.astype(np.float64)


def voiced_median(midi):
    heard = midi[midi > 0]
    assert len(heard) > 10, len(heard)
    return float(np.median(heard))


# Low E (41 Hz) with a strong second harmonic must stay on E1 (MIDI 28), not jump to E2 (40).
low_e = voiced_median(pt.low_fundamental_track(tone(41.203, harmonics=(1.0, 0.8, 0.35)), 44100)[0])
assert abs(low_e - 28.0) < 0.6, low_e

# Low B (31 Hz), the 5-string open string.
low_b = voiced_median(pt.low_fundamental_track(tone(30.868, harmonics=(1.0, 0.7, 0.3)), 44100)[0])
assert abs(low_b - 23.0) < 0.6, low_b

# A real E2, with no energy an octave down, stays E2.
high_e = voiced_median(pt.low_fundamental_track(tone(82.407, harmonics=(1.0,)), 44100)[0])
assert abs(high_e - 40.0) < 0.6, high_e

# Notes in the middle of the bass must stay there. The deepest repeating period of
# these notes is a fake octave or two below, and following it used to wipe the line out.
for freq, midi_note in ((110.0, 45), (146.83, 50), (164.81, 52), (196.0, 55), (220.0, 57)):
    heard = voiced_median(pt.low_fundamental_track(tone(freq, harmonics=(0.6, 1.0, 0.4)), 44100)[0])
    assert abs(heard - midi_note) < 0.8, (freq, heard)

# A low E whose fundamental is barely in the sound may stay an octave high. It must
# not go silent, and it must not fall another octave below the real note.
bright = voiced_median(pt.low_fundamental_track(tone(41.203, harmonics=(0.15, 1.0, 0.6, 0.3)), 44100)[0])
assert min(abs(bright - 28.0), abs(bright - 40.0)) < 0.8, bright

# Broadband noise is not a bass line.
rng = np.random.default_rng(1)
noise = rng.standard_normal(int(1.6 * 44100))
noise_midi = pt.low_fundamental_track(noise, 44100)[0]
assert (noise_midi > 0).mean() < 0.1, (noise_midi > 0).mean()

# The highway merge replaces an octave-high reading and leaves a different note alone.
swift = np.array([40.0] * 20 + [45.0] * 20 + [40.0] * 10, dtype=float)
low = np.array([28.0] * 20 + [33.0] * 20 + [35.0] * 10, dtype=float)
merged = pt.apply_low_bass(swift, 0.0, low, 0.0)
assert abs(float(np.median(merged[:20])) - 28.0) < 0.2
assert abs(float(np.median(merged[20:40])) - 33.0) < 0.2
assert abs(float(np.median(merged[40:])) - 40.0) < 0.2, merged[40:]

# An empty detector track still takes a note above Bb2. Those used to be dropped,
# so a bass line that lives there came back with no pitch at all.
empty = np.zeros(30)
filled = pt.apply_low_bass(empty, 0.0, np.full(30, 52.0), 0.0)
assert abs(float(np.median(filled)) - 52.0) < 0.2, filled[:5]
# An octave-high reading above Bb2 is still brought down.
octave = pt.apply_low_bass(np.full(20, 64.0), 0.0, np.full(20, 52.0), 0.0)
assert abs(float(np.median(octave)) - 52.0) < 0.2, octave[:3]
# A reading above the bass range is ignored, so a high solo stays put.
solo = np.full(20, 74.0)
kept_solo = pt.apply_low_bass(solo, 0.0, np.full(20, 64.0), 0.0)
assert abs(float(np.median(kept_solo)) - 74.0) < 0.2, kept_solo[:3]

# Bass keeps a steady line the detector is only moderately sure about. Singing does not.
steady_hz = np.full(40, 110.0)
steady_conf = np.full(40, 0.55)
steady_loud = np.full(40, -18.0)
bass_line = pt.clean_track(steady_hz, steady_conf, steady_loud, fmin=28, fmax=260, keep_low=True)
assert abs(float(np.median(bass_line[bass_line > 0])) - 45.0) < 0.6, bass_line[:5]
sung = pt.clean_track(steady_hz, steady_conf, steady_loud)
assert not (sung > 0).any()

# The octave cleaner must not lift a real low E up toward the middle of the line.
midi = np.zeros(40)
voiced = np.zeros(40, dtype=bool)
midi[2:18] = 28.0
midi[18:40] = 50.0
voiced[2:] = True
kept = pt.repair_octaves(midi, voiced, 48.0, allow_upward=False)
assert float(np.median(kept[2:18])) < 34.0, kept[2:18]
lifted = pt.repair_octaves(midi, voiced, 48.0, allow_upward=True)
assert float(np.median(lifted[2:18])) > 34.0, lifted[2:18]

print("bass pitch ok")
