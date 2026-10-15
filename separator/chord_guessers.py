"""Chord guessers from other projects, next to the app's own guess.

    app        Stems Studio's own guess: the beat, the bass line and the guitar (music_analysis).
    chordino   Chordino (Mauch & Dixon): NNLS chroma and an HMM over a chord dictionary.
    madmom     madmom (Korzeniowski & Widmer): a deep chroma CNN and a CRF.
    autochord  autochord (Bayron): NNLS chroma into a bi-LSTM-CRF.
    btc        BTC (Park et al.): a bi-directional transformer over a constant-Q spectrum.

The four outside guessers are optional. tools/install_chord_guessers.py puts them in .venv-chords
and .chord-tools, and chord_guess_run.py runs them there. Each one hears the song without the
vocal and the drums (bass, guitar, piano and other added together), and its answer is kept with
the song in chords-<engine>.json, so a song is only read once per guesser.
"""
import json
import os
import re
import subprocess
import sys
import tempfile
import threading

import numpy as np

import chord_guess_run

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV = os.path.join(ROOT, ".venv-chords")
TOOLS = os.path.join(ROOT, ".chord-tools")
STATUS = os.path.join(TOOLS, "installed.json")
RUNNER = os.path.join(ROOT, "separator", "chord_guess_run.py")
GUESS_VERSION = 1
NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}

GUESSERS = [
    {"id": "app", "label": "Stems Studio"},
    {"id": "chordino", "label": "Chordino"},
    {"id": "madmom", "label": "madmom"},
    {"id": "autochord", "label": "autochord"},
    {"id": "btc", "label": "BTC"},
]
LABELS = {item["id"]: item["label"] for item in GUESSERS}
HARMONY_STEMS = ("bass", "guitar", "guitar_lead", "guitar_rhythm", "piano", "other")
GUESS_LOCK = threading.Lock()

SHARP = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
PITCH = {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}
# Harte qualities (madmom, autochord, BTC) as the suffix the highway prints after the root.
HARTE = {
    "": "", "maj": "", "min": "m", "dim": "dim", "aug": "aug", "maj6": "6", "min6": "m6",
    "7": "7", "maj7": "maj7", "min7": "m7", "minmaj7": "mMaj7", "dim7": "dim7", "hdim7": "m7b5",
    "sus2": "sus2", "sus4": "sus4", "9": "9", "maj9": "maj9", "min9": "m9", "11": "11", "13": "13",
    "1": "5", "5": "5",
}
# Harte bass degrees after the slash ("C:maj/3" is C over E).
DEGREE = {"1": 0, "b2": 1, "2": 2, "b3": 3, "3": 4, "4": 5, "#4": 6, "b5": 6, "5": 7, "#5": 8, "b6": 8,
          "6": 9, "bb7": 9, "b7": 10, "7": 11, "9": 2, "b9": 1}
_NOTE = re.compile(r"^([A-Ga-g])([#b]*)")


def venv_python():
    return os.path.join(VENV, "Scripts", "python.exe") if os.name == "nt" else os.path.join(VENV, "bin", "python")


