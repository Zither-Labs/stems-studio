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

ANALYSIS_VERSION = 7          # bump this when the method changes, so saved results are redone
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


# Rough voices: growls, screams, harsh vocals. They are loud but hardly pitched, so the detector
# above (made for sung notes) leaves them out and the highway stays empty. For those loud
# stretches a second, much more forgiving estimate is made: "subharmonic summation" looks for the
# base pitch whose overtones line up best with the strongest parts of the sound, which works
# for a rough, noisy tone where a clean pitch detector gives up. It is a GUESS at the pitch of
# a sound that has hardly any, so the highway shows it separately (dashed) and the coach does
# not score it.
ROUGH_FMIN_HZ = 55.0
ROUGH_FMAX_HZ = 420.0
ROUGH_HARMONICS = 8
ROUGH_LOUD_BELOW_DB = 24       # same meaning as RESCUE_LOUD_BELOW_DB
ROUGH_SMOOTH_RADIUS = 4        # frames: the median over about 140 ms steadies the guess
ROUGH_MIN_SECONDS = 0.12
ROUGH_AUTO_FRACTION = 0.5      # if more than this share of the loud frames has no clean pitch, show it by default


def rough_voice(mono, rate, t0, midi):
    """(rough MIDI per step, share of loud frames without a clean pitch). 0 = nothing rough here."""
    n = len(midi)
    rough = np.zeros(n)
    if n == 0 or len(mono) == 0:
        return rough, 0.0
    hop_half = max(1, int(round(STEP_SECONDS * rate)))
    n_fft = 1 << int(np.ceil(np.log2(0.09 * rate)))
    centres = np.round((t0 + np.arange(n) * STEP_SECONDS) * rate).astype(np.int64)

    # Loudness of every step (RMS over about 32 ms around it).
    squares = np.concatenate(([0.0], np.cumsum(mono.astype(np.float64) ** 2)))
    lo = np.clip(centres - hop_half, 0, len(mono))
    hi = np.clip(centres + hop_half, 0, len(mono))
    rms = np.sqrt((squares[hi] - squares[lo]) / np.maximum(1, hi - lo))
    db = 20 * np.log10(rms + 1e-9)
    active = db > -60
    if not active.any():
        return rough, 0.0
    level = np.percentile(db[active], 90)
    loud = db >= level - ROUGH_LOUD_BELOW_DB
    candidate = loud & (midi <= 0)
    fraction = float(candidate.sum() / max(1, loud.sum()))
    if not candidate.any():
        return rough, fraction

    f0s = ROUGH_FMIN_HZ * 2 ** (np.arange(int(12 * np.log2(ROUGH_FMAX_HZ / ROUGH_FMIN_HZ) * 4) + 1) / 48.0)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / rate)
    weights = 0.84 ** np.arange(ROUGH_HARMONICS)
    smooth_bins = max(3, int(200.0 / freqs[1]))
    kernel = np.ones(smooth_bins) / smooth_bins
    window = np.hanning(n_fft).astype(np.float32)
    padded = np.concatenate((np.zeros(n_fft // 2, dtype=np.float32), mono.astype(np.float32), np.zeros(n_fft, dtype=np.float32)))
    guess = np.zeros(n)
    for i in np.flatnonzero(candidate):
        start = int(centres[i])                        # padded index of (centre - n_fft/2)
        spectrum = np.log1p(np.abs(np.fft.rfft(padded[start:start + n_fft] * window)) * 30.0)
        spectrum = np.maximum(0.0, spectrum - np.convolve(spectrum, kernel, mode="same"))   # keep the peaks
        score = np.zeros(len(f0s))
        for h in range(ROUGH_HARMONICS):
            score += weights[h] * np.interp((h + 1) * f0s, freqs, spectrum)
        guess[i] = 69.0 + 12.0 * np.log2(f0s[int(score.argmax())] / 440.0)

    # Steady the guess inside every stretch (median of the neighbours that have a guess) ...
    steady = np.zeros(n)
    for start, end in _runs(candidate):
        piece = guess[start:end]
        for k in range(len(piece)):
            a, b = max(0, k - ROUGH_SMOOTH_RADIUS), min(len(piece), k + ROUGH_SMOOTH_RADIUS + 1)
            steady[start + k] = np.median(piece[a:b])
    # ... and drop stretches too short to be a voice.
    min_frames = int(round(ROUGH_MIN_SECONDS / STEP_SECONDS))
    for start, end in _runs(candidate):
        if end - start >= min_frames:
            rough[start:end] = steady[start:end]
    return rough, fraction


# A 5-string bass goes down to a low B (31 Hz). With such a low note the detector usually reports
# its second harmonic (62 Hz), one octave too high. So a note found at 56-70 Hz is checked: if the
# audio also has real energy half-way down (at half that frequency), the note is moved down an octave.
# A note that really is at 62 Hz has nothing at 31 Hz, so it stays.
SUB_CHECK_MIN_HZ = 56.0
SUB_CHECK_MAX_HZ = 70.0
SUB_MAGNITUDE_RATIO = 0.35     # energy at half the frequency, compared with the note itself


def lower_octave_when_sub_present(midi, mono, rate, t0):
    """Moves notes found at 56-70 Hz down an octave when there is a real note below them. Returns the count moved."""
    moved = 0
    n_fft = 1 << int(np.ceil(np.log2(0.2 * rate)))
    window = np.hanning(n_fft).astype(np.float32)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / rate)
    n = len(midi)
    # Pieces of steady pitch.
    for start, end in _runs(midi > 0):
        piece_start = start
        for i in range(start + 1, end + 1):
            if i == end or abs(midi[i] - midi[i - 1]) > 1.5:
                if i - piece_start >= 3:
                    hz = 440.0 * 2 ** ((float(np.median(midi[piece_start:i])) - 69.0) / 12.0)
                    if SUB_CHECK_MIN_HZ <= hz <= SUB_CHECK_MAX_HZ:
                        a = int((t0 + piece_start * STEP_SECONDS) * rate)
                        b = int((t0 + i * STEP_SECONDS) * rate)
                        total = np.zeros(len(freqs))
                        count = 0
                        for first in range(a, max(a + 1, b - n_fft // 2), n_fft // 2):
                            chunk = mono[first:first + n_fft]
                            if len(chunk) < n_fft:
                                break
                            total += np.abs(np.fft.rfft(chunk * window))
                            count += 1
                        if count:
                            def peak(f):
                                keep = (freqs >= f * 0.96) & (freqs <= f * 1.04)
                                return float(total[keep].max()) if keep.any() else 0.0
                            if peak(hz) > 0 and peak(hz / 2.0) >= SUB_MAGNITUDE_RATIO * peak(hz):
                                midi[piece_start:i] -= 12.0
                                moved += 1
                piece_start = i
    return moved


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


def clean_track(hz, confidence, loudness_db, fmin=None, fmax=None):
    """The whole clean-up, from raw detector output to the final MIDI track (0 = silence)."""
    n = len(hz)
    in_range = (hz >= (FMIN_HZ if fmin is None else fmin)) & (hz <= (FMAX_HZ if fmax is None else fmax))
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


# Search range per kind of stem. "octave_up" is for notes below SwiftF0's own floor of 46.9 Hz
# (a bass guitar's low E is 41 Hz): the audio is declared to be at half its real sample rate,
# so every pitch is heard one octave higher, and the result is divided by two again.
PROFILES = {
    "vocals": {"fmin": FMIN_HZ, "fmax": FMAX_HZ, "rough": True},
    "bass": {"fmin": 28.0, "fmax": 260.0, "octave_up": True, "sub_check": True,   # low B (31 Hz) up to about C4
             "high": {"fmin": 240.0, "fmax": 900.0}},                    # then a second pass for high notes and solos
    "melody": {"fmin": 75.0, "fmax": 1400.0},     # lead guitar, guitar, anything single-note
}


def profile_for(stem_name):
    if stem_name == "vocals":
        return PROFILES["vocals"]
    return PROFILES.get(stem_name, PROFILES["melody"])


def _track(detector, mono, rate, profile):
    """One pitch pass over the audio in the profile's range: (cleaned MIDI per step, time of the first step)."""
    fmin, fmax = profile["fmin"], profile["fmax"]
    if profile.get("octave_up"):
        # Declared at twice the rate the audio sounds an octave higher and half as long, so the
        # detector's 16 ms steps are 32 ms of real time: each result is repeated twice.
        result = detector.detect(mono, rate * 2.0, fmin=fmin * 2, fmax=fmax * 2)
        hz = np.repeat(result.pitch_hz / 2.0, 2)
        confidence = np.repeat(result.confidence, 2)
        loudness = np.repeat(result.loudness_db, 2)
        t0 = float(result.timestamps[0]) * 2.0 if len(result.timestamps) else 0.0
    else:
        result = detector.detect(mono, rate, fmin=fmin, fmax=fmax)
        hz, confidence, loudness = result.pitch_hz, result.confidence, result.loudness_db
        t0 = float(result.timestamps[0]) if len(result.timestamps) else 0.0
    return clean_track(hz, confidence, loudness, fmin, fmax), t0


def analyze_file(path, instruments=None, profile=None):
    """Read a stem (any WAV/FLAC) and return {"dt", "t0", "midi"} for the highway.

    instruments: paths of the song's other stems. When given, notes that look like an instrument
    leaking into the vocal stem (ghost notes) are removed. See bleed_check.py.
    profile: search range, see PROFILES (default: the singing range).
    """
    import soundfile as sf
    from swift_f0 import SwiftF0

    profile = profile or PROFILES["vocals"]
    audio, rate = sf.read(path, dtype="float32", always_2d=True)
    mono = audio.mean(axis=1)
    detector = SwiftF0(threads=4, spin=False)
    midi, t0 = _track(detector, mono, rate, profile)
    if profile.get("high"):
        # A second, ordinary pass for notes above the main range. The detector tends to choose
        # the wrong octave when one search range is very wide, so the range is covered in two
        # passes. The high pass only fills moments the main pass left empty, and only with
        # notes at least as high as the main range's top, so it cannot turn a low note's
        # overtone into a note.
        high = profile["high"]
        high_midi, high_t0 = _track(detector, mono, rate, high)
        offset = int(round((high_t0 - t0) / STEP_SECONDS))
        floor = 12 * np.log2(profile["fmax"] / 440.0) + 69 - 0.5
        for i in range(len(midi)):
            j = i - offset
            if midi[i] <= 0 and 0 <= j < len(high_midi) and high_midi[j] >= floor:
                midi[i] = high_midi[j]

    if profile.get("sub_check"):
        lower_octave_when_sub_present(midi, mono, rate, t0)

    ghosts_removed = 0
    if instruments:
        try:
            import bleed_check
            midi, ghosts_removed = bleed_check.remove_ghost_notes(midi, STEP_SECONDS, path, instruments, t0)
        except Exception as exc:      # the check is a bonus: never lose the pitch because of it
            print(f"Ghost-note check skipped: {exc}", file=sys.stderr)
    result = {
        "version": ANALYSIS_VERSION,
        "t0": t0,
        "dt": STEP_SECONDS,
        "ghost_notes_removed": ghosts_removed,
        "midi": [round(float(m), 2) for m in midi],
    }
    if profile.get("rough"):
        try:
            rough, fraction = rough_voice(mono, rate, t0, np.asarray(midi, dtype=float))
            if (rough > 0).any():
                result["rough_midi"] = [round(float(m), 1) for m in rough]
            result["unpitched_loud"] = round(fraction, 3)
            result["rough_auto"] = bool(fraction > ROUGH_AUTO_FRACTION)
        except Exception as exc:      # a bonus: never lose the clean pitch because of it
            print(f"Rough-voice estimate skipped: {exc}", file=sys.stderr)
    return result

def _signature(wav_path, instruments):
    return {"source_mtime": os.path.getmtime(wav_path),
            "instrument_mtimes": {os.path.basename(p): os.path.getmtime(p) for p in instruments}}


def cached_analysis(wav_path, cache_path):
    """analyze_file(), remembered next to the song so it only has to run once."""
    stem_name = os.path.splitext(os.path.basename(wav_path))[0]
    # Only the vocal stem is checked for instruments leaking into it.
    instruments = instrument_paths(wav_path) if stem_name == "vocals" else []
    signature = _signature(wav_path, instruments)
    try:
        with open(cache_path, "r", encoding="utf-8") as handle:
            saved = json.load(handle)
        if saved.get("version") == ANALYSIS_VERSION and all(saved.get(k) == v for k, v in signature.items()):
            return saved
    except (OSError, ValueError):
        pass
    result = analyze_file(wav_path, instruments, profile_for(stem_name))
    result.update(signature)
    tmp = cache_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(result, handle)
    os.replace(tmp, cache_path)
    return result

if __name__ == "__main__":
    name = os.path.splitext(os.path.basename(sys.argv[1]))[0]
    out = analyze_file(sys.argv[1], instrument_paths(sys.argv[1]) if name == "vocals" else None, profile_for(name))
    voiced = sum(1 for m in out["midi"] if m)
    print(f"{len(out['midi'])} frames, {voiced} voiced")
