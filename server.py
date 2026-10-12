"""
Stems Studio - local engine.
Serves the UI to the app window and provides the separation / library API.
Normally started by app.py; `python server.py` runs it on its own for development.
Supports YouTube URLs and local FLAC / MP3 / WAV files, with 4-stem and 6-stem
(htdemucs_6s) models and Nepali Folk presets.
"""

import contextlib
import email.message
import email.parser
import hashlib
import http.server
import json
import os
import re
import shutil
import socket
import socketserver
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
import uuid

import updater

# Auto-configure bundled ffmpeg
try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception:
    pass

APP_NAME = "stems-studio"
APP_VERSION = 7
PORT = 8099
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def default_data_dir():
    """Where the song library lives: outside the code folder, so git never touches it."""
    override = os.environ.get("STEMS_STUDIO_DATA")
    if override:
        return override
    if os.name == "nt":
        root = os.environ.get("LOCALAPPDATA") or os.path.expanduser("~")
        return os.path.join(root, "StemsStudio")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/StemsStudio")
    return os.path.join(os.environ.get("XDG_DATA_HOME", os.path.expanduser("~/.local/share")), "stems-studio")


DATA_DIR = default_data_dir()
LOCAL_LIBRARY_DIR = os.path.join(DATA_DIR, "library")
OUTPUT_DIR = LOCAL_LIBRARY_DIR
SETTINGS_PATH = os.path.join(DATA_DIR, "settings.json")
LIBRARY_NOTE = ""        # shown to the user when the chosen library folder could not be used
os.makedirs(DATA_DIR, exist_ok=True)


def chosen_library_dir():
    """The folder the user wants the song library in (for example a network drive), or None for the default.

    Either the STEMS_STUDIO_LIBRARY environment variable, or "library_dir" in settings.json
    (in the app's data folder, so each computer can choose its own).
    """
    wanted = os.environ.get("STEMS_STUDIO_LIBRARY")
    if not wanted:
        try:
            with open(SETTINGS_PATH, "r", encoding="utf-8") as handle:
                wanted = json.load(handle).get("library_dir")
        except (OSError, ValueError, AttributeError):
            wanted = None
    return os.path.expandvars(wanted).strip() if wanted else None


def use_library_dir(wanted):
    """Switch to the chosen folder if it can be written to; otherwise stay local and say why."""
    global OUTPUT_DIR, LIBRARY_NOTE
    try:
        os.makedirs(wanted, exist_ok=True)
        probe = os.path.join(wanted, ".write-test")
        with open(probe, "w") as handle:
            handle.write("ok")
        os.remove(probe)
        OUTPUT_DIR = wanted
    except OSError as exc:
        LIBRARY_NOTE = (f"The library folder {wanted} cannot be reached ({exc.strerror or exc}). "
                        "Using this computer's own library until it is back.")


_wanted_library = chosen_library_dir()
if _wanted_library:
    use_library_dir(_wanted_library)

# Earlier versions kept the library inside the code folder; move it across once.
_LEGACY_OUTPUT_DIR = os.path.join(BASE_DIR, "separated_output")
if os.path.isdir(_LEGACY_OUTPUT_DIR) and not os.path.exists(OUTPUT_DIR):
    try:
        shutil.move(_LEGACY_OUTPUT_DIR, OUTPUT_DIR)
    except OSError:
        pass
os.makedirs(OUTPUT_DIR, exist_ok=True)

NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def cli_python():
    """A console-capable Python for helper processes (pythonw.exe has no stdout)."""
    exe = sys.executable
    if os.name == "nt" and os.path.basename(exe).lower() == "pythonw.exe":
        candidate = os.path.join(os.path.dirname(exe), "python.exe")
        if os.path.isfile(candidate):
            return candidate
    return exe

# "Cleaner vocals": an optional, separate tool (audio-separator, in its own .venv-roformer
# environment so it can never disturb the main one) makes the vocal stem with a Roformer model,
# which leaks far less guitar and other instruments into the vocal than Demucs does.
ROFORMER_MODEL = "model_bs_roformer_ep_317_sdr_12.9755.ckpt"      # about 610 MB, downloaded on first use
ROFORMER_VENV = os.path.join(BASE_DIR, ".venv-roformer")


def roformer_cli():
    """Path of the audio-separator program, or None when 'cleaner vocals' is not installed."""
    candidate = os.path.join(ROFORMER_VENV, "Scripts", "audio-separator.exe") if os.name == "nt" \
        else os.path.join(ROFORMER_VENV, "bin", "audio-separator")
    return candidate if os.path.isfile(candidate) else None


DB_PATH = os.path.join(OUTPUT_DIR, "library.db")
SONG_ID_RE = re.compile(r"^[0-9a-f]{8}$")
PITCH_LOCK = threading.Lock()
# Stems the highway can follow (drums have no pitch).
HIGHWAY_STEMS = ("vocals", "bass", "guitar", "guitar_lead", "guitar_rhythm", "piano", "other")
YOUTUBE_ID_RE = re.compile(r"(?:v=|youtu\.be/|shorts/|embed/|live/)([A-Za-z0-9_-]{11})")


# ---------------------------------------------------------------------------
# Song library (SQLite). Remembers every finished separation so the same song
# is never split twice.
# ---------------------------------------------------------------------------
@contextlib.contextmanager
def library_db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    conn.row_factory = sqlite3.Row
    try:
        with conn:
            yield conn
    finally:
        conn.close()


def init_library():
    with library_db() as conn:
        conn.execute(
            """CREATE TABLE IF NOT EXISTS songs (
                id TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                source_type TEXT NOT NULL,
                source_label TEXT,
                content_key TEXT NOT NULL,
                model TEXT NOT NULL,
                preset TEXT NOT NULL,
                created_at REAL NOT NULL,
                stems_json TEXT NOT NULL,
                size_bytes INTEGER NOT NULL DEFAULT 0
            )"""
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_songs_key ON songs(content_key, model, preset)"
        )


def youtube_content_key(url):
    match = YOUTUBE_ID_RE.search(url)
    return "yt:" + (match.group(1) if match else url.strip())


def file_content_key(file_bytes):
    return "file:" + hashlib.sha256(file_bytes).hexdigest()


def song_dir(song_id):
    return os.path.join(OUTPUT_DIR, song_id)


# "05 - Like A Stone", "05. Like A Stone", "Track 5 - Like A Stone", "05 Like A Stone": the number is dropped.
TRACK_NUMBER_RE = re.compile(r"^\s*(?:(?:track\s*)?\d{1,3}\s*[-._)]\s*|0\d\s+(?=\D))", re.IGNORECASE)


def without_track_number(text):
    text = (text or "").strip()
    return TRACK_NUMBER_RE.sub("", text, count=1).strip() or text


def display_title(row):
    """What the library shows: 'Artist - Track name', with no track number. Uses the file's tags when known."""
    title = without_track_number(row["title"])
    try:
        with open(os.path.join(song_dir(row["id"]), "meta.json"), "r", encoding="utf-8") as handle:
            meta = json.load(handle)
    except (OSError, ValueError):
        meta = {}
    artist = str(meta.get("artist") or "").strip()
    track = without_track_number(str(meta.get("title") or "")) if meta.get("title") else ""
    if artist and (track or title):
        track = track or title
        if track.lower().startswith(artist.lower() + " - "):
            return track
        return f"{artist} - {track}"
    return track or title


