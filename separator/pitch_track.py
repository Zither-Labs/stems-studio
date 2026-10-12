"""
Sung-pitch tracking for the vocal highway.

The pitch is found by SwiftF0, a small neural pitch detector (about 135 KB, runs on the CPU,
needs no PyTorch), and then cleaned up with the methods that pitch-tracking research and
tools such as pYIN, CREPE and RMVPE use for the same problems:

  * breaths, "s" and "t" sounds, and instrument bleed are not pitched, so frames are kept
    only when the detector is confident AND the vocal is loud enough compared with the
    singer's normal level;
  * octave errors (the tracker picks half or double the real pitch) are repaired by a
    Viterbi search that may move a frame up or down an octave, but only pays for a jump
    back if the new octave does not last (a real sung octave leap does last);
  * what is left is smoothed, tiny gaps are bridged and fragments that are too short to be
    singing are dropped.

The result is a list of MIDI note numbers (fractions allowed) at a fixed 16 ms step, with 0
meaning "nobody is singing".
"""

import json
import os
import sys

import numpy as np

ANALYSIS_VERSION = 4          # bump this when the method changes, so saved results are redone
STEP_SECONDS = 256 / 16000    # SwiftF0 reports one pitch every 256 samples at 16 kHz

# Singing range we accept (Hz). Lower than a bass voice or higher than a soprano is bleed.
FMIN_HZ = 65.0
FMAX_HZ = 1175.0

# Two-level confidence ("hysteresis", as used for edges in image processing): a stretch of
# frames counts as singing only if the detector is very sure about at least one frame in it
# (STRONG). The weaker neighbours (WEAK, SwiftF0's own "pitched" line) are then kept too,
# because the start and end of a real note are always less clear than its middle.
STRONG_CONFIDENCE = 0.8
WEAK_CONFIDENCE = 0.5
LOUDNESS_BELOW_PEAK_DB = 30   # ignore frames this much quieter than the singer's usual level
MIN_NOTE_SECONDS = 0.09       # fragments shorter than this are not singing
MAX_BRIDGE_SECONDS = 0.07     # bridge gaps at most this long when the pitch matches on both sides

OCTAVE_SHIFT_COST = 0.25      # per frame spent in a corrected octave (so about 12 frames = 0.2 s
                              # of "wrong" pitch is cheaper to flip than to leave as a spike)
JUMP_COST_CAP = 3.0           # cost of a jump of 12 semitones or more between neighbours
OUT_OF_RANGE_COST = 0.3       # per frame far (over 15 semitones) from the singer's median
PHRASE_GAP_SECONDS = 0.25     # a silence this long starts a new phrase (no jump cost across it)


def hz_to_midi(hz):
    return 69.0 + 12.0 * np.log2(np.maximum(hz, 1e-6) / 440.0)


