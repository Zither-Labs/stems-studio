"""Where is the vocal stem clearly active but the highway has no pitch?

Usage:  python tools/check_vocal_coverage.py <song id or path to vocals.wav> [--redo]

Lists every stretch of at least 0.3 s where the vocal stem is loud but no pitch was found, with
how loud it is and how confident the detector was, so the cause (breathy, whispered, growled,
very high or very low, bleed...) can be seen.
"""
import os
import sys

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "separator"))

import pitch_track as pt  # noqa: E402


def find_wav(arg):
    if os.path.isfile(arg):
        return arg
    root = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "StemsStudio", "library", arg)
    return os.path.join(root, "vocals.wav")


def main():
    import soundfile as sf
    from swift_f0 import SwiftF0

    wav = find_wav(sys.argv[1])
    audio, rate = sf.read(wav, dtype="float32", always_2d=True)
    mono = audio.mean(axis=1)
    result = SwiftF0(threads=4, spin=False).detect(mono, rate, fmin=pt.FMIN_HZ, fmax=pt.FMAX_HZ)
    midi = pt.clean_track(result.pitch_hz, result.confidence, result.loudness_db)
    n = len(midi)

    # Loudness of the stem on the same 16 ms grid.
    hop = int(round(pt.STEP_SECONDS * rate))
    frames = np.array([mono[i * hop:(i + 1) * hop] for i in range(n) if (i + 1) * hop <= len(mono)], dtype=object)
    rms = np.array([np.sqrt(np.mean(f ** 2)) if len(f) else 0.0 for f in frames])
    rms = np.pad(rms, (0, n - len(rms)))
    db = 20 * np.log10(np.maximum(rms, 1e-7))
    active_level = np.percentile(db[midi > 0], 50) if (midi > 0).any() else db.max()
    threshold = active_level - 18
    active = db >= threshold

    missing = active & (midi == 0)
    print(f"{wav}\n  frames {n}, vocal loud {active.sum()}, with pitch {(midi > 0).sum()}, "
          f"loud but no pitch {missing.sum()} ({missing.sum() / max(1, active.sum()):.1%})")
    for start, end in pt._runs(missing):
        seconds = (end - start) * pt.STEP_SECONDS
        if seconds < 0.3:
            continue
        seg = slice(start, end)
        print(f"  {start * pt.STEP_SECONDS:7.2f}s  {seconds:5.2f}s  level {db[seg].mean():6.1f} dB  "
              f"confidence mean {result.confidence[seg].mean():.2f} max {result.confidence[seg].max():.2f}  "
              f"hz median {np.median(result.pitch_hz[seg]):6.0f}")


if __name__ == "__main__":
    main()