def row_to_summary(row):
    stems = json.loads(row["stems_json"])
    return {
        "id": row["id"],
        "title": display_title(row),
        "source_type": row["source_type"],
        "source_label": row["source_label"],
        "model": row["model"],
        "preset": row["preset"],
        "created_at": row["created_at"],
        "stem_count": sum(1 for s in stems if not s.get("empty")),
        "size_bytes": row["size_bytes"],
        "drums_split": any(s["id"].startswith("drums_") for s in stems),
        "drums_can_split": any(s["id"] == "drums" for s in stems)
                           and os.path.isfile(os.path.join(song_dir(row["id"]), "drums.wav")),
        "vocals_can_clean": not row["preset"].endswith(CLEAN_VOCALS_SUFFIX)
                            and not os.path.isfile(os.path.join(song_dir(row["id"]), CLEANED_VOCALS_MARKER)),
    }


def stems_files_exist(song_id, stems):
    return bool(stems) and all(
        os.path.isfile(os.path.join(song_dir(song_id), os.path.basename(s["url"]))) for s in stems
    )


def find_cached_song(content_key, model, preset):
    """Return the saved song for this exact audio + model, or None."""
    with library_db() as conn:
        row = conn.execute(
            "SELECT * FROM songs WHERE content_key = ? AND model = ? AND preset = ?",
            (content_key, model, preset),
        ).fetchone()
        if not row:
            return None
        stems = json.loads(row["stems_json"])
        if not stems_files_exist(row["id"], stems):
            conn.execute("DELETE FROM songs WHERE id = ?", (row["id"],))
            return None
        return {"id": row["id"], "title": display_title(row), "stems": stems}


def save_song(song_id, title, source_type, source_label, content_key, model, preset, stems):
    size = 0
    for s in stems:
        path = os.path.join(song_dir(song_id), os.path.basename(s["url"]))
        if os.path.isfile(path):
            size += os.path.getsize(path)
    with library_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO songs
               (id, title, source_type, source_label, content_key, model, preset,
                created_at, stems_json, size_bytes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (song_id, title, source_type, source_label, content_key, model, preset,
             time.time(), json.dumps(stems), size),
        )


def list_songs():
    songs = []
    with library_db() as conn:
        rows = conn.execute("SELECT * FROM songs ORDER BY created_at DESC").fetchall()
        for row in rows:
            if stems_files_exist(row["id"], json.loads(row["stems_json"])):
                songs.append(row_to_summary(row))
            else:
                conn.execute("DELETE FROM songs WHERE id = ?", (row["id"],))
    return songs


def get_song(song_id):
    with library_db() as conn:
        row = conn.execute("SELECT * FROM songs WHERE id = ?", (song_id,)).fetchone()
    if not row:
        return None
    stems = json.loads(row["stems_json"])
    if not stems_files_exist(song_id, stems):
        return None
    summary = row_to_summary(row)
    summary["stems"] = stems
    return summary


def delete_song(song_id):
    with library_db() as conn:
        deleted = conn.execute("DELETE FROM songs WHERE id = ?", (song_id,)).rowcount
    shutil.rmtree(song_dir(song_id), ignore_errors=True)
    return deleted > 0


init_library()

# Active separation jobs: job_id -> { status, progress, message, stems, error }
JOBS = {}

NEPALI_FOLK_STEM_MAP = {
    "vocals": {"name": "Vocals / à¤¸à¥à¤µà¤°", "type": "vocal", "desc": "Lead Vocals & Chorus"},
    "drums": {"name": "Madal & Percussion / à¤®à¤¾à¤¦à¤²", "type": "drums", "desc": "Madal (Baya/Dahina), Tabla, Dholak"},
    "other": {"name": "Sarangi & Bansuri / à¤¸à¤¾à¤°à¤™à¥à¤—à¥€-à¤¬à¤¾à¤à¤¸à¥à¤°à¥€", "type": "other", "desc": "Folk Fiddle, Bamboo Flute, Lead"},
    "piano": {"name": "Harmonium & Keys / à¤¹à¤¾à¤°à¥à¤®à¥‹à¤¨à¤¿à¤¯à¤®", "type": "piano", "desc": "Bellows Harmonium & Drone"},
    "guitar": {"name": "Acoustic Pluck / à¤Ÿà¥à¤™à¥à¤¨à¤¾-à¤—à¤¿à¤¤à¤¾à¤°", "type": "guitar", "desc": "Tungna, Sarod, Acoustic Guitar"},
    "bass": {"name": "Bass & Low-End / à¤¬à¤¾à¤¸", "type": "bass", "desc": "Sub Bass & Low Frequencies"}
}

STANDARD_6S_STEM_MAP = {
    "vocals": {"name": "Vocals", "type": "vocal", "desc": "Lead and Backing Vocals"},
    "drums": {"name": "Drums", "type": "drums", "desc": "Drum Kit & Percussion"},
    "bass": {"name": "Bass", "type": "bass", "desc": "Bassline & Low End"},
    "guitar": {"name": "Guitar", "type": "guitar", "desc": "Electric & Acoustic Guitars"},
    "piano": {"name": "Piano", "type": "piano", "desc": "Acoustic Piano & Keys"},
    "other": {"name": "Other", "type": "other", "desc": "Strings, Synths, Brass"}
}

STANDARD_4S_STEM_MAP = {
    "vocals": {"name": "Vocals", "type": "vocal", "desc": "Vocals"},
    "drums": {"name": "Drums", "type": "drums", "desc": "Drums"},
    "bass": {"name": "Bass", "type": "bass", "desc": "Bassline"},
    "other": {"name": "Other", "type": "other", "desc": "Everything else: guitars, keys, strings, synths"}
}

# Folk names are only used when the user says the song is Nepali folk music: the model
# sorts sounds into groups, it cannot tell a madal from a drum kit by itself.
NEPALI_FOLK_4S_STEM_MAP = {
    "vocals": {"name": "Vocals / \u0938\u094d\u0935\u0930", "type": "vocal", "desc": "Lead Vocals & Chorus"},
    "drums": {"name": "Madal & Drums / \u092e\u093e\u0926\u0932", "type": "drums", "desc": "Madal, Tabla, Dholak, Drums"},
    "bass": {"name": "Bass / \u092c\u093e\u0938", "type": "bass", "desc": "Sub Bass & Low Frequencies"},
    "other": {"name": "Sarangi, Bansuri & Others", "type": "other", "desc": "Folk Fiddle, Flute, Harmonium, Plucked Strings"}
}

# Experimental: the guitar stem split by stereo position (see separator/guitar_split.py).
GUITAR_SPLIT_MAP = {
    "guitar_lead": {"name": "Lead Guitar (center)", "type": "guitar",
                    "desc": "Guitar parts sitting in the middle of the stereo picture, usually the lead"},
    "guitar_rhythm": {"name": "Rhythm Guitar (sides)", "type": "guitar",
                      "desc": "Guitar parts panned left and right, usually the rhythm guitars"},
}

STEM_ORDER = ["vocals", "drums", "drums_kick", "drums_snare", "drums_hh", "drums_toms", "drums_ride", "drums_crash", "bass", "guitar", "guitar_lead", "guitar_rhythm", "piano", "other"]

VALID_MODELS = ("htdemucs", "htdemucs_6s")
VALID_PRESETS = ("standard", "nepali_folk")
GUITAR_SPLIT_SUFFIX = "+gsplit"
CLEAN_VOCALS_SUFFIX = "+clean"
CLEANED_VOCALS_MARKER = "vocals.cleaned.json"   # written when a saved song got its vocal re-made


def clean_choices(model, preset, split_guitar=False, clean_vocals=False):
    """Only accept known model / naming choices; anything else falls back to the defaults.

    The guitar split and the cleaner vocals are remembered as suffixes on the naming choice, so a
    song made with them and the same song made without them are kept as separate library entries.
    """
    if model not in VALID_MODELS:
        model = "htdemucs_6s"
    if preset not in VALID_PRESETS:
        preset = "standard"
    if split_guitar and model == "htdemucs_6s":
        preset += GUITAR_SPLIT_SUFFIX
    if clean_vocals:
        preset += CLEAN_VOCALS_SUFFIX
    return model, preset