def _runs(mask):
    """Yield (start, end_exclusive) for every run of True in a boolean array."""
    padded = np.concatenate(([False], mask, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    return list(zip(edges[0::2], edges[1::2]))


def repair_octaves(midi, voiced, singer_median):
    """Move frames up or down by whole octaves so the contour has as few spurious jumps as possible."""
    out = midi.copy()
    gap_frames = max(1, int(round(PHRASE_GAP_SECONDS / STEP_SECONDS)))
    shifts = np.array([-12.0, 0.0, 12.0])

    # Split into phrases: voiced stretches separated by a real silence.
    phrase_start = None
    last_voiced = None
    phrases = []
    for i in np.flatnonzero(voiced):
        if phrase_start is None:
            phrase_start = last_voiced = i
        elif i - last_voiced > gap_frames:
            phrases.append((phrase_start, last_voiced))
            phrase_start = i
        last_voiced = i
    if phrase_start is not None:
        phrases.append((phrase_start, last_voiced))

    for start, end in phrases:
        idx = np.flatnonzero(voiced[start:end + 1]) + start
        n = len(idx)
        if n < 3:
            continue
        base = midi[idx]
        candidates = base[:, None] + shifts[None, :]              # n x 3
        stay = np.abs(shifts) / 12.0 * OCTAVE_SHIFT_COST          # cost of leaving the detected octave
        off_range = np.maximum(0.0, np.abs(candidates - singer_median) - 15.0) * OUT_OF_RANGE_COST / 3.0
        emission = stay[None, :] + off_range

        cost = np.empty((n, 3))
        back = np.zeros((n, 3), dtype=np.int8)
        cost[0] = emission[0]
        for t in range(1, n):
            # Frames that are far apart in time are weakly related, so the jump cost fades out.
            gap = idx[t] - idx[t - 1]
            weight = 1.0 if gap <= 3 else max(0.0, 1.0 - (gap - 3) / max(1, gap_frames))
            jump = np.abs(candidates[t][None, :] - candidates[t - 1][:, None])      # from x to
            jump_cost = np.minimum(jump, 12.0) / 12.0 * JUMP_COST_CAP * weight
            total = cost[t - 1][:, None] + jump_cost
            back[t] = np.argmin(total, axis=0)
            cost[t] = total[back[t], np.arange(3)] + emission[t]

        state = int(np.argmin(cost[-1]))
        for t in range(n - 1, -1, -1):
            out[idx[t]] = candidates[t, state]
            state = int(back[t, state])
    return out


def median_filter(values, voiced, radius):
    """Median of the voiced neighbours within `radius` frames; keeps unvoiced frames at 0."""
    n = len(values)
    out = np.zeros(n, dtype=np.float64)
    for i in np.flatnonzero(voiced):
        lo, hi = max(0, i - radius), min(n, i + radius + 1)
        window = values[lo:hi][voiced[lo:hi]]
        out[i] = np.median(window)
    return out


SPIKE_JUMP_SEMITONES = 9      # a jump this big between neighbouring frames is not a normal melody step
SPIKE_MAX_SECONDS = 0.2       # ...and a stretch this short between such jumps is a stray reading


def drop_spikes(midi, voiced):
    """Remove short stretches that sit far away from the singing around them (stray readings)."""
    n = len(midi)
    max_frames = int(round(SPIKE_MAX_SECONDS / STEP_SECONDS))
    for start, end in _runs(voiced):
        # Cut the run wherever the pitch leaps, giving stretches of steady-ish pitch.
        cuts = [start]
        for i in range(start + 1, end):
            if abs(midi[i] - midi[i - 1]) >= SPIKE_JUMP_SEMITONES:
                cuts.append(i)
        cuts.append(end)
        if len(cuts) <= 2:
            continue
        pieces = list(zip(cuts[:-1], cuts[1:]))
        for k, (a, b) in enumerate(pieces):
            if b - a > max_frames:
                continue
            longest_neighbour = max(
                [pieces[j][1] - pieces[j][0] for j in (k - 1, k + 1) if 0 <= j < len(pieces)] or [0])
            if longest_neighbour > b - a:
                voiced[a:b] = False
                midi[a:b] = 0.0
    return midi, voiced


# Second chance for singing the detector is unsure about (rough, doubled or harmonised voices).
# If the vocal stem is clearly loud but no pitch was kept, a steady stretch of pitch readings is
# still accepted at a lower confidence. Steady means: no jump bigger than RESCUE_STEP_SEMITONES
# between neighbouring frames, which noise and breath do not manage but a held note does.
RESCUE_CONFIDENCE = 0.1
RESCUE_LOUD_BELOW_DB = 24      # "clearly loud" = within this many dB of the singer's usual level
RESCUE_STEP_SEMITONES = 1.5
RESCUE_MIN_SECONDS = 0.14


def rescue_steady_singing(hz, confidence, loudness_db, pitched, level, in_range):
    """Frames that are loud, were not accepted yet, and form a steady low-confidence pitch."""
    candidate = (~pitched) & in_range & (confidence >= RESCUE_CONFIDENCE) \
        & (loudness_db >= level - RESCUE_LOUD_BELOW_DB)
    semitones = hz_to_midi(hz)
    min_frames = int(round(RESCUE_MIN_SECONDS / STEP_SECONDS))
    rescued = np.zeros(len(hz), dtype=bool)
    for start, end in _runs(candidate):
        piece_start = start
        for i in range(start + 1, end + 1):
            if i == end or abs(semitones[i] - semitones[i - 1]) > RESCUE_STEP_SEMITONES:
                if i - piece_start >= min_frames:
                    rescued[piece_start:i] = True
                piece_start = i
    return rescued


def unpitched_loud_fraction(midi, loudness_db):
    """The check: of the frames where the vocal stem is clearly loud, how many have no pitch?"""
    singing = midi > 0
    if not singing.any():
        return 1.0 if len(midi) else 0.0
    level = np.percentile(loudness_db[singing], 90)
    loud = loudness_db >= level - RESCUE_LOUD_BELOW_DB
    return float((loud & ~singing).sum() / max(1, loud.sum()))


def clean_track(hz, confidence, loudness_db):
    """The whole clean-up, from raw detector output to the final MIDI track (0 = silence)."""
    n = len(hz)
    in_range = (hz >= FMIN_HZ) & (hz <= FMAX_HZ)
    candidate = (confidence >= WEAK_CONFIDENCE) & in_range
    pitched = np.zeros(n, dtype=bool)
    for start, end in _runs(candidate):
        if confidence[start:end].max() >= STRONG_CONFIDENCE:
            pitched[start:end] = True

    # How loud the singer normally is: a high percentile of the pitched frames.
    if not pitched.any():
        return np.zeros(n)
    level = np.percentile(loudness_db[pitched], 90)
    pitched = pitched | rescue_steady_singing(hz, confidence, loudness_db, pitched, level, in_range)
    loud_enough = loudness_db >= level - LOUDNESS_BELOW_PEAK_DB
    voiced = pitched & loud_enough
    if not voiced.any():
        return np.zeros(n)

    midi = np.where(voiced, hz_to_midi(hz), 0.0)
    singer_median = float(np.median(midi[voiced]))

    midi = repair_octaves(midi, voiced, singer_median)
    midi = median_filter(midi, voiced, radius=2)

    # Bridge tiny gaps (a consonant in the middle of a word), but only if both sides agree.
    max_bridge = int(round(MAX_BRIDGE_SECONDS / STEP_SECONDS))
    for start, end in _runs(~voiced):
        if start == 0 or end >= n or end - start > max_bridge:
            continue
        left, right = midi[start - 1], midi[end]
        if left and right and abs(left - right) < 1.5:
            midi[start:end] = np.linspace(left, right, end - start + 2)[1:-1]
            voiced[start:end] = True

    midi, voiced = drop_spikes(midi, voiced)

    # Fragments that are too short are not singing: breath, click or bleed.
    min_frames = int(round(MIN_NOTE_SECONDS / STEP_SECONDS))
    for start, end in _runs(voiced):
        if end - start < min_frames:
            voiced[start:end] = False
    midi[~voiced] = 0.0
    return midi


# The other stems of a song, used to spot instruments that leaked into the vocal stem.
INSTRUMENT_STEMS = ("guitar", "guitar_lead", "guitar_rhythm", "piano", "other")


def instrument_paths(vocal_path):
    """Paths of the instrument stems that sit next to the vocal stem (the ones that exist)."""
    folder = os.path.dirname(os.path.abspath(vocal_path))
    paths = [os.path.join(folder, name + ".wav") for name in INSTRUMENT_STEMS]
    return [p for p in paths if os.path.isfile(p)]


def analyze_file(path, instruments=None):
    """Read a vocal stem (any WAV/FLAC) and return {"dt", "t0", "midi"} for the highway.

    instruments: paths of the song's other stems. When given, notes that look like an instrument
    leaking into the vocal stem (ghost notes) are removed. See bleed_check.py.
    """
    import soundfile as sf
    from swift_f0 import SwiftF0

    audio, rate = sf.read(path, dtype="float32", always_2d=True)
    mono = audio.mean(axis=1)
    detector = SwiftF0(threads=4, spin=False)
    result = detector.detect(mono, rate, fmin=FMIN_HZ, fmax=FMAX_HZ)
    midi = clean_track(result.pitch_hz, result.confidence, result.loudness_db)
    t0 = float(result.timestamps[0]) if len(result.timestamps) else 0.0

    ghosts_removed = 0
    if instruments:
        try:
            import bleed_check
            midi, ghosts_removed = bleed_check.remove_ghost_notes(midi, STEP_SECONDS, path, instruments, t0)
        except Exception as exc:      # the check is a bonus: never lose the pitch because of it
            print(f"Ghost-note check skipped: {exc}", file=sys.stderr)
    return {
        "version": ANALYSIS_VERSION,
        "t0": t0,
        "dt": STEP_SECONDS,
        "ghost_notes_removed": ghosts_removed,
        "midi": [round(float(m), 2) for m in midi],
    }


def _signature(wav_path, instruments):
    return {"source_mtime": os.path.getmtime(wav_path),
            "instrument_mtimes": {os.path.basename(p): os.path.getmtime(p) for p in instruments}}


def cached_analysis(wav_path, cache_path):
    """analyze_file(), remembered next to the song so it only has to run once."""
    instruments = instrument_paths(wav_path)
    signature = _signature(wav_path, instruments)
    try:
        with open(cache_path, "r", encoding="utf-8") as handle:
            saved = json.load(handle)
        if saved.get("version") == ANALYSIS_VERSION and all(saved.get(k) == v for k, v in signature.items()):
            return saved
    except (OSError, ValueError):
        pass
    result = analyze_file(wav_path, instruments)
    result.update(signature)
    tmp = cache_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(result, handle)
    os.replace(tmp, cache_path)
    return result

if __name__ == "__main__":
    out = analyze_file(sys.argv[1], instrument_paths(sys.argv[1]))
    voiced = sum(1 for m in out["midi"] if m)
    print(f"{len(out['midi'])} frames, {voiced} voiced")
