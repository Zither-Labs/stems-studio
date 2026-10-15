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
APP_VERSION = 8
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


def read_settings():
    """settings.json in the data folder. A missing or broken file is an empty dict."""
    try:
        with open(SETTINGS_PATH, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_settings(updates):
    """Merge updates into settings.json. Other keys (the library folder, the voice type) stay."""
    data = read_settings()
    data.update(updates)
    os.makedirs(DATA_DIR, exist_ok=True)
    temporary = SETTINGS_PATH + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(data, handle, indent=2)
        handle.write("\n")
    os.replace(temporary, SETTINGS_PATH)


def library_folder_locked():
    """STEMS_STUDIO_LIBRARY, when set, chooses the folder and the in-app button leaves it alone."""
    return bool(os.environ.get("STEMS_STUDIO_LIBRARY", "").strip())


def chosen_library_dir():
    """The folder the user wants the song library in (for example a network drive), or None for the default.

    Either the STEMS_STUDIO_LIBRARY environment variable, or "library_dir" in settings.json
    (in the app's data folder, so each computer can choose its own).
    """
    wanted = os.environ.get("STEMS_STUDIO_LIBRARY")
    if not wanted:
        wanted = read_settings().get("library_dir")
    return os.path.expandvars(wanted).strip() if isinstance(wanted, str) and wanted.strip() else None


def bind_library_db():
    """Point the database at whatever folder the library is using right now."""
    global DB_PATH
    DB_PATH = os.path.join(OUTPUT_DIR, "library.db")


def use_library_dir(wanted):
    """Switch to the chosen folder if it can be written to. Returns an error string, or '' on success.

    On failure the library stays where it was.
    """
    global OUTPUT_DIR, LIBRARY_NOTE
    try:
        os.makedirs(wanted, exist_ok=True)
        probe = os.path.join(wanted, ".write-test")
        with open(probe, "w") as handle:
            handle.write("ok")
        os.remove(probe)
    except OSError as exc:
        return f"The library folder {wanted} cannot be reached ({exc.strerror or exc})."
    OUTPUT_DIR = wanted
    LIBRARY_NOTE = ""
    bind_library_db()
    return ""


def set_library_folder(wanted):
    """Remember a library folder and switch to it. Returns an error string, or ''."""
    if library_folder_locked():
        return "This computer's library folder is set by STEMS_STUDIO_LIBRARY."
    if any(job.get("status") == "processing" for job in list(JOBS.values())):
        return "Wait until the current song finishes, then change the folder."
    path = os.path.expandvars(os.path.expanduser(str(wanted or "").strip().strip('"')))
    stripped = path.rstrip("/\\")
    if stripped and not re.fullmatch(r"[A-Za-z]:", stripped):
        path = stripped
    if not path:
        return "Choose a folder."
    if not os.path.isabs(path):
        return "Use the full path, for example Z:\\Music\\Stems."
    error = use_library_dir(path)
    if error:
        return error + " The library stayed where it was."
    write_settings({"library_dir": path})
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    init_library()
    return ""


def browse_for_folder():
    """Open this computer's folder window. Returns the chosen path, or None if the person cancelled."""
    if os.name == "nt":
        script = (
            "Add-Type -AssemblyName System.Windows.Forms; "
            "$dialog = New-Object System.Windows.Forms.FolderBrowserDialog; "
            "$dialog.Description = 'Choose the folder that contains your Stems Studio songs'; "
            "$dialog.ShowNewFolderButton = $true; "
            "$owner = New-Object System.Windows.Forms.Form; "
            "$owner.TopMost = $true; "
            "$result = $dialog.ShowDialog($owner); "
            "$owner.Dispose(); "
            "if ($result -eq [System.Windows.Forms.DialogResult]::OK) { Write-Output $dialog.SelectedPath; exit 0 }; "
            "exit 1"
        )
        command = ["powershell", "-NoProfile", "-STA", "-Command", script]
    elif sys.platform == "darwin":
        command = ["osascript", "-e",
                   'POSIX path of (choose folder with prompt "Choose the folder that contains your Stems Studio songs")']
    else:
        zenity = shutil.which("zenity")
        if not zenity:
            raise Exception("Type the folder path. A folder window is not available on this computer.")
        command = [zenity, "--file-selection", "--directory",
                   "--title=Choose the folder that contains your Stems Studio songs"]
    result = subprocess.run(command, capture_output=True, text=True, **NO_WINDOW)
    if result.returncode != 0:
        return None
    path = (result.stdout or "").strip().strip('"').rstrip("/\\")
    return path or None


_wanted_library = chosen_library_dir()
if _wanted_library:
    _library_error = use_library_dir(_wanted_library)
    if _library_error:
        LIBRARY_NOTE = _library_error + " Using this computer's own library until it is back."

# Earlier versions kept the library inside the code folder; move it across once.
_LEGACY_OUTPUT_DIR = os.path.join(BASE_DIR, "separated_output")
if os.path.isdir(_LEGACY_OUTPUT_DIR) and not os.path.exists(OUTPUT_DIR):
    try:
        shutil.move(_LEGACY_OUTPUT_DIR, OUTPUT_DIR)
    except OSError:
        pass
os.makedirs(OUTPUT_DIR, exist_ok=True)

NO_WINDOW = {"creationflags": subprocess.CREATE_NO_WINDOW} if os.name == "nt" else {}


def current_build():
    """Which copy this process is. A newer launch must not keep talking to an older one.

    The number above stayed the same across real updates, so opening the app after an update
    found the still-running old engine and treated it as current.
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=BASE_DIR, capture_output=True, text=True, timeout=5,
            env=dict(os.environ, GIT_TERMINAL_PROMPT="0"), **NO_WINDOW,
        )
        sha = (result.stdout or "").strip()
        if result.returncode == 0 and sha:
            return sha
    except (OSError, subprocess.SubprocessError):
        pass
    return f"{APP_VERSION}-local"


APP_BUILD = current_build()


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
    """The command (a list) that runs the audio-separator tool, or None when 'cleaner vocals' is not installed.

    On Windows it runs the tool through the environment's own python.exe rather than the little
    audio-separator.exe that pip makes: that one is never digitally signed, and Windows' Smart App
    Control blocks unsigned programs, while python.exe (from python.org) is signed.
    """
    if os.name == "nt":
        python_exe = os.path.join(ROFORMER_VENV, "Scripts", "python.exe")
        package = os.path.join(ROFORMER_VENV, "Lib", "site-packages", "audio_separator")
        if os.path.isfile(python_exe) and os.path.isdir(package):
            return [python_exe, "-c", "import sys; from audio_separator.utils.cli import main; sys.exit(main())"]
        return None
    candidate = os.path.join(ROFORMER_VENV, "bin", "audio-separator")
    return [candidate] if os.path.isfile(candidate) else None


bind_library_db()
SONG_ID_RE = re.compile(r"^[0-9a-f]{8}$")
PITCH_LOCK = threading.Lock()
# What the beat/key listen is doing right now, so the page can draw a bar while it runs.
LISTEN_PROGRESS = {}
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
        # The folder a song lives in, by its readable name ("Audioslave - Like A Stone"). Older libraries
        # used the song's code (like d0d43c0c); those folders are renamed below.
        if "folder" not in [col["name"] for col in conn.execute("PRAGMA table_info(songs)")]:
            conn.execute("ALTER TABLE songs ADD COLUMN folder TEXT")
    tidy_folder_names()


def youtube_content_key(url):
    match = YOUTUBE_ID_RE.search(url)
    return "yt:" + (match.group(1) if match else url.strip())


def file_content_key(file_bytes):
    return "file:" + hashlib.sha256(file_bytes).hexdigest()


def row_dir(row):
    return os.path.join(OUTPUT_DIR, row["folder"] or row["id"])


def song_dir(song_id):
    """The folder of a saved song (a song still being made has its code as the folder name)."""
    try:
        with library_db() as conn:
            row = conn.execute("SELECT id, folder FROM songs WHERE id = ?", (song_id,)).fetchone()
    except sqlite3.Error:
        row = None
    return row_dir(row) if row else os.path.join(OUTPUT_DIR, song_id)


UNSAFE_NAME_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
RESERVED_NAMES = {"con", "prn", "aux", "nul", *(f"com{n}" for n in range(1, 10)), *(f"lpt{n}" for n in range(1, 10))}


def folder_name_for(text):
    """A name that is safe as a folder name on Windows, Mac and the NAS ("Would?" becomes "Would")."""
    name = UNSAFE_NAME_CHARS.sub("", text or "")
    name = re.sub(r"\s+", " ", name).strip()[:90].rstrip(". ")
    if not name or name.lower() in RESERVED_NAMES:
        name = (name + " song").strip()
    return name


def name_song_folder(song_id):
    """Give a saved song a readable folder name. If anything goes wrong the old name just stays."""
    try:
        with library_db() as conn:
            row = conn.execute("SELECT * FROM songs WHERE id = ?", (song_id,)).fetchone()
        if not row:
            return
        current = row_dir(row)
        if not os.path.isdir(current):
            return
        base = folder_name_for(display_title(row))
        name, number = base, 2
        while name != (row["folder"] or row["id"]) and os.path.exists(os.path.join(OUTPUT_DIR, name)):
            name, number = f"{base} ({number})", number + 1
        if name == (row["folder"] or row["id"]):
            return
        os.rename(current, os.path.join(OUTPUT_DIR, name))
        with library_db() as conn:
            conn.execute("UPDATE songs SET folder = ? WHERE id = ?", (name, song_id))
    except Exception:
        traceback.print_exc()


def tidy_folder_names():
    """Rename old code-named song folders (once)."""
    with library_db() as conn:
        pending = [r["id"] for r in conn.execute("SELECT id FROM songs WHERE folder IS NULL OR folder = ''")]
    for song_id in pending:
        name_song_folder(song_id)


# "05 - Like A Stone", "05. Like A Stone", "Track 5 - Like A Stone", "05 Like A Stone": the number is dropped.
TRACK_NUMBER_RE = re.compile(r"^\s*(?:(?:track\s*)?\d{1,3}\s*[-._)]\s*|0\d\s+(?=\D))", re.IGNORECASE)


def without_track_number(text):
    text = (text or "").strip()
    return TRACK_NUMBER_RE.sub("", text, count=1).strip() or text


def display_title(row):
    """What the library shows: 'Artist - Track name', with no track number. Uses the file's tags when known."""
    title = without_track_number(row["title"])
    try:
        with open(os.path.join(row_dir(row), "meta.json"), "r", encoding="utf-8") as handle:
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
    folder = row_dir(row)
    present = stems_files_exist(row["id"], stems, folder)
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
        "drums_can_split": present and any(s["id"] == "drums" for s in stems)
                           and os.path.isfile(os.path.join(folder, "drums.wav")),
        "vocals_can_clean": present and not row["preset"].endswith(CLEAN_VOCALS_SUFFIX)
                            and not os.path.isfile(os.path.join(folder, CLEANED_VOCALS_MARKER)),
        "vocals_can_undo": present and clean_backups(folder) is not None,
        "missing": not present,
    }