def truthy(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on")


# A stem counts as "nothing in it" when it is practically silent, or carries under 1% of the
# energy of all the stems together (about 20 dB quieter). Such stems are hidden in the mixer
# but kept on disk, so they can still be shown.
EMPTY_STEM_ABS_DB = -50.0
EMPTY_STEM_SHARE = 0.01
EMPTY_DRUM_PART_SHARE = 0.002   # a drum part with less than this share of the kit's energy is hidden


def find_empty_stems(stems_dir, stem_files):
    """Return the set of stem file names that have (almost) nothing in them."""
    try:
        import numpy as np
        import soundfile as sf

        energy = {}
        loudness_db = {}
        for name in stem_files:
            total = 0.0
            count = 0
            with sf.SoundFile(os.path.join(stems_dir, name)) as audio:
                for block in audio.blocks(blocksize=1 << 18, dtype="float32"):
                    total += float(np.sum(np.square(block, dtype=np.float64)))
                    count += block.size
            energy[name] = total
            rms = (total / count) ** 0.5 if count else 0.0
            loudness_db[name] = 20 * np.log10(rms + 1e-12)

        everything = sum(energy.values())
        if everything <= 0:
            return set()
        # The parts of a split drum kit are judged against the kit, not the whole song: a hi-hat
        # is quiet next to the vocal, but it is not empty.
        kit = sum(e for n, e in energy.items() if n.startswith("drums_"))
        empty = set()
        for name in stem_files:
            if name.startswith("drums_") and kit > 0:
                share = energy[name] / kit
                if loudness_db[name] < EMPTY_STEM_ABS_DB or share < EMPTY_DRUM_PART_SHARE:
                    empty.add(name)
            elif loudness_db[name] < EMPTY_STEM_ABS_DB or energy[name] / everything < EMPTY_STEM_SHARE:
                empty.add(name)
        # Never hide so much that almost nothing is left.
        keep = sorted(stem_files, key=lambda n: energy[n], reverse=True)[:2]
        return empty - set(keep)
    except Exception:
        traceback.print_exc()
        return set()


def separator_module(name):
    """Import one of the helper modules in the separator folder (they are optional extras)."""
    path = os.path.join(BASE_DIR, "separator")
    if path not in sys.path:
        sys.path.insert(0, path)
    return __import__(name)


def read_song_tags(audio_path, fallback_name=None):
    return separator_module("lyrics").read_tags(audio_path)


def write_json_file(path, payload):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(payload, handle)
    os.replace(tmp, path)


def save_song_lyrics(song_folder, tags, fallback_name, extra):
    """Find lyrics (the file's own tags first, then LRCLIB) and keep them with the song."""
    lyrics = separator_module("lyrics")
    result, meta = lyrics.find_for_song(tags, fallback_name, extra)
    write_json_file(os.path.join(song_folder, "meta.json"), meta)
    if result:
        write_json_file(os.path.join(song_folder, "lyrics.json"), result)
    return result


def load_song_lyrics(song_id):
    """The saved lyrics for a song, as the page wants them (never raises)."""
    folder = os.path.join(OUTPUT_DIR, song_id)
    payload = {"found": False, "meta": {}}
    try:
        with open(os.path.join(folder, "meta.json"), "r", encoding="utf-8") as handle:
            payload["meta"] = json.load(handle)
    except (OSError, ValueError):
        pass
    try:
        with open(os.path.join(folder, "lyrics.json"), "r", encoding="utf-8") as handle:
            payload.update(json.load(handle))
            payload["found"] = True
    except (OSError, ValueError):
        pass
    return payload


_device_info_cache = None
_device_info_lock = threading.Lock()


CPU_DEVICE_INFO = {
    "device": "cpu",
    "device_name": "CPU",
    "vram_gb": 0,
    "cuda_available": False,
    "cuda_version": None
}

# Runs in a separate process on purpose: importing PyTorch can freeze its whole process for
# many seconds, and that must never be the process that is serving the web page.
_DEVICE_PROBE_SCRIPT = """
import json
import subprocess
import torch

info = {"device": "cpu"}
if torch.cuda.is_available():
    props = torch.cuda.get_device_properties(0)
    info = {
        "device": "cuda",
        "device_name": torch.cuda.get_device_name(0),
        "vram_gb": round(props.total_memory / (1024 ** 3), 1),
        "cuda_available": True,
        "cuda_version": getattr(torch.version, "cuda", None),
    }
elif getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
    # Apple Silicon: PyTorch talks to the Mac's GPU through "MPS".
    try:
        torch.zeros(1, device="mps")
        chip = ""
        try:
            chip = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], text=True).strip()
        except Exception:
            pass
        info = {
            "device": "mps",
            "device_name": "Apple GPU" + (" (" + chip + ")" if chip else ""),
            "vram_gb": 0,
            "cuda_available": False,
            "cuda_version": None,
        }
    except Exception:
        pass
print(json.dumps(info))
"""

# Devices that count as "a graphics card" (everything else runs on the CPU).
GPU_DEVICES = ("cuda", "mps")


def _detect_device_info():
    # Escape hatch: set STEMS_STUDIO_DEVICE to cpu, cuda or mps to skip auto-detection.
    forced = os.environ.get("STEMS_STUDIO_DEVICE", "").strip().lower()
    if forced == "cpu":
        return dict(CPU_DEVICE_INFO)
    if forced in GPU_DEVICES:
        return {"device": forced, "device_name": f"{forced.upper()} (set by STEMS_STUDIO_DEVICE)",
                "vram_gb": 0, "cuda_available": forced == "cuda", "cuda_version": None}
    try:
        result = subprocess.run(
            [cli_python(), "-c", _DEVICE_PROBE_SCRIPT],
            capture_output=True, text=True, timeout=300, **NO_WINDOW
        )
        info = json.loads(result.stdout.strip().splitlines()[-1])
        if info.get("device") in GPU_DEVICES:
            return info
    except Exception:
        pass
    return dict(CPU_DEVICE_INFO)


def get_device_info():
    """Detect the compute device once. Importing PyTorch is slow, so the result is cached."""
    global _device_info_cache
    with _device_info_lock:
        if _device_info_cache is None:
            _device_info_cache = _detect_device_info()
        return _device_info_cache


def peek_device_info():
    """Return the cached device info without waiting, or None while detection is still running."""
    return _device_info_cache


def warm_up_device_info():
    threading.Thread(target=get_device_info, daemon=True).start()


def run_audio_separator(audio_file, model, out_dir, job, base, span, label, download_note):
    """Run one model of the optional audio-separator tool. Returns the list of WAV files it wrote.

    base/span: where this step sits on the job's progress bar. label: what the message says.
    """
    cli = roformer_cli()
    if not cli:
        raise Exception("This needs the optional extra tool. Close Stems Studio and run the installer "
                        "again, and say yes to 'cleaner vocals' (Install.bat on Windows, "
                        "Install.command on Mac/Linux).")
    models_dir = os.path.join(DATA_DIR, "models")
    os.makedirs(out_dir, exist_ok=True)
    os.makedirs(models_dir, exist_ok=True)
    cmd = [cli, audio_file, "-m", model, "--model_file_dir", models_dir,
           "--output_dir", out_dir, "--output_format", "WAV"]
    env = dict(os.environ, PYTORCH_ENABLE_MPS_FALLBACK="1", PYTHONIOENCODING="utf-8")
    process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                               universal_newlines=True, encoding="utf-8", errors="replace",
                               env=env, **NO_WINDOW)
    recent_output = []
    for line in process.stdout:
        for piece in line.replace("\r", "\n").split("\n"):
            piece = piece.strip()
            if not piece:
                continue
            recent_output = (recent_output + [piece])[-6:]
            if "Downloading" in piece or "download" in piece.lower():
                job["message"] = download_note
            if "%" in piece and "|" in piece:
                try:
                    pct = int(piece.split("%")[0].split()[-1])
                    job["progress"] = base + int(pct * span / 100)
                    job["message"] = f"{label}: {pct}%"
                except Exception:
                    pass
    process.wait()
    if process.returncode != 0:
        raise Exception(f"{label} failed (code {process.returncode}): {' | '.join(recent_output)}")
    return [os.path.join(out_dir, n) for n in os.listdir(out_dir) if n.lower().endswith(".wav")]


