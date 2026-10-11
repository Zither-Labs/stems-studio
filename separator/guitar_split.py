"""
Experimental lead / rhythm guitar split, by position in the stereo picture.

No free model can reliably tell "lead" from "rhythm" (they are playing roles, not different
instruments), so this uses the way rock records are usually mixed instead: the lead guitar sits
in the middle, while the rhythm guitars are double-tracked and panned left and right.

For every small slice of the sound (a time frame and a frequency), the left and right channels
are compared. If they match, that slice sits in the middle and goes to the "center" stem. If
they differ, it goes to the "sides" stem. The two stems always add back up to the original
guitar. This is the "phantom center" idea that the MSST community also uses on guitar stems.

When the guitars in a song are all in the middle (mono), everything ends up in the center
stem and the sides stem is practically silent, so the app hides it.
"""

import os
import sys

import numpy as np

FRAME = 4096
HOP = FRAME // 4
BATCH_FRAMES = 256          # frames processed at a time, to keep memory small
CENTER_SHARPNESS = 2.0      # higher = stricter about what counts as "in the middle"


def _center_mask(left, right):
    """1 where left and right match (middle), towards 0 where they differ (sides)."""
    mag_l = np.abs(left)
    mag_r = np.abs(right)
    # Same loudness in both ears: 1.0. Only in one ear: 0.0.
    level_match = (2.0 * mag_l * mag_r) / (mag_l * mag_l + mag_r * mag_r + 1e-12)
    # Same phase in both ears (not just the same loudness).
    phase_match = np.cos(np.angle(left) - np.angle(right))
    mask = level_match * np.clip(phase_match, 0.0, 1.0)
    return np.clip(mask, 0.0, 1.0) ** CENTER_SHARPNESS


def split_stereo(audio):
    """audio: float32 array (samples, 2). Returns (center, sides), both (samples, 2)."""
    samples = audio.shape[0]
    window = np.hanning(FRAME + 1)[:-1].astype(np.float32)
    pad = FRAME
    padded = np.zeros((samples + 2 * pad + FRAME, 2), dtype=np.float32)
    padded[pad:pad + samples] = audio

    center = np.zeros_like(padded)
    norm = np.zeros(padded.shape[0], dtype=np.float32)

    n_frames = (padded.shape[0] - FRAME) // HOP + 1
    for first in range(0, n_frames, BATCH_FRAMES):
        last = min(n_frames, first + BATCH_FRAMES)
        starts = np.arange(first, last) * HOP
        index = starts[:, None] + np.arange(FRAME)[None, :]
        left = np.fft.rfft(padded[:, 0][index] * window, axis=1)
        right = np.fft.rfft(padded[:, 1][index] * window, axis=1)

        mask = _center_mask(left, right)
        # Smooth the mask over time and frequency a little, so it does not flutter ("musical noise").
        kernel = np.array([0.25, 0.5, 0.25], dtype=np.float32)
        mask = np.apply_along_axis(lambda row: np.convolve(row, kernel, mode="same"), 1, mask)
        mask = np.apply_along_axis(lambda col: np.convolve(col, kernel, mode="same"), 0, mask)

        for ch, spec in enumerate((left, right)):
            frames = np.fft.irfft(spec * mask, n=FRAME, axis=1).astype(np.float32) * window
            for k, start in enumerate(starts):
                center[start:start + FRAME, ch] += frames[k]
        for start in starts:
            norm[start:start + FRAME] += window * window

    norm = np.maximum(norm, 1e-6)
    center = center / norm[:, None]
    center = center[pad:pad + samples]
    sides = audio - center
    return center, sides


def split_file(source_wav, center_wav, sides_wav):
    """Split a stereo guitar stem into two files. Returns the share of energy in each."""
    import soundfile as sf

    audio, rate = sf.read(source_wav, dtype="float32", always_2d=True)
    if audio.shape[1] == 1:
        audio = np.repeat(audio, 2, axis=1)
    center, sides = split_stereo(audio[:, :2])
    sf.write(center_wav, center, rate, subtype="PCM_16")
    sf.write(sides_wav, sides, rate, subtype="PCM_16")
    e_center = float(np.sum(np.square(center, dtype=np.float64)))
    e_sides = float(np.sum(np.square(sides, dtype=np.float64)))
    total = e_center + e_sides + 1e-12
    return e_center / total, e_sides / total


if __name__ == "__main__":
    src = sys.argv[1]
    out_dir = sys.argv[2]
    c, s = split_file(src, os.path.join(out_dir, "guitar_lead.wav"), os.path.join(out_dir, "guitar_rhythm.wav"))
    print(f"energy share: center {c:.0%}, sides {s:.0%}")