def stems_files_exist(song_id, stems, folder=None):
    folder = folder or song_dir(song_id)
    return bool(stems) and all(
        os.path.isfile(os.path.join(folder, os.path.basename(s["url"]))) for s in stems
    )


def find_cached_song(content_key, model, preset):
    """Return the saved song for this exact audio + model, or None.

    A song whose files are missing stays in the library. It is not treated as a finished copy,
    so separating that recording again can replace it once the new files exist.
    """
    with library_db() as conn:
        row = conn.execute(
            "SELECT * FROM songs WHERE content_key = ? AND model = ? AND preset = ?",
            (content_key, model, preset),
        ).fetchone()
    if not row:
        return None
    stems = json.loads(row["stems_json"])
    if not stems_files_exist(row["id"], stems, row_dir(row)):
        return None
    return {"id": row["id"], "title": display_title(row), "stems": stems}


def save_song(song_id, title, source_type, source_label, content_key, model, preset, stems):
    size = 0
    for s in stems:
        path = os.path.join(song_dir(song_id), os.path.basename(s["url"]))
        if os.path.isfile(path):
            size += os.path.getsize(path)
    with library_db() as conn:
        # The new files are already written. Replace an older row for this same recording
        # (for example one whose files could not be opened) instead of keeping both.
        conn.execute(
            "DELETE FROM songs WHERE content_key = ? AND model = ? AND preset = ? AND id != ?",
            (content_key, model, preset, song_id),
        )
        conn.execute(
            """INSERT OR REPLACE INTO songs
               (id, title, source_type, source_label, content_key, model, preset,
                created_at, stems_json, size_bytes)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (song_id, title, source_type, source_label, content_key, model, preset,
             time.time(), json.dumps(stems), size),
        )


def list_songs():
    with library_db() as conn:
        rows = conn.execute("SELECT * FROM songs ORDER BY created_at DESC").fetchall()
    return [row_to_summary(row) for row in rows]


def get_song(song_id):
    with library_db() as conn:
        row = conn.execute("SELECT * FROM songs WHERE id = ?", (song_id,)).fetchone()
    if not row:
        return None
    stems = json.loads(row["stems_json"])
    if not stems_files_exist(song_id, stems, row_dir(row)):
        return None
    summary = row_to_summary(row)
    summary["stems"] = stems
    return summary


def delete_song(song_id):
    folder = song_dir(song_id)
    with library_db() as conn:
        deleted = conn.execute("DELETE FROM songs WHERE id = ?", (song_id,)).rowcount
    shutil.rmtree(folder, ignore_errors=True)
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
PRACTICE_NAME = "practice.json"                  # coach scores and the lyrics timing nudge, kept with the song
VOICE_TYPES = ("bass", "baritone", "tenor", "alto", "mezzo", "soprano")


def backup_name(stem_id):
    return f"{stem_id}-before-clean.wav"


def keep_backup(folder, stem_id, src_path):
    """Copy a stem aside the first time it is cleaned. A later clean leaves that copy alone."""
    name = backup_name(stem_id)
    dest = os.path.join(folder, name)
    if not os.path.isfile(dest):
        shutil.copy2(src_path, dest)
    return name


def clean_backups(folder):
    """The marker written by Clean vocals, when it names a vocal backup that is still on disk."""
    marker_path = os.path.join(folder, CLEANED_VOCALS_MARKER)
    if not os.path.isfile(marker_path):
        return None
    try:
        with open(marker_path, "r", encoding="utf-8") as handle:
            marker = json.load(handle)
    except (OSError, ValueError):
        return None
    backups = marker.get("backups") if isinstance(marker, dict) else None
    if not isinstance(backups, dict) or not backups.get("vocals"):
        return None
    vocals = os.path.join(folder, os.path.basename(str(backups["vocals"])))
    if not os.path.isfile(vocals):
        return None
    return marker


def restore_clean_backups(folder):
    """Put back the stems from before the first clean. The backup files stay, so this can be done again."""
    marker = clean_backups(folder)
    if not marker:
        raise Exception("This song has no saved copy of the vocal from before cleaning.")
    for stem_id, name in marker["backups"].items():
        if not isinstance(stem_id, str) or not re.fullmatch(r"[a-z0-9_]+", stem_id):
            continue
        src = os.path.join(folder, os.path.basename(str(name)))
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(folder, stem_id + ".wav"))
    os.remove(os.path.join(folder, CLEANED_VOCALS_MARKER))


def sanitize_history(value):
    if not isinstance(value, list):
        return []
    cleaned = []
    for entry in value[-20:]:
        if not isinstance(entry, dict):
            continue
        try:
            score = int(entry.get("score"))
        except (TypeError, ValueError):
            continue
        level = entry.get("level") if entry.get("level") in ("beginner", "medium", "advanced") else "beginner"
        try:
            date = int(entry.get("date"))
        except (TypeError, ValueError):
            date = int(time.time() * 1000)
        cleaned.append({"date": date, "score": max(0, min(100, score)), "level": level})
    return cleaned


def sanitize_offset(value):
    try:
        offset = float(value)
    except (TypeError, ValueError):
        return 0
    if offset != offset:
        return 0
    return max(-30.0, min(30.0, round(offset, 1)))


def read_practice(song_id):
    """Coach scores and the lyrics nudge for one song. None when that song has no folder."""
    folder = song_dir(song_id)
    if not os.path.isdir(folder):
        return None
    path = os.path.join(folder, PRACTICE_NAME)
    if not os.path.isfile(path):
        return {"coach_history": [], "lyrics_offset": 0, "stored": False}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError):
        return {"coach_history": [], "lyrics_offset": 0, "stored": False}
    if not isinstance(data, dict):
        data = {}
    return {
        "coach_history": sanitize_history(data.get("coach_history")),
        "lyrics_offset": sanitize_offset(data.get("lyrics_offset")),
        "stored": True,
    }


def write_practice(song_id, payload):
    folder = song_dir(song_id)
    if not os.path.isdir(folder) or not isinstance(payload, dict):
        return False
    data = {
        "coach_history": sanitize_history(payload.get("coach_history")),
        "lyrics_offset": sanitize_offset(payload.get("lyrics_offset")),
    }
    path = os.path.join(folder, PRACTICE_NAME)
    temporary = path + ".tmp"
    with open(temporary, "w", encoding="utf-8") as handle:
        json.dump(data, handle)
        handle.write("\n")
    os.replace(temporary, path)
    return True


def current_voice_type():
    value = read_settings().get("voice_type")
    return value if value in VOICE_TYPES else None


def set_voice_type(value):
    if value not in VOICE_TYPES:
        return False
    write_settings({"voice_type": value})
    return True


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


def note_listen(song_id, percent, message, running=True):
    """Remember the latest listen stage. The page polls this; it does not wait on the listen itself."""
    LISTEN_PROGRESS[song_id] = {
        "progress": max(0, min(100, int(percent))),
        "message": message,
        "running": bool(running),
    }


def prepare_song_listen(song_id, folder, on_progress=None):
    """Read the vocal, the beat, the key and the bass, and keep the result next to the song.

    A later chord sheet only has to line the chords up against that saved result. Doing this
    while the stems are first made means opening the song does not start the long listen again.
    The vocal pitch is saved too, so the highway's later request matches the cache.
    """
    def report(percent, message, running=True):
        note_listen(song_id, percent, message, running and percent < 100)
        if on_progress is not None:
            on_progress(max(0, min(100, int(percent))), message)

    try:
        music_analysis = separator_module("music_analysis")
    except ImportError:
        note_listen(song_id, 100, "Beat and key need the extras.", running=False)
        raise
    try:
        with PITCH_LOCK:
            vocal_midi = None
            vocals = os.path.join(folder, "vocals.wav")
            pitch_path = os.path.join(folder, "vocals.pitch.json")
            analysis_path = os.path.join(folder, "analysis.json")
            if os.path.isfile(vocals):
                try:
                    pitch_track = separator_module("pitch_track")
                    saved_pitch = pitch_track.load_if_fresh(vocals, pitch_path)
                    if saved_pitch is not None:
                        vocal_midi = saved_pitch["midi"]
                    else:
                        report(2, "Reading the vocal...")
                        vocal_midi = pitch_track.cached_analysis(vocals, pitch_path)["midi"]
                except Exception:
                    traceback.print_exc()

            # The bass line drawn on the highway, timed to 16 ms. Chord changes follow it.
            bass_line = None
            bass_wav = os.path.join(folder, "bass.wav")
            if os.path.isfile(bass_wav):
                try:
                    pitch_track = separator_module("pitch_track")
                    bass_pitch_path = os.path.join(folder, "bass.pitch.json")
                    saved_bass = pitch_track.load_if_fresh(bass_wav, bass_pitch_path)
                    if saved_bass is None:
                        report(7, "Reading the bass line...")
                        saved_bass = pitch_track.cached_analysis(bass_wav, bass_pitch_path)
                    bass_line = {key: saved_bass.get(key)
                                 for key in ("t0", "dt", "midi", "bass_method", "source_mtime")}
                except Exception:
                    traceback.print_exc()

            saved = music_analysis.load_if_fresh(folder, analysis_path, vocal_midi, bass_line)
            if saved is not None:
                # Already heard this song. Do not flash the bar for a result that is sitting on disk.
                note_listen(song_id, 100, "Beat and key are ready.", running=False)
                return saved

            def analysis_progress(percent, message):
                report(12 + percent * 0.87, message)

            result = music_analysis.cached_analysis(
                folder, analysis_path, vocal_midi, progress=analysis_progress, bass_line=bass_line)
            report(100, "Beat and key are ready.", running=False)
            return result
    except Exception:
        traceback.print_exc()
        report(100, "Could not read the beat.", running=False)
        return None


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
    folder = song_dir(song_id)
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


CHORD_SHEET_NAME = "chord-sheet.txt"
KARALYR_CACHE_NAME = "karalyr-chords.json"
PUBLISHED_CACHE_NAME = "published-chords.json"
PUBLISHED_CACHE_SECONDS = 7 * 24 * 3600


def song_chord_query(song_id):
    """YouTube id and artist/title, so a published chord chart can be looked up."""
    youtube_id = None
    library_title = None
    try:
        with library_db() as conn:
            row = conn.execute(
                "SELECT content_key, source_label, title FROM songs WHERE id = ?", (song_id,)
            ).fetchone()
        if row:
            library_title = row["title"]
            key = row["content_key"] or ""
            rest = key[3:] if key.startswith("yt:") else ""
            if re.fullmatch(r"[A-Za-z0-9_-]{11}", rest):
                youtube_id = rest
            if not youtube_id and row["source_label"]:
                match = YOUTUBE_ID_RE.search(row["source_label"])
                if match:
                    youtube_id = match.group(1)
    except sqlite3.Error:
        pass
    artist = title = None
    try:
        with open(os.path.join(song_dir(song_id), "meta.json"), "r", encoding="utf-8") as handle:
            meta = json.load(handle)
        artist = str(meta.get("artist") or "").strip() or None
        title = str(meta.get("title") or "").strip() or None
    except (OSError, ValueError):
        pass
    lyrics = separator_module("lyrics")
    if title:
        title = lyrics._clean_title(title)
    if not title and library_title:
        artist, title = lyrics.guess_artist_title(library_title)
    elif title and not artist and library_title:
        guessed_artist, _guessed_title = lyrics.guess_artist_title(library_title)
        artist = guessed_artist
    return youtube_id, artist, title


def load_chord_sheet(folder):
    try:
        with open(os.path.join(folder, CHORD_SHEET_NAME), "r", encoding="utf-8") as handle:
            return handle.read()
    except OSError:
        return ""


def save_chord_sheet(folder, text):
    path = os.path.join(folder, CHORD_SHEET_NAME)
    text = (text or "").strip()
    if not text:
        try:
            os.remove(path)
        except OSError:
            pass
        return
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        handle.write(text + "\n")
    os.replace(tmp, path)


def cached_karalyr(folder, youtube_id, artist, title):
    """Karalyr's timed chords, remembered with the song so the lookup happens once."""
    path = os.path.join(folder, KARALYR_CACHE_NAME)
    identity = {"youtube_id": youtube_id or "", "artist": artist or "", "title": title or ""}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            saved = json.load(handle)
        if all(saved.get(key) == value for key, value in identity.items()):
            return saved.get("chords") or []
    except (OSError, ValueError):
        pass
    chords = separator_module("chord_pass").fetch_karalyr(youtube_id, artist, title)
    write_json_file(path, {**identity, "chords": chords})
    return chords


def cached_published_chart(folder, artist, title):
    """A published chord chart for this song, remembered so the lookup happens once a week."""
    path = os.path.join(folder, PUBLISHED_CACHE_NAME)
    identity = {"artist": artist or "", "title": title or ""}
    try:
        with open(path, "r", encoding="utf-8") as handle:
            saved = json.load(handle)
        fresh = time.time() - float(saved.get("fetched_at") or 0) < PUBLISHED_CACHE_SECONDS
        if fresh and saved.get("artist") == identity["artist"] and saved.get("title") == identity["title"]:
            return saved
    except (OSError, ValueError, TypeError):
        pass
    if not identity["title"]:
        return None
    found = separator_module("chord_pass").fetch_jamming(identity["artist"], identity["title"])
    payload = {
        **identity,
        "fetched_at": time.time(),
        "source": "startjamming",
        "chords": (found or {}).get("chords") or [],
        "flats": bool((found or {}).get("flats")),
        "label": (found or {}).get("label") or "",
        "url": (found or {}).get("url") or "",
    }
    write_json_file(path, payload)
    return payload


def guessed_chords(song_id, folder, guesser):
    """The chords one of the outside guessers hears (Chordino, madmom, autochord or BTC).

    Returns (chords, note). The chords are None when that guesser is not installed or failed,
    so the app's own guess is drawn instead.
    """
    guessers = separator_module("chord_guessers")
    label = guessers.LABELS.get(guesser, guesser)
    if not guessers.ready(guesser):
        return None, (f"{label} is not installed yet, so these are Stems Studio's own chords. "
                      "Run Install again and answer Y to \"more chord guessers\".")

    def progress(percent, message):
        note_listen(song_id, percent, message or f"{label} is listening...", percent < 100)

    try:
        segments = guessers.guess(folder, guesser, progress)
    except Exception as exc:
        traceback.print_exc()
        note_listen(song_id, 100, f"{label} could not read this song.", False)
        return None, f"{label} could not read this song ({exc}), so these are Stems Studio's own chords."
    note_listen(song_id, 100, "Chords are ready.", False)
    chords = guessers.tidy(segments)
    if not chords:
        return None, f"{label} heard no chords in this song, so these are Stems Studio's own chords."
    return chords, f"Showing {len(chords)} chords guessed by {label}. Nothing here is checked against the bass."


def chords_for_song(song_id, folder, audio, guesser="app"):
    """First pass is a published chart (or a pasted sheet). Second pass is the app, kept only when the bass agrees.

    With another guesser chosen, its chords are drawn as it heard them. A pasted sheet still comes first.
    """
    chord_pass = separator_module("chord_pass")
    sheet = load_chord_sheet(folder)
    guesser_note = ""
    if guesser != "app" and not sheet.strip():
        chords, guesser_note = guessed_chords(song_id, folder, guesser)
        if chords:
            return {"chords": chords, "sheet": sheet, "note": guesser_note, "chord_from": guesser}
    runs = audio.get("bass_runs") or []
    app_chords = audio.get("chords") or []
    key = audio.get("key") or {}
    try:
        key_flats = bool(key) and separator_module("music_analysis").uses_flats(
            int(key.get("tonic") or 0), key.get("mode") or "major")
    except (TypeError, ValueError):
        key_flats = False

    kept = []
    chart_label = ""
    if sheet.strip():
        sections, flats = chord_pass.parse_sections(sheet)
        if len(sections) >= 2:
            # Verse and chorus can repeat for as long as the bass stays on those chords.
            kept = chord_pass.align_sections(sections, runs, flats, "sheet")
        else:
            external = [chord for section in sections for chord in section["chords"]]
            kept = chord_pass.from_chart(external, runs, False, "sheet", flats)
    else:
        youtube_id, artist, title = song_chord_query(song_id)
        if title:
            try:
                chart = cached_published_chart(folder, artist, title)
            except Exception:
                traceback.print_exc()
                chart = None
            if chart and chart.get("chords"):
                kept = chord_pass.from_chart(chart["chords"], runs, False, "chart", chart.get("flats"))
                if kept:
                    chart_label = chart.get("label") or ""
        if not kept and (youtube_id or title):
            try:
                external = cached_karalyr(folder, youtube_id, artist, title)
            except Exception:
                traceback.print_exc()
                external = []
            kept = chord_pass.from_chart(external, runs, True, "karalyr", key_flats)
    chords = chord_pass.add_app_chords(app_chords, runs, kept)
    # A chart that only caught a few bars used to leave the ribbon blank. The app's own
    # guess is already in the saved listen, so it can be drawn without reading the song again.
    chords, app_only = chord_pass.prefer_visible_line(app_chords, chords)
    sheet_used = any(chord.get("source") == "sheet" for chord in chords)
    chart_used = any(chord.get("source") == "chart" for chord in chords)
    karalyr_used = any(chord.get("source") == "karalyr" for chord in chords)
    chord_from = "sheet" if sheet_used else "chart" if chart_used else "karalyr" if karalyr_used else "app" if chords else None
    if app_only:
        note = "Chord names are along the top of the highway. They are the app's guess: no published chart matched this song."
    else:
        note = chord_pass.explain(sheet, sheet_used, chart_used, karalyr_used, len(chords), chart_label)
    if guesser_note:
        note = guesser_note
    elif guesser != "app" and sheet_used:
        note += " Your sheet comes before the chord guesser. Clear it to see what the guesser hears."
    return {
        "chords": chords,
        "sheet": sheet,
        "note": note,
        "chord_from": chord_from,
    }


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
    cmd = [*cli, audio_file, "-m", model, "--model_file_dir", models_dir,
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
    Copies from before the first clean are kept, so My Library can put them back.
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
        # Keep the pre-clean copies. A second clean does not overwrite them, so Undo returns
        # the vocal from before the first clean.
        backups = {"vocals": keep_backup(folder, "vocals", files["vocals"])}
        if home_id:
            backups[home_id] = keep_backup(folder, home_id, files[home_id])
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
            json.dump({"model": ROFORMER_MODEL, "leftover_went_to": home_id, "backups": backups}, handle)
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


def run_undo_clean_vocals_job(job_id, song_id):
    """Put back the vocal (and the stem that received the leftover) from before the first clean."""
    job = JOBS[job_id]
    folder = song_dir(song_id)
    try:
        song = get_song(song_id)
        if not song:
            raise Exception("Song not found in the library.")
        job["message"] = "Putting the old vocal back..."
        job["progress"] = 40
        restore_clean_backups(folder)
        stems = song["stems"]
        empty = find_empty_stems(folder, [os.path.basename(s["url"]) for s in stems])
        for s in stems:
            s["empty"] = os.path.basename(s["url"]) in empty
        update_song_stems(song_id, stems)
        job["stems"] = stems
        job["title"] = song["title"]
        job["progress"] = 100
        job["status"] = "completed"
        job["message"] = "Old vocal restored."
    except Exception as e:
        traceback.print_exc()
        job["status"] = "error"
        job["error"] = str(e)
        job["message"] = f"Error: {e}"


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
        # Leave the last stretch of the bar for reading the beat, the key and the bass.
        progress_base, progress_span = 28, 0.50      # where Demucs' progress bar starts and how far it goes
        if clean_vocals:
            job["message"] = "Making a cleaner vocal (the first time, a 600 MB model is downloaded)..."
            job["progress"] = 12
            roformer_vocals, demucs_input = run_roformer(audio_file, job_dir, job)
            progress_base, progress_span = 42, 0.36

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
        job["progress"] = 80

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
            job["progress"] = 82
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
            job["progress"] = 82
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
        job["progress"] = 84
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
            name_song_folder(job_id)

        # The beat, the key and the bass are read now, on this same bar, so a chord sheet
        # later only has to line up against a result that is already saved.
        def listen_progress(percent, message):
            job["progress"] = 84 + int(max(0, min(100, percent)) * 15 / 100)
            job["message"] = message

        try:
            prepare_song_listen(job_id, song_dir(job_id), listen_progress)
        except Exception:
            traceback.print_exc()          # the song is still usable if the listen cannot run

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
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(json.dumps(payload).encode("utf-8"))

    def local_request(self):
        """The app's own page. Another website must not be able to change the library or the settings."""
        origin = self.headers.get("Origin")
        if not origin:
            return True
        port = self.server.server_address[1]
        return origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")

    def read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length < 0 or length > 256 * 1024:
            raise ValueError("too large")
        raw = self.rfile.read(length).decode("utf-8") if length else ""
        if not raw.strip():
            return {}
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("expected an object")
        return data

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

        elif parsed.path == "/api/preferences":
            self.send_json({"voice_type": current_voice_type()})
            return

        elif parsed.path == "/api/library":
            self.send_json({"songs": list_songs(), "folder": OUTPUT_DIR, "note": LIBRARY_NOTE,
                            "folder_locked": library_folder_locked()})
            return

        elif parsed.path.startswith("/api/library/"):
            parts = [part for part in parsed.path.split("/") if part]
            song_id = parts[2] if len(parts) >= 3 else ""
            if len(parts) == 4 and parts[3] == "practice" and SONG_ID_RE.match(song_id):
                practice = read_practice(song_id)
                if practice is None:
                    self.send_json({"error": "Song not found in library"}, 404)
                else:
                    self.send_json(practice)
                return
            song = get_song(song_id) if SONG_ID_RE.match(song_id) else None
            if song:
                self.send_json(song)
                return
            if SONG_ID_RE.match(song_id):
                with library_db() as conn:
                    row = conn.execute("SELECT id FROM songs WHERE id = ?", (song_id,)).fetchone()
                if row:
                    self.send_json({"error": "The files for this song could not be opened.", "missing": True}, 409)
                    return
            self.send_json({"error": "Song not found in library"}, 404)
            return

        elif parsed.path == "/api/engine":
            dev_info = peek_device_info()
            if dev_info is None:
                dev_info = {"device": "unknown", "device_name": "", "cuda_available": False, "pending": True}
            self.send_json(dict(dev_info, library=True, app=APP_NAME, version=APP_BUILD,
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
            wav_path = os.path.join(song_dir(song_id), stem + ".wav")
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
                    result = module.cached_notes(wav_path, os.path.join(song_dir(song_id), stem + ".notes.json"))
                    self.send_json({"notes": result["notes"]})
                    return
                result = module.cached_analysis(wav_path, os.path.join(song_dir(song_id), stem + ".pitch.json"))
            payload = {"t0": result["t0"], "dt": result["dt"], "midi": result["midi"]}
            for key in ("rough_midi", "rough_auto", "unpitched_loud"):   # growls and screams, when there are any
                if key in result:
                    payload[key] = result[key]
            self.send_json(payload)
            return
        elif parsed.path.startswith("/api/hits/"):
            # When the drums hit (kick, snare, hi-hat...), for the drum lane of the highway.
            song_id = parsed.path.split("/")[3]
            folder = song_dir(song_id)
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

        elif parsed.path.startswith("/api/analysis/") and parsed.path.endswith("/progress"):
            parts = [part for part in parsed.path.split("/") if part]
            song_id = parts[2] if len(parts) > 2 else ""
            if not SONG_ID_RE.match(song_id):
                self.send_json({"error": "Song not found"}, 404)
                return
            self.send_json(LISTEN_PROGRESS.get(song_id) or {"progress": 0, "message": "", "running": False})
            return

        elif parsed.path.startswith("/api/analysis/"):
            # Key and chords of a song, found from its separated stems.
            song_id = parsed.path.split("/")[3]
            folder = song_dir(song_id)
            if not SONG_ID_RE.match(song_id) or not os.path.isdir(folder):
                self.send_json({"error": "Song not found"}, 404)
                return
            try:
                result = prepare_song_listen(song_id, folder)
            except ImportError as exc:
                self.send_json({"error": f"Key finder is not installed: {exc}"}, 501)
                return
            except Exception:
                traceback.print_exc()
                self.send_json({"error": "Could not read the beat for this song."}, 500)
                return
            if not result:
                self.send_json({"error": "Could not read the beat for this song."}, 500)
                return
            guessers = separator_module("chord_guessers")
            guesser = urllib.parse.parse_qs(parsed.query).get("guesser", ["app"])[0]
            if guesser not in guessers.LABELS:
                guesser = "app"
            passed = chords_for_song(song_id, folder, result, guesser)
            self.send_json({
                "guesser": guesser,
                "guessers": guessers.listing(),
                "key": result.get("key"),
                "chords": passed["chords"],
                "tuning_cents": result.get("tuning_cents"),
                "sources": result.get("sources"),
                "sheet": passed["sheet"],
                "note": passed["note"],
                "chord_from": passed["chord_from"],
                "meter": result.get("meter"),
            })
            return

        elif parsed.path.startswith("/api/lyrics/"):
            parts = parsed.path.split("/")
            song_id = parts[3] if len(parts) > 3 else ""
            if not SONG_ID_RE.match(song_id) or not os.path.isdir(song_dir(song_id)):
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
                folder = song_dir(song_id)
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
                file_path = os.path.join(song_dir(job_id), filename)

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

        if parsed.path.startswith("/api/analysis/") and parsed.path.endswith("/sheet"):
            if not self.local_request():
                self.send_json({"error": "Not allowed"}, 403)
                return
            parts = [part for part in parsed.path.split("/") if part]
            song_id = parts[2] if len(parts) > 2 else ""
            folder = song_dir(song_id)
            if not SONG_ID_RE.match(song_id) or not os.path.isdir(folder):
                self.send_json({"error": "Song not found"}, 404)
                return
            try:
                data = self.read_json_body()
            except (ValueError, UnicodeError):
                self.send_json({"error": "Could not read that."}, 400)
                return
            text = str(data.get("sheet") or "")
            if len(text) > 8000:
                self.send_json({"error": "That sheet is too long."}, 400)
                return
            save_chord_sheet(folder, text)
            self.send_json({"ok": True})
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
                result = updater.apply()
                if result.get("ok"):
                    result["restart"] = True
                    result["message"] = "Updated. Reopening Stems Studio."
                self.send_json(result)
                if result.get("ok"):
                    schedule_restart()
            return

        if parsed.path in ("/api/preferences", "/api/library/folder", "/api/library/browse"):
            if not self.local_request():
                self.send_json({"error": "Not allowed"}, 403)
                return
            try:
                data = {} if parsed.path.endswith("/browse") else self.read_json_body()
            except (ValueError, UnicodeError):
                self.send_json({"error": "Could not read that."}, 400)
                return
            if parsed.path == "/api/preferences":
                if not set_voice_type(data.get("voice_type")):
                    self.send_json({"error": "Unknown voice type."}, 400)
                    return
                self.send_json({"voice_type": data.get("voice_type")})
                return
            if parsed.path == "/api/library/browse":
                try:
                    path = browse_for_folder()
                except Exception as exc:
                    self.send_json({"error": str(exc)}, 501)
                    return
                self.send_json({"cancelled": True} if not path else {"path": path})
                return
            error = set_library_folder(data.get("path"))
            if error:
                self.send_json({"error": error}, 400)
                return
            self.send_json({"folder": OUTPUT_DIR, "note": LIBRARY_NOTE, "folder_locked": library_folder_locked()})
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

        if parsed.path.startswith("/api/library/") and parsed.path.endswith("/practice"):
            song_id = parsed.path.split("/")[3]
            if not self.local_request():
                self.send_json({"error": "Not allowed"}, 403)
                return
            if not SONG_ID_RE.match(song_id):
                self.send_json({"error": "Song not found in library"}, 404)
                return
            try:
                data = self.read_json_body()
            except (ValueError, UnicodeError):
                self.send_json({"error": "Could not read that."}, 400)
                return
            if not write_practice(song_id, data):
                self.send_json({"error": "Song not found in library"}, 404)
                return
            self.send_json(read_practice(song_id))
            return

        if parsed.path.startswith("/api/library/") and parsed.path.endswith("/undo-clean-vocals"):
            song_id = parsed.path.split("/")[3]
            if not SONG_ID_RE.match(song_id) or not get_song(song_id):
                self.send_json({"error": "Song not found in library"}, 404)
                return
            if not clean_backups(song_dir(song_id)):
                self.send_json({"error": "This song has no saved copy of the vocal from before cleaning."}, 404)
                return
            busy = busy_job_for(song_id)
            if busy:
                if busy.get("song_task") == "undo-clean-vocals":
                    self.send_json({"job_id": busy["id"]})
                else:
                    self.send_json({"error": "This song is being worked on. Wait for that to finish."}, 409)
                return
            job_id = str(uuid.uuid4())[:8]
            JOBS[job_id] = {"id": job_id, "status": "processing", "progress": 2, "message": "Starting...", "stems": [],
                            "song_busy": song_id, "song_task": "undo-clean-vocals"}
            threading.Thread(target=run_undo_clean_vocals_job, args=(job_id, song_id), daemon=True).start()
            self.send_json({"job_id": job_id})
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
    # Longer than two of the page's 5-second heartbeats, so a second open window (or a page
    # that is reloading) can still claim the engine after another window closes.
    CLOSE_GRACE_SECONDS = 12
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

    def quit_reason(self, now):
        """Why the engine should stop now, or None while a window still needs it."""
        if self.busy():
            return None
        if self.closing_at and now - self.closing_at > self.CLOSE_GRACE_SECONDS:
            return "the app window was closed"
        if self.last_seen and now - self.last_seen > self.SILENCE_LIMIT_SECONDS:
            return f"no app window has checked in for {self.SILENCE_LIMIT_SECONDS} seconds"
        if self.last_seen is None and now - self.started > self.NEVER_OPENED_LIMIT_SECONDS:
            return "the app window never opened"
        return None

    def should_quit(self, now):
        return self.quit_reason(now) is not None

    def watch(self):
        while (reason := self.quit_reason(time.time())) is None:
            time.sleep(1)
        print(f"Stems Studio engine stopping: {reason}.", flush=True)
        self.httpd.shutdown()


LIFECYCLE = None


def create_server(preferred_port=PORT):
    """Bind the preferred port, or any free one if something else is using it.

    The preferred port is tried more than once: a restart can arrive while the previous
    engine is still letting go of it.
    """
    last_error = None
    for _ in range(25):
        try:
            return ThreadedServer(("127.0.0.1", preferred_port), StudioRequestHandler)
        except OSError as exc:
            last_error = exc
            time.sleep(0.3)
    try:
        return ThreadedServer(("127.0.0.1", 0), StudioRequestHandler)
    except OSError as exc:
        raise last_error or exc


def probe_instance(port=PORT):
    """The Stems Studio already listening on this port, or None. Includes its url."""
    url = f"http://127.0.0.1:{port}"
    try:
        with urllib.request.urlopen(f"{url}/api/engine", timeout=2) as resp:
            info = json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None
    if not isinstance(info, dict) or info.get("app") != APP_NAME:
        return None
    info["url"] = url
    return info


def same_build(reported, current=None):
    """True when a running engine is this same copy, so it is safe to reopen it."""
    if reported is None:
        return False
    return str(reported) == str(APP_BUILD if current is None else current)


def find_running_instance(port=PORT):
    """Return the URL of this same Stems Studio already running, else None.

    An older engine on the port is not reused: it would keep serving the previous code
    after an update had already been downloaded.
    """
    info = probe_instance(port)
    if info and same_build(info.get("version")):
        return info["url"]
    return None


def schedule_restart():
    """Leave this process, then start the app again so the downloaded code is what actually runs."""
    script = os.path.join(BASE_DIR, "app.py")
    helper = (
        "import sys, time, subprocess, urllib.request\n"
        f"url = 'http://127.0.0.1:{PORT}/api/engine'\n"
        "for _ in range(50):\n"
        "    try:\n"
        "        urllib.request.urlopen(url, timeout=0.4)\n"
        "        time.sleep(0.2)\n"
        "    except Exception:\n"
        "        break\n"
        "time.sleep(0.5)\n"
        "subprocess.Popen([sys.executable, sys.argv[1]], cwd=sys.argv[2])\n"
    )

    def go():
        time.sleep(0.6)
        subprocess.Popen(
            [sys.executable, "-c", helper, script, BASE_DIR],
            cwd=BASE_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **NO_WINDOW,
        )
        if LIFECYCLE is not None:
            LIFECYCLE.httpd.shutdown()

    threading.Thread(target=go, daemon=True).start()


def warm_up_pitch():
    """Load the pitch detector on this thread, before any request thread can.

    Opening a song and making stems both read pitch on a background thread. On Windows the
    detector's library crashes the whole engine if that thread is the first to load it, and the
    page then says it cannot reach 127.0.0.1:8099.
    """
    try:
        separator_module("pitch_track").warm_up()
    except Exception:
        traceback.print_exc()


def serve(httpd, quit_with_window=True):
    """Serve until the app window closes (or forever, for development)."""
    global LIFECYCLE
    warm_up_pitch()
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
