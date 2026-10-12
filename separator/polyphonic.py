"""Notes of a chord or piano stem: every note that sounds, not only the loudest one.

This runs Basic Pitch (Spotify, Apache-2.0) as a plain ONNX model with onnxruntime, so it needs
no TensorFlow. The model and its licence are in separator/vendor/. The window handling and the
note-making step are a numpy port of the ones in the basic-pitch package (inference.py and
note_creation.py), including its "melodia trick" for notes whose start is not clear.

Result: {"version", "notes": [[start_seconds, end_seconds, midi, strength 0..1], ...]}
It is a good guess, not a score: distorted guitar and busy mixes give stray and missing notes.
"""
import json
import os
import sys

import numpy as np

import bleed_check

VERSION = 1
MODEL_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vendor", "basic_pitch_nmp.onnx")

SAMPLE_RATE = 22050
HOP = 256                              # samples per model frame (86 frames a second)
WINDOW = SAMPLE_RATE * 2 - HOP         # the model reads exactly this many samples at a time
OVERLAP_FRAMES = 30
OVERLAP = OVERLAP_FRAMES * HOP
WINDOW_HOP = WINDOW - OVERLAP
MIDI_OFFSET = 21                       # the lowest of the 88 outputs is piano key A0
KEYS = 88
FRAME_SECONDS = HOP / SAMPLE_RATE

ONSET_THRESHOLD = 0.5
FRAME_THRESHOLD = 0.3
MIN_NOTE_SECONDS = 0.1
ENERGY_TOLERANCE = 11                  # frames below the threshold before a note is over


def available():
    try:
        import onnxruntime  # noqa: F401
        return os.path.isfile(MODEL_PATH)
    except ImportError:
        return False


