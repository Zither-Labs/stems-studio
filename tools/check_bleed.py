"""Tests the ghost-note check (separator/bleed_check.py) on a real song from the library.

    python tools/check_bleed.py <song id>

1. Real stems as they are: how much real singing does the check wrongly remove? (should be none)
2. Fake leak: the band (guitar + other stems) is mixed into the vocal stem at a low level, with a
   random tone-shape that changes every 2 s (a real leak is never a perfect copy). Where the
   vocal stem is otherwise empty, how many of the resulting ghost notes does the check remove?
   And how much real singing is lost on the way?
"""
import os
import sys
import tempfile

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "separator"))

import bleed_check as bc  # noqa: E402
import pitch_track as pt  # noqa: E402

OTHER_STEMS = ["guitar", "guitar_lead", "guitar_rhythm", "piano", "other"]


def random_tone_shape(signal, rate, ripple_db, rng, block_seconds=2.0):
    """Change the tone of `signal` by a random smooth +/- ripple_db curve, new curve every block."""
    out = np.zeros_like(signal)
    block = int(block_seconds * rate)
    for start in range(0, len(signal), block):
        piece = signal[start:start + block]
        spectrum = np.fft.rfft(piece)
        freqs = np.fft.rfftfreq(len(piece), 1.0 / rate)
        position = np.log2(np.maximum(freqs, 50.0) / 50.0)
        curve = np.zeros_like(position)
        for _ in range(4):
            curve += rng.uniform(0.2, 1.0) * np.sin(2 * np.pi * rng.uniform(0.15, 0.7) * position + rng.uniform(0, 6.28))
        curve = curve / max(1e-6, np.abs(curve).max()) * ripple_db
        out[start:start + len(piece)] = np.fft.irfft(spectrum * 10 ** (curve / 20.0), n=len(piece))
    return out


def voiced_seconds(midi, ranges):
    v = midi > 0
    return sum(v[int(a / pt.STEP_SECONDS):int(b / pt.STEP_SECONDS)].sum() for a, b in ranges) * pt.STEP_SECONDS


def main(song):
    import soundfile as sf
    from swift_f0 import SwiftF0

    root = os.path.join(os.environ.get("LOCALAPPDATA", ""), "StemsStudio", "library", song)
    vocal_path = os.path.join(root, "vocals.wav")
    others = [os.path.join(root, f"{n}.wav") for n in OTHER_STEMS if os.path.exists(os.path.join(root, f"{n}.wav"))]
    print("other stems used:", [os.path.basename(p) for p in others])
    detector = SwiftF0(threads=4, spin=False)

    vocal, rate = sf.read(vocal_path, dtype="float32", always_2d=True)
    vocal_mono = vocal.mean(axis=1)
    result = detector.detect(vocal_mono, rate, fmin=pt.FMIN_HZ, fmax=pt.FMAX_HZ)
    midi = pt.clean_track(result.pitch_hz, result.confidence, result.loudness_db)
    t0 = float(result.timestamps[0])
    cleaned, removed = bc.remove_ghost_notes(midi, pt.STEP_SECONDS, vocal_path, others, t0)
    lost = ((midi > 0) & (cleaned == 0)).sum() * pt.STEP_SECONDS
    print(f"\n1. real stems: {removed} notes removed, {lost:.2f} s of {(midi > 0).sum() * pt.STEP_SECONDS:.1f} s")

    # Fake leak. Ranges where this song's vocal stem is silent / really singing (from its lyrics).
    quiet = [(14, 29), (74, 86)]
    singing = [(31, 66), (97, 123)]
    rng = np.random.default_rng(7)
    band = None
    for path in others:
        a, _ = sf.read(path, dtype="float32", always_2d=True)
        a = a.mean(axis=1)
        band = a if band is None else band[:len(a)] + a[:len(band)]
    print("\n2. fake leak (gain relative to the band stems, tone-shape ripple)")
    print(f"   {'gain':>6s} {'ripple':>7s} | ghost s before -> after | real singing s before -> after")
    for gain_db in (-26, -20, -14):
        for ripple in (0, 6, 12):
            shaped = random_tone_shape(band, rate, ripple, rng) if ripple else band
            mixed = vocal_mono[:len(shaped)] + 10 ** (gain_db / 20.0) * shaped[:len(vocal_mono)]
            res = detector.detect(mixed.astype(np.float32), rate, fmin=pt.FMIN_HZ, fmax=pt.FMAX_HZ)
            m = pt.clean_track(res.pitch_hz, res.confidence, res.loudness_db)
            with tempfile.TemporaryDirectory() as tmp:
                leaky = os.path.join(tmp, "leaky.wav")
                sf.write(leaky, mixed.astype(np.float32), rate)
                after, _ = bc.remove_ghost_notes(m, pt.STEP_SECONDS, leaky, others, float(res.timestamps[0]))
            print(f"   {gain_db:6d} {ripple:7d} | {voiced_seconds(m, quiet):6.1f} -> {voiced_seconds(after, quiet):6.1f}"
                  f"       | {voiced_seconds(m, singing):6.1f} -> {voiced_seconds(after, singing):6.1f}")


if __name__ == "__main__":
    main(sys.argv[1])