def run_roformer(audio_file, job_dir, job):
    """Make the vocal with the Roformer model. Returns (vocals wav, instrumental wav)."""
    files = run_audio_separator(
        audio_file, ROFORMER_MODEL, os.path.join(job_dir, "roformer"), job, 12, 35,
        "Making a cleaner vocal", "Downloading the cleaner-vocals model (one time, about 600 MB)...")
    vocals = instrumental = None
    for path in files:
        lower = os.path.basename(path).lower()
        if "(vocals)" in lower:
            vocals = path
        elif "(instrumental)" in lower or "(other)" in lower or "(no_vocals)" in lower:
            instrumental = path
    if not vocals or not instrumental:
        raise Exception("Cleaner vocals did not produce the expected files.")
    return vocals, instrumental


# Splitting the drums into kick, snare, toms, hi-hat, ride and crash (the DrumSep model by
# aufr33 and jarredou), with the same optional tool as "cleaner vocals".
DRUMSEP_MODEL = "MDX23C-DrumSep-aufr33-jarredou.ckpt"
DRUM_PART_MAP = {
    "drums_kick": {"name": "Kick", "type": "drums", "desc": "Bass drum", "part": "kick"},
    "drums_snare": {"name": "Snare", "type": "drums", "desc": "Snare drum", "part": "snare"},
    "drums_toms": {"name": "Toms", "type": "drums", "desc": "Tom-toms", "part": "toms"},
    "drums_hh": {"name": "Hi-hat", "type": "drums", "desc": "Hi-hat", "part": "hh"},
    "drums_ride": {"name": "Ride", "type": "drums", "desc": "Ride cymbal", "part": "ride"},
    "drums_crash": {"name": "Crash", "type": "drums", "desc": "Crash cymbal", "part": "crash"},
}


def split_drums_in_folder(folder, job, base, span):
    """Split folder/drums.wav into folder/drums_kick.wav, drums_snare.wav... Returns their file names."""
    work = os.path.join(folder, "drumsep")
    try:
        files = run_audio_separator(
            os.path.join(folder, "drums.wav"), DRUMSEP_MODEL, work, job, base, span,
            "Splitting the drums", "Downloading the drum-splitting model (one time)...")
        made = []
        for stem_key, meta in DRUM_PART_MAP.items():
            wanted = f"({meta['part']})"
            source = next((f for f in files if wanted in os.path.basename(f).lower()), None)
            if source:
                shutil.move(source, os.path.join(folder, stem_key + ".wav"))
                made.append(stem_key + ".wav")
        if not made:
            raise Exception("The drum splitter did not produce the expected files.")
        return made
    finally:
        shutil.rmtree(work, ignore_errors=True)


def update_song_stems(song_id, stems):
    size = sum(os.path.getsize(os.path.join(song_dir(song_id), os.path.basename(s["url"])))
               for s in stems if os.path.isfile(os.path.join(song_dir(song_id), os.path.basename(s["url"]))))
    with library_db() as conn:
        conn.execute("UPDATE songs SET stems_json = ?, size_bytes = ? WHERE id = ?",
                     (json.dumps(stems), size, song_id))


def run_drum_split_job(job_id, song_id):
    """Split the drums of a song that is already in the library."""
    job = JOBS[job_id]
    folder = song_dir(song_id)
    try:
        song = get_song(song_id)
        if not song or not os.path.isfile(os.path.join(folder, "drums.wav")):
            raise Exception("This song has no drum stem to split.")
        job["message"] = "Splitting the drums..."
        job["progress"] = 5
        made = split_drums_in_folder(folder, job, 5, 90)
        stems = [s for s in song["stems"] if s["id"] != "drums"]
        for name in made:
            key = os.path.splitext(name)[0]
            meta = DRUM_PART_MAP[key]
            stems.append({"id": key, "name": meta["name"], "stemType": meta["type"], "desc": meta["desc"],
                          "empty": False, "url": f"/api/stems/{song_id}/{name}"})
        stems.sort(key=lambda s: (STEM_ORDER.index(s["id"]) if s["id"] in STEM_ORDER else len(STEM_ORDER), s["id"]))
        empty = find_empty_stems(folder, [os.path.basename(s["url"]) for s in stems])
        for s in stems:
            s["empty"] = os.path.basename(s["url"]) in empty
        update_song_stems(song_id, stems)
        job["stems"] = stems
        job["title"] = song["title"]
        job["progress"] = 100
        job["status"] = "completed"
        job["message"] = "Drums split."
    except Exception as e:
        traceback.print_exc()
        job["status"] = "error"
        job["error"] = str(e)
        job["message"] = f"Error: {e}"

def run_clean_vocals_job(job_id, song_id):
    """Re-make the vocal of a song that is already in the library, with the Roformer model.

    The library keeps no copy of the original file, so the song is put back together from its own
    stems (their sum is the song, to within rounding). Whatever the new vocal no longer holds (the
    guitar that had leaked into it) goes to the guitar stem, or to Other, so the stems still add up.
    """
    import numpy as np
    import soundfile as sf

    job = JOBS[job_id]
    folder = song_dir(song_id)
    work = os.path.join(folder, "cleanvocals")
    try:
        song = get_song(song_id)
        if not song:
            raise Exception("Song not found in the library.")
        files = {s["id"]: os.path.join(folder, os.path.basename(s["url"])) for s in song["stems"]}
        if "vocals" not in files or not all(os.path.isfile(f) for f in files.values()):
            raise Exception("This song's stems are not all on disk.")
        job["message"] = "Putting the song back together..."
        job["progress"] = 3
        mix = None
        rate = None
        for path in files.values():
            data, sr = sf.read(path, dtype="float32", always_2d=True)
            rate = rate or sr
            if sr != rate:
                raise Exception("The stems have different sample rates.")
            if mix is None:
                mix = data.copy()
            else:
                frames = min(len(mix), len(data))
                mix[:frames] += data[:frames]
        peak = float(np.abs(mix).max())
        scale = 1.0 / peak if peak > 0.98 else 1.0       # the model must not get a clipped mix
        os.makedirs(work, exist_ok=True)
        mix_path = os.path.join(work, "mix.wav")
        sf.write(mix_path, mix * scale, rate, subtype="FLOAT")
        del mix

        new_vocals_path, _instrumental = run_roformer(mix_path, work, job)
        new_vocals, sr = sf.read(new_vocals_path, dtype="float32", always_2d=True)
        if sr != rate:
            raise Exception("The new vocal has a different sample rate.")
        new_vocals = new_vocals / scale
        job["message"] = "Saving..."
        job["progress"] = 90

        old_vocals, _ = sf.read(files["vocals"], dtype="float32", always_2d=True)
        frames = len(old_vocals)
        if len(new_vocals) < frames:
            new_vocals = np.pad(new_vocals, ((0, frames - len(new_vocals)), (0, 0)))
        new_vocals = new_vocals[:frames]
        if new_vocals.shape[1] != old_vocals.shape[1]:
            new_vocals = np.repeat(new_vocals[:, :1], old_vocals.shape[1], axis=1)
        leftover = old_vocals - new_vocals
        home_id = next((k for k in ("guitar", "other") if k in files), None)
        if home_id:
            home, _ = sf.read(files[home_id], dtype="float32", always_2d=True)
            n = min(len(home), frames)
            home[:n] += leftover[:n]
            sf.write(files[home_id], np.clip(home, -1.0, 1.0), rate, subtype="PCM_16")
        sf.write(files["vocals"], np.clip(new_vocals, -1.0, 1.0), rate, subtype="PCM_16")

        stems = song["stems"]
        empty = find_empty_stems(folder, [os.path.basename(s["url"]) for s in stems])
        for s in stems:
            s["empty"] = os.path.basename(s["url"]) in empty
        update_song_stems(song_id, stems)
        with open(os.path.join(folder, CLEANED_VOCALS_MARKER), "w", encoding="utf-8") as handle:
            json.dump({"model": ROFORMER_MODEL, "leftover_went_to": home_id}, handle)
        job["stems"] = stems
        job["title"] = song["title"]
        job["progress"] = 100
        job["status"] = "completed"
        job["message"] = "Vocals cleaned."
    except Exception as e:
        traceback.print_exc()
        job["status"] = "error"
        job["error"] = str(e)
        job["message"] = f"Error: {e}"
    finally:
        shutil.rmtree(work, ignore_errors=True)