def posteriorgrams(mono):
    """Run the model over a mono 22.05 kHz signal -> (note, onset), each (frames, 88)."""
    import onnxruntime as ort
    session = ort.InferenceSession(MODEL_PATH, providers=["CPUExecutionProvider"])

    padded = np.concatenate([np.zeros(OVERLAP // 2, dtype=np.float32), mono.astype(np.float32)])
    starts = list(range(0, len(padded), WINDOW_HOP))
    total = int(len(mono) / HOP) + 1
    note = np.zeros((total, KEYS), dtype=np.float32)
    onset = np.zeros((total, KEYS), dtype=np.float32)
    keep_from, keep_to = OVERLAP_FRAMES // 2, 172 - OVERLAP_FRAMES // 2

    for first in range(0, len(starts), 16):
        batch_starts = starts[first:first + 16]
        batch = np.zeros((len(batch_starts), WINDOW, 1), dtype=np.float32)
        for row, start in enumerate(batch_starts):
            piece = padded[start:start + WINDOW]
            batch[row, :len(piece), 0] = piece
        # The three outputs are contour (:0), note (:1) and onset (:2).
        _, note_out, onset_out = session.run(
            ["StatefulPartitionedCall:0", "StatefulPartitionedCall:1", "StatefulPartitionedCall:2"],
            {session.get_inputs()[0].name: batch})
        for row, start in enumerate(batch_starts):
            for j in range(keep_from, keep_to):
                # Frame j of this window, as seconds from the start of the real audio.
                index = int(round((start + j * HOP - OVERLAP // 2) / HOP))
                if 0 <= index < total:
                    note[index] = note_out[row, j]
                    onset[index] = onset_out[row, j]
    return note, onset


def _infer_onsets(onsets, frames, n_diff=2):
    """Add onsets where a key's strength suddenly rises, even if the model did not mark one."""
    diffs = []
    for n in range(1, n_diff + 1):
        padded = np.concatenate([np.zeros((n, frames.shape[1])), frames])
        diffs.append(padded[n:, :] - padded[:-n, :])
    change = np.min(diffs, axis=0)
    change[change < 0] = 0
    change[:n_diff, :] = 0
    top = change.max()
    if top > 0:
        change = onsets.max() * change / top
    return np.maximum(onsets, change)


def _clear_neighbours(energy, start, end, key):
    energy[start:end, key] = 0
    if key < KEYS - 1:
        energy[start:end, key + 1] = 0
    if key > 0:
        energy[start:end, key - 1] = 0


def notes_from_posteriorgrams(frames, onsets, min_frames):
    """Basic Pitch's polyphonic note-making. Returns (start_frame, end_frame, midi, strength)."""
    n_frames = frames.shape[0]
    onsets = _infer_onsets(onsets, frames)

    peaks = np.zeros(onsets.shape, dtype=bool)
    peaks[1:-1] = (onsets[1:-1] > onsets[:-2]) & (onsets[1:-1] > onsets[2:])
    peak_values = np.where(peaks, onsets, 0.0)
    times, keys = np.where(peak_values >= ONSET_THRESHOLD)
    times, keys = times[::-1], keys[::-1]            # latest first, like the original

    remaining = frames.copy()
    events = []
    for start, key in zip(times, keys):
        if start >= n_frames - 1:
            continue
        i, quiet = start + 1, 0
        while i < n_frames - 1 and quiet < ENERGY_TOLERANCE:
            quiet = quiet + 1 if remaining[i, key] < FRAME_THRESHOLD else 0
            i += 1
        i -= quiet
        if i - start <= min_frames:
            continue
        _clear_neighbours(remaining, start, i, key)
        events.append((int(start), int(i), int(key) + MIDI_OFFSET, float(frames[start:i, key].mean())))

    # "Melodia trick": strong stretches that never had a clear onset still become notes.
    rows, cols = np.where(remaining > FRAME_THRESHOLD)
    order = np.argsort(-remaining[rows, cols], kind="stable")
    for at in order:
        mid, key = int(rows[at]), int(cols[at])
        if remaining[mid, key] <= FRAME_THRESHOLD:      # used up by an earlier note
            continue
        remaining[mid, key] = 0
        i, quiet = mid + 1, 0
        while i < n_frames - 1 and quiet < ENERGY_TOLERANCE:
            quiet = quiet + 1 if remaining[i, key] < FRAME_THRESHOLD else 0
            _clear_neighbours(remaining, i, i + 1, key)
            i += 1
        end = i - 1 - quiet
        i, quiet = mid - 1, 0
        while i > 0 and quiet < ENERGY_TOLERANCE:
            quiet = quiet + 1 if remaining[i, key] < FRAME_THRESHOLD else 0
            _clear_neighbours(remaining, i, i + 1, key)
            i -= 1
        begin = i + 1 + quiet
        if end - begin <= min_frames:
            continue
        events.append((begin, end, key + MIDI_OFFSET, float(frames[begin:end, key].mean())))
    return events


OVERTONE_INTERVALS = (12, 19, 24)      # an octave, octave + fifth, two octaves above a note
OVERTONE_WEAKER_THAN = 0.7             # only notes this much weaker than the one below are dropped
OVERTONE_OVERLAP = 0.6                 # ...and only if they mostly sound at the same time


def drop_overtones(events):
    """A strong note makes its overtones ring; the model often reports them as extra notes."""
    by_start = sorted(events)
    keep = []
    for start, end, midi, strength in by_start:
        is_overtone = False
        for other_start, other_end, other_midi, other_strength in by_start:
            if other_start >= end:
                break
            if midi - other_midi not in OVERTONE_INTERVALS:
                continue
            overlap = min(end, other_end) - max(start, other_start)
            if overlap >= OVERTONE_OVERLAP * (end - start) and strength < OVERTONE_WEAKER_THAN * other_strength:
                is_overtone = True
                break
        if not is_overtone:
            keep.append((start, end, midi, strength))
    return keep


def transcribe_file(path):
    """Notes of one stem. The result is sorted by start time."""
    mono = bleed_check._mono_22k(path)
    note, onset = posteriorgrams(mono)
    min_frames = int(round(MIN_NOTE_SECONDS / FRAME_SECONDS))
    events = drop_overtones(notes_from_posteriorgrams(note, onset, min_frames))
    events.sort()
    return {
        "version": VERSION,
        "notes": [[round(s * FRAME_SECONDS, 3), round(e * FRAME_SECONDS, 3), m, round(min(1.0, a), 2)]
                  for s, e, m, a in events],
    }


def cached_notes(wav_path, cache_path):
    """transcribe_file(), remembered next to the song so it only has to run once."""
    signature = {"source_mtime": os.path.getmtime(wav_path)}
    try:
        with open(cache_path, "r", encoding="utf-8") as handle:
            saved = json.load(handle)
        if saved.get("version") == VERSION and saved.get("source_mtime") == signature["source_mtime"]:
            return saved
    except (OSError, ValueError):
        pass
    result = transcribe_file(wav_path)
    result.update(signature)
    tmp = cache_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(result, handle)
    os.replace(tmp, cache_path)
    return result


if __name__ == "__main__":
    out = transcribe_file(sys.argv[1])
    print(f"{len(out['notes'])} notes")