def _status():
    try:
        with open(STATUS, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def ready(engine):
    if engine == "app":
        return True
    if not _status().get(engine, {}).get("ok"):
        return False
    if engine in ("chordino", "autochord") and not chord_guess_run.chordino_ready(TOOLS):
        return False
    return engine == "chordino" or os.path.isfile(venv_python())


def listing():
    return [{**item, "ready": ready(item["id"])} for item in GUESSERS]


def _note(text):
    match = _NOTE.match(text or "")
    if not match:
        return None, ""
    pitch = PITCH[match.group(1).upper()]
    for sign in match.group(2):
        pitch += 1 if sign == "#" else -1
    return pitch % 12, text[match.end():]


def parse_label(label):
    """One guesser's label as {root, quality, bass}, or None for no chord.

    Chordino writes "Am7b5/G" and "Ebm". madmom, autochord and BTC write Harte labels: "A:hdim7",
    "E:min", "C:maj/3", or just "C".
    """
    text = (label or "").strip()
    if not text or text.upper() in ("N", "X"):
        return None
    main, _, slash = text.partition("/")
    root, rest = _note(main)
    if root is None:
        return None
    if rest.startswith(":"):
        harte = rest[1:].split("(")[0]
        quality = HARTE.get(harte, HARTE.get(harte.lower(), harte))
        bass = (root + DEGREE[slash]) % 12 if slash in DEGREE else None
    else:
        quality = rest
        bass = _note(slash)[0] if slash else None
    if bass == root:
        bass = None
    return {"root": root, "quality": quality, "bass": bass}


def tidy(segments, shortest=0.25):
    """Chords for the highway: no gaps for 'no chord', and a blip shorter than a beat is folded away."""
    chords = []
    for segment in segments or []:
        try:
            start, end = float(segment["start"]), float(segment["end"])
        except (KeyError, TypeError, ValueError):
            continue
        parsed = parse_label(segment.get("label"))
        if parsed is None or end <= start:
            continue
        last = chords[-1] if chords else None
        if last and (last["root"], last["quality"], last["bass"]) == (parsed["root"], parsed["quality"], parsed["bass"]) \
                and start - last["end"] < 0.3:
            last["end"] = end
            continue
        if end - start < shortest and last and start - last["end"] < 0.3:
            last["end"] = end
            continue
        chords.append({"start": start, "end": end, **parsed})
    out = []
    for chord in chords:
        name = SHARP[chord["root"]] + chord["quality"] + (f"/{SHARP[chord['bass']]}" if chord["bass"] is not None else "")
        out.append({
            "start": round(chord["start"], 2),
            "end": round(chord["end"], 2),
            "root": chord["root"],
            "quality": chord["quality"],
            "bass": chord["bass"],
            "name": name,
            "sure": True,
        })
    return out


def harmony_stems(folder):
    names = set()
    for stem in HARMONY_STEMS:
        if os.path.isfile(os.path.join(folder, f"{stem}.wav")):
            names.add(stem)
    if names & {"guitar_lead", "guitar_rhythm"}:
        names.discard("guitar")
    return sorted(names)


def _signature(folder, stems):
    out = []
    for stem in stems:
        info = os.stat(os.path.join(folder, f"{stem}.wav"))
        out.append([stem, int(info.st_size), int(info.st_mtime)])
    return out


def write_harmony_mix(folder, stems, path):
    """Bass, guitar, piano and other added together, as mono 16-bit 44.1 kHz (what the guessers expect)."""
    import soundfile as sf
    total = None
    rate = None
    for stem in stems:
        audio, stem_rate = sf.read(os.path.join(folder, f"{stem}.wav"), dtype="float32", always_2d=True)
        mono = audio.mean(axis=1)
        if rate is None:
            rate = stem_rate
        elif stem_rate != rate:
            continue
        if total is None:
            total = mono
        else:
            length = max(len(total), len(mono))
            total = np.pad(total, (0, length - len(total))) + np.pad(mono, (0, length - len(mono)))
    if total is None:
        raise RuntimeError("this song has no bass, guitar, piano or other stem")
    if rate != chord_guess_run.SAMPLE_RATE:
        seconds = len(total) / float(rate)
        count = int(round(seconds * chord_guess_run.SAMPLE_RATE))
        total = np.interp(np.linspace(0, len(total) - 1, count), np.arange(len(total)), total).astype(np.float32)
    peak = float(np.max(np.abs(total))) if len(total) else 0.0
    if peak > 0:
        total = total * (0.9 / peak)
    sf.write(path, total, chord_guess_run.SAMPLE_RATE, subtype="PCM_16")


def cache_path(folder, engine):
    return os.path.join(folder, f"chords-{engine}.json")


def load_if_fresh(folder, engine):
    stems = harmony_stems(folder)
    if not stems:
        return None
    try:
        with open(cache_path(folder, engine), "r", encoding="utf-8") as handle:
            saved = json.load(handle)
    except (OSError, ValueError):
        return None
    if saved.get("version") != GUESS_VERSION or saved.get("stems") != _signature(folder, stems):
        return None
    return saved.get("segments") or []


def _run(engine, wav, out, progress):
    if engine == "chordino":
        # Chordino is a program of its own, so it does not need the chord-guesser environment.
        command = [sys.executable, RUNNER, engine, TOOLS, wav, out]
        if os.name == "nt" and os.path.basename(sys.executable).lower() == "pythonw.exe":
            command[0] = os.path.join(os.path.dirname(sys.executable), "python.exe")
    else:
        command = [venv_python(), RUNNER, engine, TOOLS, wav, out]
    env = {**os.environ, "PYTHONUNBUFFERED": "1", "TF_CPP_MIN_LOG_LEVEL": "2"}
    process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                               encoding="utf-8", errors="replace", env=env, **NO_WINDOW)
    errors = []
    reader = threading.Thread(target=lambda: errors.extend(process.stderr), daemon=True)
    reader.start()
    for line in process.stdout:
        if line.startswith("PROGRESS "):
            parts = line.split(" ", 2)
            try:
                progress(int(parts[1]), parts[2].strip() if len(parts) > 2 else "")
            except ValueError:
                pass
    process.wait()
    reader.join(timeout=2)
    if process.returncode != 0:
        tail = "".join(errors)[-600:].strip()
        raise RuntimeError(f"{LABELS.get(engine, engine)} stopped: {tail.splitlines()[-1] if tail else 'no message'}")


def guess(folder, engine, progress=None):
    """The chords this guesser hears in the song, read once and then kept with the song."""
    if engine not in LABELS or engine == "app":
        raise ValueError(f"unknown chord guesser: {engine}")
    progress = progress or (lambda percent, message: None)
    saved = load_if_fresh(folder, engine)
    if saved is not None:
        return saved
    with GUESS_LOCK:
        saved = load_if_fresh(folder, engine)
        if saved is not None:
            return saved
        stems = harmony_stems(folder)
        if not stems:
            raise RuntimeError("this song has no bass, guitar, piano or other stem")
        signature = _signature(folder, stems)
        progress(2, "Mixing the bass, guitar, piano and other stems...")
        with tempfile.TemporaryDirectory() as work:
            wav = os.path.join(work, "harmony.wav")
            out = os.path.join(work, "chords.json")
            write_harmony_mix(folder, stems, wav)
            _run(engine, wav, out, lambda percent, message: progress(5 + percent * 0.94, message))
            with open(out, "r", encoding="utf-8") as handle:
                segments = json.load(handle).get("segments") or []
        payload = {"version": GUESS_VERSION, "engine": engine, "stems": signature, "segments": segments}
        tmp = cache_path(folder, engine) + ".tmp"
        with open(tmp, "w", encoding="utf-8") as handle:
            json.dump(payload, handle)
        os.replace(tmp, cache_path(folder, engine))
        return segments