def busy_job_for(song_id):
    """The running job (split drums / clean vocals) that is working on this song, if any."""
    for other in list(JOBS.values()):
        if other.get("song_busy") == song_id and other.get("status") == "processing":
            return other
    return None


def run_separation_job(job_id, source_type, source_val, model="htdemucs_6s", preset="nepali_folk",
                       content_key=None, source_label="", title=None, split_drums=False):
    job = JOBS[job_id]
    job_dir = os.path.join(OUTPUT_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    library_preset = preset   # what the library remembers (includes the option suffixes)
    clean_vocals = preset.endswith(CLEAN_VOCALS_SUFFIX)
    if clean_vocals:
        preset = preset[:-len(CLEAN_VOCALS_SUFFIX)]
    split_guitar = preset.endswith(GUITAR_SPLIT_SUFFIX)
    if split_guitar:
        preset = preset[:-len(GUITAR_SPLIT_SUFFIX)]

    try:
        audio_file = None
        lyrics_tags = None
        lyrics_extra = None
        dev_info = get_device_info()
        device_arg = dev_info["device"]

        # Step 1: Acquire audio file
        if source_type == "youtube":
            job["message"] = f"Downloading audio from YouTube ({dev_info['device_name']})..."
            job["progress"] = 15
            try:
                import yt_dlp
            except ImportError:
                raise Exception("YouTube support (yt-dlp) is not installed. Try a song file instead.")
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': os.path.join(job_dir, 'source_audio.%(ext)s'),
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'wav',
                    'preferredquality': '192',
                }],
                'quiet': True
            }
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(source_val, download=True)
                job["title"] = info.get("title", "YouTube Audio")
                # What YouTube knows about the song, for the lyrics lookup.
                lyrics_extra = {
                    "artist": info.get("artist") or info.get("creator"),
                    "title": info.get("track") or info.get("title"),
                    "album": info.get("album"),
                    "duration": info.get("duration"),
                }
            audio_file = os.path.join(job_dir, "source_audio.wav")
        else:
            audio_file = source_val
            job["title"] = title or os.path.splitext(os.path.basename(audio_file))[0]
            # Read the file's own tags (artist, title, embedded lyrics) before the file is cleaned up.
            try:
                lyrics_tags = read_song_tags(audio_file, source_label)
            except Exception:
                traceback.print_exc()

        if not os.path.isfile(audio_file):
            raise Exception("Failed to prepare source audio file.")

        # Step 2a (optional): the cleanest vocal, from a Roformer model. What is left over
        # (the music without the voice) is then split into drums, bass, guitar... by Demucs.
        demucs_input = audio_file
        roformer_vocals = None
        progress_base, progress_span = 35, 0.55      # where Demucs' progress bar starts and how far it goes
        if clean_vocals:
            job["message"] = "Making a cleaner vocal (the first time, a 600 MB model is downloaded)..."
            job["progress"] = 12
            roformer_vocals, demucs_input = run_roformer(audio_file, job_dir, job)
            progress_base, progress_span = 50, 0.40

        # Step 2: Run Demucs Separation with GPU acceleration
        job["message"] = f"Running neural separation with {model} on {dev_info['device_name']}..."
        job["progress"] = progress_base

        def run_demucs(device):
            cmd = [
                cli_python(), "-m", "demucs.separate",
                "-n", model,
                "-d", device,
                "-o", job_dir,
                demucs_input
            ]
            # On a Mac, let PyTorch quietly use the CPU for the few operations the GPU lacks.
            env = dict(os.environ, PYTORCH_ENABLE_MPS_FALLBACK="1")
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                       universal_newlines=True, env=env, **NO_WINDOW)

            recent_output = []
            for line in process.stdout:
                if line.strip():
                    recent_output = (recent_output + [line.strip()])[-6:]
                if "%" in line:
                    try:
                        parts = line.split("%")[0].split()
                        pct = int(parts[-1])
                        job["progress"] = progress_base + int(pct * progress_span)
                        job["message"] = f"Processing neural stems: {pct}%"
                    except Exception:
                        pass

            process.wait()
            return process.returncode, " | ".join(recent_output)

        returncode, tail = run_demucs(device_arg)
        missing_demucs = "No module named" in tail and "demucs" in tail
        if returncode != 0 and device_arg != "cpu" and not missing_demucs:
            # The graphics card failed (out of memory, unsupported driver, ...). A slow
            # result is better than no result, so try again on the CPU.
            job["message"] = "The graphics card could not process this song. Retrying on the CPU (slower)..."
            job["progress"] = progress_base
            returncode, tail = run_demucs("cpu")
            missing_demucs = "No module named" in tail and "demucs" in tail
        if returncode != 0:
            if missing_demucs:
                raise Exception("Demucs is not installed. Close Stems Studio and run the installer "
                                "again (Install.bat on Windows, Install.command on Mac/Linux).")
            raise Exception(f"Demucs failed (code {returncode}): {tail}")

        # Step 3: Collect generated stems
        job["message"] = "Finalizing stem channels..."
        job["progress"] = 92

        audio_base = os.path.splitext(os.path.basename(demucs_input))[0]
        stems_source_dir = os.path.join(job_dir, model, audio_base)

        if not os.path.isdir(stems_source_dir):
            for root, dirs, files in os.walk(job_dir):
                if any(f.endswith(".wav") for f in files) and root != job_dir:
                    stems_source_dir = root
                    break

        stem_files = [f for f in os.listdir(stems_source_dir) if f.endswith(".wav")]
        if not stem_files:
            raise Exception("No stem audio files were generated.")

        if clean_vocals and roformer_vocals:
            # The Roformer vocal replaces the one Demucs found on the leftover (vocal-free) music.
            shutil.copy2(roformer_vocals, os.path.join(stems_source_dir, "vocals.wav"))
            if "vocals.wav" not in stem_files:
                stem_files.append("vocals.wav")

        if split_guitar and "guitar.wav" in stem_files:
            job["message"] = "Splitting the guitar into lead and rhythm (by stereo position)..."
            job["progress"] = 93
            try:
                sys.path.insert(0, os.path.join(BASE_DIR, "separator"))
                import guitar_split
                guitar_split.split_file(
                    os.path.join(stems_source_dir, "guitar.wav"),
                    os.path.join(stems_source_dir, "guitar_lead.wav"),
                    os.path.join(stems_source_dir, "guitar_rhythm.wav"))
                stem_files = [f for f in stem_files if f != "guitar.wav"] + ["guitar_lead.wav", "guitar_rhythm.wav"]
            except Exception:
                # Keep the ordinary single guitar stem rather than failing the whole song.
                traceback.print_exc()

        if split_drums and "drums.wav" in stem_files and roformer_cli():
            job["message"] = "Splitting the drums into kick, snare, hi-hat and cymbals..."
            job["progress"] = 93
            try:
                parts = split_drums_in_folder(stems_source_dir, job, 93, 3)
                # The whole drum track stays on disk (the highway can still use it); the parts replace it in the mixer.
                shutil.copy2(os.path.join(stems_source_dir, "drums.wav"), os.path.join(job_dir, "drums.wav"))
                stem_files = [f for f in stem_files if f != "drums.wav"] + parts
            except Exception:
                traceback.print_exc()      # keep the ordinary drum stem rather than failing the whole song

        # Pick mapping dictionary
        if preset == "nepali_folk":
            mapping = NEPALI_FOLK_STEM_MAP if model == "htdemucs_6s" else NEPALI_FOLK_4S_STEM_MAP
        elif model == "htdemucs_6s":
            mapping = STANDARD_6S_STEM_MAP
        else:
            mapping = STANDARD_4S_STEM_MAP

        mapping = dict(mapping, **GUITAR_SPLIT_MAP, **DRUM_PART_MAP)
        empty_files = find_empty_stems(stems_source_dir, stem_files)

        stems_result = []
        # Vocals first (the stem most people care about), then the rest in a fixed order.
        for sf in sorted(stem_files, key=lambda f: (STEM_ORDER.index(os.path.splitext(f)[0].lower())
                                                    if os.path.splitext(f)[0].lower() in STEM_ORDER
                                                    else len(STEM_ORDER), f)):
            stem_key = os.path.splitext(sf)[0].lower()
            meta = mapping.get(stem_key, {
                "name": stem_key.capitalize(),
                "type": "custom",
                "desc": "Audio Stem"
            })

            dest_file = os.path.join(job_dir, sf)
            if dest_file != os.path.join(stems_source_dir, sf):
                shutil.copy2(os.path.join(stems_source_dir, sf), dest_file)

            stems_result.append({
                "id": stem_key,
                "name": meta["name"],
                "stemType": meta["type"],
                "desc": meta["desc"],
                "empty": sf in empty_files,
                "url": f"/api/stems/{job_id}/{sf}"
            })

        job["message"] = "Looking for the lyrics..."
        job["progress"] = 96
        try:
            save_song_lyrics(job_dir, lyrics_tags,
                             source_label if source_type == "file" else job.get("title"), lyrics_extra)
        except Exception:
            traceback.print_exc()          # lyrics are a bonus: never fail the song because of them

        # Keep only the finished stems; drop the working copies to save disk space.
        for entry in os.listdir(job_dir):
            entry_path = os.path.join(job_dir, entry)
            if os.path.isdir(entry_path):
                shutil.rmtree(entry_path, ignore_errors=True)
        if os.path.isfile(audio_file) and os.path.basename(audio_file) not in stem_files:
            os.remove(audio_file)

        if content_key:
            save_song(job_id, job.get("title", "Untitled"), source_type, source_label,
                      content_key, model, library_preset, stems_result)

        job["stems"] = stems_result
        job["progress"] = 100
        job["status"] = "completed"
        job["message"] = "Stem separation complete!"

    except Exception as e:
        shutil.rmtree(job_dir, ignore_errors=True)
        job["status"] = "error"
        job["error"] = str(e)
        job["message"] = f"Error: {e}"


class StudioRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def end_headers(self):
        # The page's own files must be checked again on every load; otherwise the window can keep
        # running an old script after an update. (Audio stays cacheable.)
        path = urllib.parse.urlparse(self.path).path
        if path == "/" or path.endswith((".js", ".css", ".html")):
            self.send_header("Cache-Control", "no-cache")
        super().end_headers()

    def send_json(self, payload, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def start_cached_job(self, job_id, cached):
        JOBS[job_id] = {
            "id": job_id,
            "status": "completed",
            "progress": 100,
            "message": "Found in your library - no need to separate again.",
            "title": cached["title"],
            "stems": cached["stems"],
            "cached": True,
        }
        self.send_json({"job_id": job_id, "cached": True})

    def run_guarded(self, handler):
        """Report server-side crashes to the page instead of silently dropping the connection."""
        try:
            handler()
        except (BrokenPipeError, ConnectionResetError):
            raise
        except Exception as exc:
            traceback.print_exc()
            if self.path.startswith("/api/"):
                try:
                    self.send_json({"error": f"{type(exc).__name__}: {exc}"}, 500)
                except Exception:
                    pass
            else:
                raise

    def do_GET(self):
        self.run_guarded(self.handle_get)

    def do_POST(self):
        self.run_guarded(self.handle_post)

    def do_DELETE(self):
        self.run_guarded(self.handle_delete)

    def handle_get(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/api/heartbeat":
            if LIFECYCLE:
                LIFECYCLE.beat()
            self.send_json({"ok": True})
            return

        elif parsed.path == "/api/update":
            self.send_json(updater.get_state())
            return

        elif parsed.path == "/api/library":
            self.send_json({"songs": list_songs(), "folder": OUTPUT_DIR, "note": LIBRARY_NOTE})
            return

        elif parsed.path.startswith("/api/library/"):
            song_id = parsed.path.split("/")[3]
            song = get_song(song_id) if SONG_ID_RE.match(song_id) else None
            if song:
                self.send_json(song)
            else:
                self.send_json({"error": "Song not found in library"}, 404)
            return

        elif parsed.path == "/api/engine":
            dev_info = peek_device_info()
            if dev_info is None:
                dev_info = {"device": "unknown", "device_name": "", "cuda_available": False, "pending": True}
            self.send_json(dict(dev_info, library=True, app=APP_NAME, version=APP_VERSION,
                                clean_vocals_available=roformer_cli() is not None,
                                drum_split_available=roformer_cli() is not None,
                                library_dir=OUTPUT_DIR, library_note=LIBRARY_NOTE))
            return

        elif parsed.path == "/api/status":
            query = urllib.parse.parse_qs(parsed.query)
            job_id = query.get("job_id", [""])[0]
            job = JOBS.get(job_id)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()

            if job:
                self.wfile.write(json.dumps(job).encode("utf-8"))
            else:
                self.wfile.write(json.dumps({"status": "not_found"}).encode("utf-8"))
            return

        elif parsed.path.startswith("/api/pitch/") or parsed.path.startswith("/api/notes/"):
            # /api/pitch/<id>[?stem=bass]: the single melody line of a stem, for the highway.
            # /api/notes/<id>?stem=piano: every note of a chord or piano stem (piano-roll mode).
            song_id = parsed.path.split("/")[3]
            stem = (urllib.parse.parse_qs(parsed.query).get("stem") or ["vocals"])[0]
            wav_path = os.path.join(OUTPUT_DIR, song_id, stem + ".wav")
            if not SONG_ID_RE.match(song_id) or stem not in HIGHWAY_STEMS or not os.path.isfile(wav_path):
                self.send_json({"error": f"No {stem} stem found for this song"}, 404)
                return
            polyphonic_request = parsed.path.startswith("/api/notes/")
            try:
                module = separator_module("polyphonic" if polyphonic_request else "pitch_track")
            except ImportError as exc:
                self.send_json({"error": f"Pitch tracker is not installed: {exc}"}, 501)
                return
            if polyphonic_request and not module.available():
                self.send_json({"error": "Note finder needs onnxruntime (run Install.bat again)"}, 501)
                return
            with PITCH_LOCK:   # one analysis at a time; a second request waits and then reads the saved result
                if polyphonic_request:
                    result = module.cached_notes(wav_path, os.path.join(OUTPUT_DIR, song_id, stem + ".notes.json"))
                    self.send_json({"notes": result["notes"]})
                    return
                result = module.cached_analysis(wav_path, os.path.join(OUTPUT_DIR, song_id, stem + ".pitch.json"))
            payload = {"t0": result["t0"], "dt": result["dt"], "midi": result["midi"]}
            for key in ("rough_midi", "rough_auto", "unpitched_loud"):   # growls and screams, when there are any
                if key in result:
                    payload[key] = result[key]
            self.send_json(payload)
            return
        elif parsed.path.startswith("/api/hits/"):
            # When the drums hit (kick, snare, hi-hat...), for the drum lane of the highway.
            song_id = parsed.path.split("/")[3]
            folder = os.path.join(OUTPUT_DIR, song_id)
            if not SONG_ID_RE.match(song_id) or not os.path.isdir(folder):
                self.send_json({"error": "Song not found"}, 404)
                return
            try:
                drum_hits = separator_module("drum_hits")
            except ImportError as exc:
                self.send_json({"error": f"Drum finder is not installed: {exc}"}, 501)
                return
            with PITCH_LOCK:
                result = drum_hits.cached_hits(folder, os.path.join(folder, "drums.hits.json"))
            if not result:
                self.send_json({"error": "This song has no drum stem"}, 404)
                return
            self.send_json({"lanes": result["lanes"], "approximate": result["approximate"]})
            return

        elif parsed.path.startswith("/api/analysis/"):
            # Key and chords of a song, found from its separated stems.
            song_id = parsed.path.split("/")[3]
            folder = os.path.join(OUTPUT_DIR, song_id)
            if not SONG_ID_RE.match(song_id) or not os.path.isdir(folder):
                self.send_json({"error": "Song not found"}, 404)
                return
            try:
                music_analysis = separator_module("music_analysis")
            except ImportError as exc:
                self.send_json({"error": f"Key finder is not installed: {exc}"}, 501)
                return
            with PITCH_LOCK:
                vocal_midi = None
                vocals = os.path.join(folder, "vocals.wav")
                if os.path.isfile(vocals):
                    try:
                        pitch_track = separator_module("pitch_track")
                        vocal_midi = pitch_track.cached_analysis(vocals, os.path.join(folder, "vocals.pitch.json"))["midi"]
                    except ImportError:
                        pass
                result = music_analysis.cached_analysis(folder, os.path.join(folder, "analysis.json"), vocal_midi)
            self.send_json({k: result[k] for k in ("key", "chords", "tuning_cents", "sources")})
            return

        elif parsed.path.startswith("/api/lyrics/"):
            parts = parsed.path.split("/")
            song_id = parts[3] if len(parts) > 3 else ""
            if not SONG_ID_RE.match(song_id) or not os.path.isdir(os.path.join(OUTPUT_DIR, song_id)):
                self.send_json({"error": "Song not found"}, 404)
                return
            if len(parts) > 4 and parts[4] == "find":
                # Search LRCLIB for what the user typed, and keep the best match with the song.
                query = urllib.parse.parse_qs(parsed.query)
                artist = query.get("artist", [""])[0].strip() or None
                title = query.get("title", [""])[0].strip()
                if not title:
                    self.send_json({"error": "Type the song title first."}, 400)
                    return
                lyrics = separator_module("lyrics")
                try:
                    result = lyrics.fetch_lrclib(artist, title, None, None)
                except Exception as exc:
                    self.send_json({"error": f"Could not reach LRCLIB ({type(exc).__name__}). Check your internet connection."}, 502)
                    return
                if not result:
                    self.send_json({"found": False, "meta": {"artist": artist, "title": title}})
                    return
                folder = os.path.join(OUTPUT_DIR, song_id)
                write_json_file(os.path.join(folder, "lyrics.json"), result)
                write_json_file(os.path.join(folder, "meta.json"), {"artist": artist or result["matched"].get("artist"),
                                                                    "title": title, "album": result["matched"].get("album"),
                                                                    "duration": result["matched"].get("duration")})
            self.send_json(load_song_lyrics(song_id))
            return

        elif parsed.path.startswith("/api/stems/"):
            parts = parsed.path.split("/")
            if len(parts) >= 5:
                job_id = parts[3]
                filename = parts[4]
                file_path = os.path.join(OUTPUT_DIR, job_id, filename)

                if SONG_ID_RE.match(job_id) and filename.endswith(".wav") and os.path.isfile(file_path):
                    self.send_response(200)
                    self.send_header("Content-Type", "audio/wav")
                    self.send_header("Content-Length", str(os.path.getsize(file_path)))
                    self.end_headers()
                    with open(file_path, "rb") as f:
                        shutil.copyfileobj(f, self.wfile)
                    return

            self.send_error(404, "Stem file not found")
            return

        super().do_GET()

    def handle_post(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/api/closing":
            if LIFECYCLE:
                LIFECYCLE.closing()
            self.send_response(204)
            self.end_headers()
            return

        if parsed.path in ("/api/update/check", "/api/update/apply"):
            # Only the app's own page may ask for this (another website could otherwise poke the local server).
            origin = self.headers.get("Origin")
            if origin and origin not in (f"http://127.0.0.1:{self.server.server_address[1]}",
                                         f"http://localhost:{self.server.server_address[1]}"):
                self.send_json({"error": "Not allowed"}, 403)
                return
            if parsed.path.endswith("/check"):
                self.send_json(updater.check())
            else:
                self.send_json(updater.apply())
            return

        if parsed.path == "/api/separate":
            content_type = self.headers.get("Content-Type", "")
            job_id = str(uuid.uuid4())[:8]

            if "application/json" in content_type:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8")
                data = json.loads(body)

                youtube_url = data.get("youtube_url", "").strip()
                model, preset = clean_choices(data.get("model"), data.get("preset"),
                                              truthy(data.get("guitar_split", False)),
                                              truthy(data.get("clean_vocals", False)))
                split_drums = truthy(data.get("split_drums", False))

                if not youtube_url:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b'{"error": "No YouTube URL provided"}')
                    return

                content_key = youtube_content_key(youtube_url)
                cached = find_cached_song(content_key, model, preset)
                if cached:
                    self.start_cached_job(job_id, cached)
                    return

                JOBS[job_id] = {
                    "id": job_id,
                    "status": "processing",
                    "progress": 5,
                    "message": "Initializing job...",
                    "stems": []
                }

                t = threading.Thread(
                    target=run_separation_job,
                    args=(job_id, "youtube", youtube_url, model, preset, content_key, youtube_url, None, split_drums),
                    daemon=True
                )
                t.start()

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"job_id": job_id}).encode("utf-8"))
                return

            elif "multipart/form-data" in content_type:
                length = int(self.headers.get("Content-Length", 0))
                body_bytes = self.rfile.read(length)

                header_bytes = f"Content-Type: {content_type}\r\n\r\n".encode("utf-8")
                msg = email.parser.BytesParser().parsebytes(header_bytes + body_bytes)

                model = "htdemucs_6s"
                preset = "standard"
                guitar_split = False
                clean_vocals = False
                split_drums = False
                file_bytes = None
                file_name = "uploaded_audio.wav"

                if msg.is_multipart():
                    for part in msg.get_payload():
                        cd = part.get("Content-Disposition", "")
                        if 'name="model"' in cd:
                            model = part.get_payload(decode=True).decode("utf-8").strip()
                        elif 'name="preset"' in cd:
                            preset = part.get_payload(decode=True).decode("utf-8").strip()
                        elif 'name="guitar_split"' in cd:
                            guitar_split = truthy(part.get_payload(decode=True).decode("utf-8"))
                        elif 'name="clean_vocals"' in cd:
                            clean_vocals = truthy(part.get_payload(decode=True).decode("utf-8"))
                        elif 'name="split_drums"' in cd:
                            split_drums = truthy(part.get_payload(decode=True).decode("utf-8"))
                        elif 'name="file"' in cd:
                            fname = part.get_filename()
                            if fname:
                                file_name = fname
                            file_bytes = part.get_payload(decode=True)

                model, preset = clean_choices(model, preset, guitar_split, clean_vocals)

                if not file_bytes:
                    self.send_response(400)
                    self.end_headers()
                    self.wfile.write(b'{"error": "No file payload received"}')
                    return

                content_key = file_content_key(file_bytes)
                cached = find_cached_song(content_key, model, preset)
                if cached:
                    self.start_cached_job(job_id, cached)
                    return

                original_name = os.path.basename(file_name.replace("\\", "/"))
                title = os.path.splitext(original_name)[0] or "Untitled"
                ext = os.path.splitext(original_name)[1].lower()
                if not re.fullmatch(r"\.[a-z0-9]{1,5}", ext):
                    ext = ".wav"

                job_dir = os.path.join(OUTPUT_DIR, job_id)
                os.makedirs(job_dir, exist_ok=True)
                uploaded_path = os.path.join(job_dir, "source_upload" + ext)

                with open(uploaded_path, "wb") as f:
                    f.write(file_bytes)

                JOBS[job_id] = {
                    "id": job_id,
                    "status": "processing",
                    "progress": 10,
                    "message": "Saved uploaded file...",
                    "stems": []
                }

                t = threading.Thread(
                    target=run_separation_job,
                    args=(job_id, "file", uploaded_path, model, preset, content_key, original_name, title, split_drums),
                    daemon=True
                )
                t.start()

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"job_id": job_id}).encode("utf-8"))
                return

        if parsed.path.startswith("/api/library/") and parsed.path.endswith("/split-drums"):
            song_id = parsed.path.split("/")[3]
            if not SONG_ID_RE.match(song_id) or not get_song(song_id):
                self.send_json({"error": "Song not found in library"}, 404)
                return
            if not roformer_cli():
                self.send_json({"error": "Splitting the drums needs the optional extra tool. Close Stems Studio and run the "
                                         "installer again, and say yes to cleaner vocals."}, 501)
                return
            # Two jobs on the same song at once would overwrite each other's files.
            busy = busy_job_for(song_id)
            if busy:
                if busy.get("song_task") == "split-drums":
                    self.send_json({"job_id": busy["id"]})
                else:
                    self.send_json({"error": "This song is being worked on. Wait for that to finish."}, 409)
                return
            job_id = str(uuid.uuid4())[:8]
            JOBS[job_id] = {"id": job_id, "status": "processing", "progress": 2, "message": "Starting...", "stems": [],
                            "song_busy": song_id, "song_task": "split-drums"}
            threading.Thread(target=run_drum_split_job, args=(job_id, song_id), daemon=True).start()
            self.send_json({"job_id": job_id})
            return

        if parsed.path.startswith("/api/library/") and parsed.path.endswith("/clean-vocals"):
            song_id = parsed.path.split("/")[3]
            if not SONG_ID_RE.match(song_id) or not get_song(song_id):
                self.send_json({"error": "Song not found in library"}, 404)
                return
            if not roformer_cli():
                self.send_json({"error": "Cleaner vocals needs the optional extra tool. Close Stems Studio and run the "
                                         "installer again, and say yes to cleaner vocals."}, 501)
                return
            busy = busy_job_for(song_id)
            if busy:
                if busy.get("song_task") == "clean-vocals":
                    self.send_json({"job_id": busy["id"]})
                else:
                    self.send_json({"error": "This song is being worked on. Wait for that to finish."}, 409)
                return
            job_id = str(uuid.uuid4())[:8]
            JOBS[job_id] = {"id": job_id, "status": "processing", "progress": 2, "message": "Starting...", "stems": [],
                            "song_busy": song_id, "song_task": "clean-vocals"}
            threading.Thread(target=run_clean_vocals_job, args=(job_id, song_id), daemon=True).start()
            self.send_json({"job_id": job_id})
            return

        self.send_error(404, "Endpoint not found")

    def handle_delete(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path.startswith("/api/library/"):
            song_id = parsed.path.split("/")[3]
            if SONG_ID_RE.match(song_id) and delete_song(song_id):
                self.send_json({"deleted": song_id})
            else:
                self.send_json({"error": "Song not found in library"}, 404)
            return
        self.send_error(404, "Endpoint not found")

    def do_OPTIONS(self):
        self.send_response(204)
        self.end_headers()


class ThreadedServer(socketserver.ThreadingTCPServer):
    daemon_threads = True
    # On Windows SO_REUSEADDR lets a second program share a port that is already in use,
    # which silently hands requests to a stale copy. Take the port exclusively instead.
    allow_reuse_address = os.name != "nt"

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class Lifecycle:
    """Quits the engine when the app window goes away, but never in the middle of a separation."""
    CLOSE_GRACE_SECONDS = 4
    SILENCE_LIMIT_SECONDS = 150
    NEVER_OPENED_LIMIT_SECONDS = 90

    def __init__(self, httpd):
        self.httpd = httpd
        self.started = time.time()
        self.last_seen = None
        self.closing_at = None

    def beat(self):
        self.last_seen = time.time()
        self.closing_at = None

    def closing(self):
        self.closing_at = time.time()

    @staticmethod
    def busy():
        return any(job.get("status") == "processing" for job in list(JOBS.values()))

    def should_quit(self, now):
        if self.busy():
            return False
        if self.closing_at and now - self.closing_at > self.CLOSE_GRACE_SECONDS:
            return True
        if self.last_seen and now - self.last_seen > self.SILENCE_LIMIT_SECONDS:
            return True
        return self.last_seen is None and now - self.started > self.NEVER_OPENED_LIMIT_SECONDS

    def watch(self):
        while not self.should_quit(time.time()):
            time.sleep(1)
        self.httpd.shutdown()


LIFECYCLE = None


def create_server(preferred_port=PORT):
    """Bind the preferred port, or any free one if something else is using it."""
    last_error = None
    for port in (preferred_port, 0):
        try:
            return ThreadedServer(("127.0.0.1", port), StudioRequestHandler)
        except OSError as exc:
            last_error = exc
    raise last_error


def find_running_instance(port=PORT):
    """Return the URL of an up-to-date Stems Studio already running on this port, else None."""
    url = f"http://127.0.0.1:{port}"
    try:
        with urllib.request.urlopen(f"{url}/api/engine", timeout=2) as resp:
            info = json.loads(resp.read().decode("utf-8"))
        if info.get("app") == APP_NAME and info.get("version") == APP_VERSION:
            return url
    except Exception:
        pass
    return None


def serve(httpd, quit_with_window=True):
    """Serve until the app window closes (or forever, for development)."""
    global LIFECYCLE
    warm_up_device_info()
    updater.start_background_checks()
    if quit_with_window:
        LIFECYCLE = Lifecycle(httpd)
        threading.Thread(target=LIFECYCLE.watch, daemon=True).start()
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()


def start_server():
    """Development entry point: run in a terminal and keep going until Ctrl+C."""
    httpd = create_server()
    print(f"Stems Studio engine running at http://127.0.0.1:{httpd.server_address[1]}")
    serve(httpd, quit_with_window=False)


if __name__ == "__main__":
    start_server()
