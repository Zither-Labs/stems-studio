"""
Ghost-note check: is a "sung" note really the vocal stem, or a guitar (or piano, or anything
else) that leaked into it?

The song's other stems (guitar, piano, other...) are the reference. If an instrument leaked
into the vocal stem, the leak is a quieter COPY of what that instrument stem plays. A real voice
is not: it has its own overtone shape (the vowel) and its own loudness movement (the singer's
breath and phrasing, not the instrument's pluck and decay).

For every pitched frame we measure the first five overtones of the note in the vocal stem and in
the other stems. A note is dropped as a ghost when either:

  A. (frame test) in most of its frames the other stems are louder than the vocal stem at those
     overtones AND the loudness difference is nearly the same at every overtone (a clean copy);
  B. (note test) the note lasts at least 0.25 s, the other stems are louder, AND the vocal stem's
     loudness at the note's overtones rises and falls together with the other stems' loudness
     (correlation of the two loudness curves over the note). A leak follows the instrument
     exactly, even when its tone has been coloured; a singer does not.

Test B is what catches real, imperfect leaks, since the separator colours the leaked sound.
Notes are only ever removed as a whole, and only when the evidence is strong, so the check
never thins out real singing (see tools/check_bleed.py).
"""
import numpy as np

SAMPLE_RATE = 22050
N_FFT = 2048
HOP = 353                      # about 16 ms, like the pitch frames
OVERTONES = 5

LOUDER_DB = 3.0                # other stems at least this much louder than the vocal stem
COPY_STD_DB = 3.5              # frame test: difference changes less than this between overtones
NOTE_GHOST_FRACTION = 0.6      # frame test: share of a note's frames that must look like a copy
NOTE_MIN_SECONDS = 0.25        # note test: shortest note it applies to
NOTE_CORRELATION = 0.85        # note test: loudness curves must correlate at least this much
CORRELATION_OVERTONES = 3


def _mono_22k(path):
    import soundfile as sf
    audio, rate = sf.read(path, dtype="float32", always_2d=True)
    mono = audio.mean(axis=1)
    rate = int(rate)
    if rate == 2 * SAMPLE_RATE:
        usable = len(mono) // 2 * 2
        return mono[:usable].reshape(-1, 2).mean(axis=1).astype(np.float32)     # simple 2:1 downsample
    if rate != SAMPLE_RATE:
        positions = np.arange(0, len(mono), rate / SAMPLE_RATE)
        mono = np.interp(positions, np.arange(len(mono)), mono).astype(np.float32)
    return mono


def _magnitude(signal):
    """Magnitude spectrogram, shape (bins, frames); frame j starts at j * HOP samples."""
    window = np.hanning(N_FFT).astype(np.float32)
    count = max(0, (len(signal) - N_FFT) // HOP + 1)
    out = np.empty((N_FFT // 2 + 1, count), dtype=np.float32)
    step = 512
    for first in range(0, count, step):
        last = min(count, first + step)
        idx = np.arange(first, last)[:, None] * HOP + np.arange(N_FFT)[None, :]
        out[:, first:last] = np.abs(np.fft.rfft(signal[idx] * window, axis=1)).T
    return out


def overtone_levels(vocal_mag, other_mag, midi, dt, t0=0.0):
    """Levels in dB of the first overtones of every pitched frame.

    Returns (vocal_db, other_db), each shaped (frames, OVERTONES) with NaN where there is no
    pitch or the overtone is beyond the spectrum.
    """
    n = len(midi)
    vocal_db = np.full((n, OVERTONES), np.nan)
    other_db = np.full((n, OVERTONES), np.nan)
    bin_hz = SAMPLE_RATE / N_FFT
    frames = vocal_mag.shape[1]
    for i in np.flatnonzero(midi > 0):
        j = int(round(((i * dt + t0) * SAMPLE_RATE - N_FFT / 2) / HOP))   # frame centred on this time
        if j < 0:
            continue
        if j >= frames:
            break
        f0 = 440.0 * 2.0 ** ((midi[i] - 69.0) / 12.0)
        for k in range(OVERTONES):
            b = int(round((k + 1) * f0 / bin_hz))
            if b + 2 >= vocal_mag.shape[0]:
                break
            vocal_db[i, k] = 20.0 * np.log10(vocal_mag[b - 1:b + 2, j].max() + 1e-6)
            other_db[i, k] = 20.0 * np.log10(other_mag[b - 1:b + 2, j].max() + 1e-6)
    return vocal_db, other_db


def frame_features(vocal_db, other_db):
    """Per frame: how much louder the other stems are (median over overtones) and how much that varies."""
    diff = other_db - vocal_db
    enough = np.sum(~np.isnan(diff), axis=1) >= 3
    louder = np.full(len(diff), np.nan)
    spread = np.full(len(diff), np.nan)
    with np.errstate(all="ignore"):
        louder[enough] = np.nanmedian(diff[enough], axis=1)
        spread[enough] = np.nanstd(diff[enough], axis=1)
    return louder, spread


def note_is_ghost(vocal_db, other_db, louder, spread, start, end, dt):
    """The two tests above, for the note occupying frames [start, end)."""
    checked = ~np.isnan(louder[start:end])
    if checked.sum() < 5:
        return False
    with np.errstate(invalid="ignore"):
        frame_copy = (louder[start:end] > LOUDER_DB) & (spread[start:end] < COPY_STD_DB)
    if frame_copy[checked].mean() >= NOTE_GHOST_FRACTION:
        return True

    if (end - start) * dt < NOTE_MIN_SECONDS:
        return False
    if np.nanmedian(louder[start:end]) <= LOUDER_DB:
        return False
    correlations = []
    for k in range(CORRELATION_OVERTONES):
        v = vocal_db[start:end, k]
        o = other_db[start:end, k]
        ok = ~np.isnan(v) & ~np.isnan(o)
        if ok.sum() < 10 or v[ok].std() < 0.5 or o[ok].std() < 0.5:
            continue
        correlations.append(np.corrcoef(v[ok], o[ok])[0, 1])
    return len(correlations) >= 2 and float(np.median(correlations)) >= NOTE_CORRELATION


def other_magnitude(other_paths):
    """Summed spectrogram of the instrument stems (guitar, piano, other...)."""
    total = None
    for path in other_paths:
        mag = _magnitude(_mono_22k(path))
        if total is None:
            total = mag
        else:
            width = min(total.shape[1], mag.shape[1])
            total = total[:, :width] + mag[:, :width]
    return total


def remove_ghost_notes(midi, dt, vocal_path, other_paths, t0=0.0):
    """Zero out the notes of `midi` that look like leaked instruments. Returns (midi, notes_removed)."""
    others = [p for p in other_paths if p]
    if not others or not (midi > 0).any():
        return midi, 0
    other_mag = other_magnitude(others)
    vocal_mag = _magnitude(_mono_22k(vocal_path))
    width = min(vocal_mag.shape[1], other_mag.shape[1])
    vocal_mag, other_mag = vocal_mag[:, :width], other_mag[:, :width]

    vocal_db, other_db = overtone_levels(vocal_mag, other_mag, midi, dt, t0)
    louder, spread = frame_features(vocal_db, other_db)
    out = midi.copy()
    removed = 0
    padded = np.concatenate(([False], midi > 0, [False]))
    edges = np.flatnonzero(padded[1:] != padded[:-1])
    for start, end in zip(edges[0::2], edges[1::2]):
        if note_is_ghost(vocal_db, other_db, louder, spread, start, end, dt):
            out[start:end] = 0.0
            removed += 1
    return out, removed
