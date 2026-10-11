"""Quality check for the vocal pitch tracker: compares the raw detector with the cleaned track.

    .venv\\Scripts\\python.exe tools\\check_pitch.py path\\to\\vocals.wav
"""
import os
import sys
import time

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "separator"))
import pitch_track as pt  # noqa: E402


def jump_times(midi):
    """Times of sudden octave-sized jumps between neighbouring voiced frames."""
    v = midi > 0
    return [i * pt.STEP_SECONDS for i in range(1, len(midi))
            if v[i] and v[i - 1] and abs(midi[i] - midi[i - 1]) >= 9]


def report(label, midi):
    r = pt._runs(midi > 0)
    lengths = np.array([e - s for s, e in r]) * pt.STEP_SECONDS
    voiced = (midi > 0).sum() * pt.STEP_SECONDS
    short = int((lengths < 0.15).sum()) if len(lengths) else 0
    print(f"{label:8s} voiced {voiced:6.1f}s  runs {len(r):4d}  runs<0.15s {short:4d}"
          f"  octave-sized jumps {len(jump_times(midi)):4d}", flush=True)


def main(path):
    import soundfile as sf
    from swift_f0 import SwiftF0

    audio, rate = sf.read(path, dtype="float32", always_2d=True)
    mono = audio.mean(axis=1)
    t = time.time()
    res = SwiftF0(threads=4, spin=False).detect(mono, rate, fmin=pt.FMIN_HZ, fmax=pt.FMAX_HZ)
    print(f"detector took {time.time() - t:.1f}s for {len(mono) / rate:.0f}s of audio", flush=True)

    raw_midi = np.where(res.confidence >= 0.5, pt.hz_to_midi(res.pitch_hz), 0.0)
    report("raw", raw_midi)
    t = time.time()
    cleaned = pt.clean_track(res.pitch_hz, res.confidence, res.loudness_db)
    print(f"clean-up took {time.time() - t:.1f}s", flush=True)
    report("cleaned", cleaned)
    print("remaining jumps at (s):", [round(x, 2) for x in jump_times(cleaned)[:30]], flush=True)


if __name__ == "__main__":
    main(sys.argv[1])
