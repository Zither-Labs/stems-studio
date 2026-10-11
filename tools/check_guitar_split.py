"""Sanity checks for the stereo lead/rhythm guitar split, with sounds whose answer is known."""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "separator"))
import guitar_split as gs  # noqa: E402

rate = 44100
t = np.arange(rate * 6) / rate


def tone(freq, seed):
    rng = np.random.default_rng(seed)
    out = np.zeros_like(t)
    for h in range(1, 6):
        out += np.sin(2 * np.pi * freq * h * t + rng.uniform(0, 6)) / h
    return (out * 0.2).astype(np.float32)


def share(audio):
    center, sides = gs.split_stereo(audio)
    ec = float(np.sum(center.astype(np.float64) ** 2))
    es = float(np.sum(sides.astype(np.float64) ** 2))
    err = float(np.max(np.abs(center + sides - audio)))
    return ec / (ec + es), es / (ec + es), err


lead = tone(330, 1)
rhythm_l = tone(196, 2)
rhythm_r = tone(247, 3)

cases = {
    "mono guitar in the middle (expect center ~100%)": np.stack([lead, lead], 1),
    "one guitar hard left (expect sides ~100%)": np.stack([rhythm_l, np.zeros_like(lead)], 1),
    "two guitars, one hard left and one hard right (expect sides ~100%)": np.stack([rhythm_l, rhythm_r], 1),
    "lead centre + rhythm left/right (expect centre ~ lead share)": np.stack([lead + rhythm_l, lead + rhythm_r], 1),
    "centre guitar with a little stereo reverb difference": np.stack([lead + 0.05 * rhythm_l, lead + 0.05 * rhythm_r], 1),
}
for label, audio in cases.items():
    c, s, err = share(audio.astype(np.float32))
    print(f"{label}\n    center {c:5.0%}  sides {s:5.0%}  (adds back up to original within {err:.1e})")

# Where does the lead energy go in the mixed case?
mix = np.stack([lead + rhythm_l, lead + rhythm_r], 1).astype(np.float32)
center, sides = gs.split_stereo(mix)
def corr(a, b):
    a = a.mean(axis=1) if a.ndim == 2 else a
    return float(np.corrcoef(a, b)[0, 1])
print(f"\nmixed case: centre stem vs the true lead: correlation {corr(center, lead):.2f}")
print(f"mixed case: sides stem vs the true rhythm (left): correlation {corr(sides[:, 0], rhythm_l):.2f}")
