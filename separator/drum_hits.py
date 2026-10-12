"""When the drums hit: a list of hit times for kick, snare, toms, hi-hat, ride and crash.

With the drums split into parts (drums_kick.wav ...) every part is searched for hits on its own,
which is accurate. Without the split only the whole drum track exists, and the hits are guessed
from three frequency bands (low = kick, middle = snare, high = hi-hat); that is marked as
approximate, because a kick and a snare share a lot of sound.

A hit is a sudden rise of energy in the part (spectral flux), picked at its peaks, and dropped
when it is far quieter than the part's real hits (the leftovers of other drums in a split part).
numpy only.
"""
import json
import os
import sys

import numpy as np

import bleed_check

VERSION = 2
SILENT_PART_DB = -50.0         # a part quieter than this overall is empty
SILENT_PART_SHARE = 0.002      # ...or with less than this share of the whole kit's energy
SAMPLE_RATE = 22050
N_FFT = 1024
HOP = 256
FRAME_SECONDS = HOP / SAMPLE_RATE

# (lane id, label, file, shortest gap between two hits in seconds)
PARTS = [
    ("kick", "Kick", "drums_kick.wav", 0.07),
    ("snare", "Snare", "drums_snare.wav", 0.08),
    ("toms", "Toms", "drums_toms.wav", 0.08),
    ("hh", "Hi-hat", "drums_hh.wav", 0.045),
    ("ride", "Ride", "drums_ride.wav", 0.09),
    ("crash", "Crash", "drums_crash.wav", 0.25),
]
# Without the split: frequency band (Hz) for each lane.
BANDS = {"kick": (30, 150), "snare": (200, 3000), "hh": (6000, 11000)}

FLUX_THRESHOLD = 0.22          # of the part's strong onset level (95th percentile)
QUIET_HIT_SHARE = 0.12         # a hit with less than this share of the typical hit's energy is leftover
ONSET_LAG_SECONDS = -0.010     # measured on test clicks: the rise is seen about 20 ms before the frame's centre


def _spectrogram(mono):
    window = np.hanning(N_FFT).astype(np.float32)
    count = max(0, (len(mono) - N_FFT) // HOP + 1)
    out = np.empty((N_FFT // 2 + 1, count), dtype=np.float32)
    step = 512
    for first in range(0, count, step):
        last = min(count, first + step)
        idx = np.arange(first, last)[:, None] * HOP + np.arange(N_FFT)[None, :]
        out[:, first:last] = np.abs(np.fft.rfft(mono[idx] * window, axis=1)).T
    return out


def hits_in_band(magnitude, band, min_gap):
    """Hit times and strengths (0..1) in one band of a magnitude spectrogram."""
    freqs = np.fft.rfftfreq(N_FFT, 1.0 / SAMPLE_RATE)
    keep = (freqs >= band[0]) & (freqs <= band[1]) if band else np.ones(len(freqs), dtype=bool)
    mag = magnitude[keep]
    if mag.shape[1] < 8:
        return []
    compressed = np.log1p(mag * 50.0)
    flux = np.maximum(0.0, np.diff(compressed, axis=1, prepend=compressed[:, :1])).sum(axis=0)
    flux = np.convolve(flux, np.array([0.25, 0.5, 0.25]), mode="same")
    energy = (mag ** 2).sum(axis=0)

    reference = np.percentile(flux, 95)
    if reference <= 1e-6:
        return []
    gap = max(1, int(round(min_gap / FRAME_SECONDS)))
    peaks = []
    for i in range(1, len(flux) - 1):
        if flux[i] < FLUX_THRESHOLD * reference or flux[i] < flux[i - 1] or flux[i] <= flux[i + 1]:
            continue
        lo, hi = max(0, i - gap), min(len(flux), i + gap + 1)
        if flux[i] < flux[lo:hi].max():
            continue                            # a stronger rise sits within the minimum gap
        peaks.append(i)
    if not peaks:
        return []
    hit_energy = np.array([energy[i:i + 4].max() for i in peaks])
    typical = np.percentile(hit_energy, 90)
    hits = []
    for i, e in zip(peaks, hit_energy):
        if e < QUIET_HIT_SHARE * typical:
            continue
        time = (i * HOP + N_FFT / 2) / SAMPLE_RATE - ONSET_LAG_SECONDS
        hits.append([round(max(0.0, time), 3), round(float(min(1.0, np.sqrt(e / typical) * 0.9)), 2)])
    return hits


def detect(folder):
    """{"lanes": [{"id", "label", "hits": [[time, strength]...]}], "approximate": bool}, or None."""
    lanes = []
    present = [(lane, label, name, gap) for lane, label, name, gap in PARTS
               if os.path.isfile(os.path.join(folder, name))]
    if present:
        audio = {lane: bleed_check._mono_22k(os.path.join(folder, name)) for lane, _l, name, _g in present}
        energy = {lane: float(np.sum(np.square(x, dtype=np.float64))) for lane, x in audio.items()}
        kit = sum(energy.values()) or 1.0
        for lane, label, name, gap in present:
            x = audio[lane]
            rms_db = 20 * np.log10((energy[lane] / max(1, len(x))) ** 0.5 + 1e-12)
            if rms_db < SILENT_PART_DB or energy[lane] / kit < SILENT_PART_SHARE:
                continue                        # nothing in this part but leftovers: it would only invent hits
            mag = _spectrogram(x)
            hits = hits_in_band(mag, None, gap)
            if hits:
                lanes.append({"id": lane, "label": label, "hits": hits})
        return {"lanes": lanes, "approximate": False}
    whole = os.path.join(folder, "drums.wav")
    if not os.path.isfile(whole):
        return None
    mag = _spectrogram(bleed_check._mono_22k(whole))
    for lane, label, _name, gap in PARTS:
        if lane in BANDS:
            hits = hits_in_band(mag, BANDS[lane], gap)
            if hits:
                lanes.append({"id": lane, "label": label, "hits": hits})
    return {"lanes": lanes, "approximate": True}


def _signature(folder):
    names = ["drums.wav"] + [name for _l, _b, name, _g in PARTS]
    return {n: os.path.getmtime(os.path.join(folder, n)) for n in names if os.path.isfile(os.path.join(folder, n))}


def cached_hits(folder, cache_path):
    """detect(), remembered next to the song so it only has to run once."""
    signature = _signature(folder)
    if not signature:
        return None
    try:
        with open(cache_path, "r", encoding="utf-8") as handle:
            saved = json.load(handle)
        if saved.get("version") == VERSION and saved.get("signature") == signature:
            return saved
    except (OSError, ValueError):
        pass
    result = detect(folder)
    if result is None:
        return None
    result.update({"version": VERSION, "signature": signature})
    tmp = cache_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(result, handle)
    os.replace(tmp, cache_path)
    return result


if __name__ == "__main__":
    out = detect(sys.argv[1])
    for lane in out["lanes"]:
        print(lane["label"], len(lane["hits"]))
    print("approximate" if out["approximate"] else "from the split parts")
