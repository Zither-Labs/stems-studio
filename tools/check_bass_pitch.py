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

# The highway merge replaces an octave-high reading and leaves a different note alone.
swift = np.array([40.0] * 20 + [45.0] * 20 + [40.0] * 10, dtype=float)
low = np.array([28.0] * 20 + [33.0] * 20 + [35.0] * 10, dtype=float)
merged = pt.apply_low_bass(swift, 0.0, low, 0.0)
assert abs(float(np.median(merged[:20])) - 28.0) < 0.2
assert abs(float(np.median(merged[20:40])) - 33.0) < 0.2
assert abs(float(np.median(merged[40:])) - 40.0) < 0.2, merged[40:]

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
