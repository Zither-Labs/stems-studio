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

# Auto-configure bundled ffmpeg
try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception:
    pass

APP_NAME = "stems-studio"
APP_VERSION = 3
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
OUTPUT_DIR = os.path.join(DATA_DIR, "library")
os.makedirs(DATA_DIR, exist_ok=True)

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

DB_PATH = os.path.join(OUTPUT_DIR, "library.db")
SONG_ID_RE = re.compile(r"^[0-9a-f]{8}$")
PITCH_LOCK = threading.Lock()
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


def row_to_summary(row):
    stems = json.loads(row["stems_json"])
    return {
        "id": row["id"],
        "title": row["title"],
        "source_type": row["source_type"],
        "source_label": row["source_label"],
        "model": row["model"],
        "preset": row["preset"],
        "created_at": row["created_at"],
        "stem_count": sum(1 for s in stems if not s.get("empty")),
        "size_bytes": row["size_bytes"],
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
        return {"id": row["id"], "title": row["title"], "stems": stems}


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
    "vocals": {"name": "Vocals / स्वर", "type": "vocal", "desc": "Lead Vocals & Chorus"},
    "drums": {"name": "Madal & Percussion / मादल", "type": "drums", "desc": "Madal (Baya/Dahina), Tabla, Dholak"},
    "other": {"name": "Sarangi & Bansuri / सारङ्गी-बाँसुरी", "type": "other", "desc": "Folk Fiddle, Bamboo Flute, Lead"},
    "piano": {"name": "Harmonium & Keys / हार्मोनियम", "type": "piano", "desc": "Bellows Harmonium & Drone"},
    "guitar": {"name": "Acoustic Pluck / टुङ्ना-गितार", "type": "guitar", "desc": "Tungna, Sarod, Acoustic Guitar"},
    "bass": {"name": "Bass & Low-End / बास", "type": "bass", "desc": "Sub Bass & Low Frequencies"}
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

STEM_ORDER = ["vocals", "drums", "bass", "guitar", "guitar_lead", "guitar_rhythm", "piano", "other"]

VALID_MODELS = ("htdemucs", "htdemucs_6s")
VALID_PRESETS = ("standard", "nepali_folk")
GUITAR_SPLIT_SUFFIX = "+gsplit"


def clean_choices(model, preset, split_guitar=False):
    """Only accept known model / naming choices; anything else falls back to the defaults.

    The guitar split is remembered as a suffix on the naming choice, so a song made with it
    and the same song made without it are kept as two different library entries.
    """
    if model not in VALID_MODELS:
        model = "htdemucs_6s"
    if preset not in VALID_PRESETS:
        preset = "standard"
    if split_guitar and model == "htdemucs_6s":
        preset += GUITAR_SPLIT_SUFFIX
    return model, preset


def truthy(value):
    return str(value).strip().lower() in ("1", "true", "yes", "on")


# A stem counts as "nothing in it" when it is practically silent, or carries under 1% of the
# energy of all the stems together (about 20 dB quieter). Such stems are hidden in the mixer
# but kept on disk, so they can still be shown.
EMPTY_STEM_ABS_DB = -50.0
EMPTY_STEM_SHARE = 0.01


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
        empty = {
            name for name in stem_files
            if loudness_db[name] < EMPTY_STEM_ABS_DB or energy[name] / everything < EMPTY_STEM_SHARE
        }
        # Never hide so much that almost nothing is left.
        keep = sorted(stem_files, key=lambda n: energy[n], reverse=True)[:2]
        return empty - set(keep)
    except Exception:
        traceback.print_exc()
        return set()


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


def run_separation_job(job_id, source_type, source_val, model="htdemucs_6s", preset="nepali_folk",
                       content_key=None, source_label="", title=None):
    job = JOBS[job_id]
    job_dir = os.path.join(OUTPUT_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    try:
        audio_file = None
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
            audio_file = os.path.join(job_dir, "source_audio.wav")
        else:
            audio_file = source_val
            job["title"] = title or os.path.splitext(os.path.basename(audio_file))[0]

        if not os.path.isfile(audio_file):
            raise Exception("Failed to prepare source audio file.")

        # Step 2: Run Demucs Separation with GPU acceleration
        job["message"] = f"Running neural separation with {model} on {dev_info['device_name']}..."
        job["progress"] = 35

        def run_demucs(device):
            cmd = [
                cli_python(), "-m", "demucs.separate",
                "-n", model,
                "-d", device,
                "-o", job_dir,
                audio_file
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
                        job["progress"] = 35 + int(pct * 0.55)
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
            job["progress"] = 35
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

        audio_base = os.path.splitext(os.path.basename(audio_file))[0]
        stems_source_dir = os.path.join(job_dir, model, audio_base)

        if not os.path.isdir(stems_source_dir):
            for root, dirs, files in os.walk(job_dir):
                if any(f.endswith(".wav") for f in files) and root != job_dir:
                    stems_source_dir = root
                    break

        stem_files = [f for f in os.listdir(stems_source_dir) if f.endswith(".wav")]
        if not stem_files:
            raise Exception("No stem audio files were generated.")

        library_preset = preset   # what the library remembers (includes the guitar-split suffix)
        split_guitar = preset.endswith(GUITAR_SPLIT_SUFFIX)
        preset = preset[:-len(GUITAR_SPLIT_SUFFIX)] if split_guitar else preset

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

        # Pick mapping dictionary
        if preset == "nepali_folk":
            mapping = NEPALI_FOLK_STEM_MAP if model == "htdemucs_6s" else NEPALI_FOLK_4S_STEM_MAP
        elif model == "htdemucs_6s":
            mapping = STANDARD_6S_STEM_MAP
        else:
            mapping = STANDARD_4S_STEM_MAP

        mapping = dict(mapping, **GUITAR_SPLIT_MAP)
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

        elif parsed.path == "/api/library":
            self.send_json({"songs": list_songs()})
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
            self.send_json(dict(dev_info, library=True, app=APP_NAME, version=APP_VERSION))
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

        elif parsed.path.startswith("/api/pitch/"):
            # The sung pitch of a song's vocal stem, for the vocal highway.
            song_id = parsed.path.split("/")[3]
            wav_path = os.path.join(OUTPUT_DIR, song_id, "vocals.wav")
            if not SONG_ID_RE.match(song_id) or not os.path.isfile(wav_path):
                self.send_json({"error": "No vocal stem found for this song"}, 404)
                return
            try:
                sys.path.insert(0, os.path.join(BASE_DIR, "separator"))
                import pitch_track
            except ImportError as exc:
                self.send_json({"error": f"Pitch tracker is not installed: {exc}"}, 501)
                return
            with PITCH_LOCK:   # one analysis at a time; a second request waits and then reads the saved result
                result = pitch_track.cached_analysis(wav_path, os.path.join(OUTPUT_DIR, song_id, "vocals.pitch.json"))
            self.send_json({"t0": result["t0"], "dt": result["dt"], "midi": result["midi"]})
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

        if parsed.path == "/api/separate":
            content_type = self.headers.get("Content-Type", "")
            job_id = str(uuid.uuid4())[:8]

            if "application/json" in content_type:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8")
                data = json.loads(body)

                youtube_url = data.get("youtube_url", "").strip()
                model, preset = clean_choices(data.get("model"), data.get("preset"),
                                              truthy(data.get("guitar_split", False)))

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
                    args=(job_id, "youtube", youtube_url, model, preset, content_key, youtube_url),
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
                        elif 'name="file"' in cd:
                            fname = part.get_filename()
                            if fname:
                                file_name = fname
                            file_bytes = part.get_payload(decode=True)

                model, preset = clean_choices(model, preset, guitar_split)

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
                    args=(job_id, "file", uploaded_path, model, preset, content_key, original_name, title),
                    daemon=True
                )
                t.start()

                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(json.dumps({"job_id": job_id}).encode("utf-8"))
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
