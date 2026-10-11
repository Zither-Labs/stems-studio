"""
Stems Studio - Unified Local Server & AI Separation Engine
Serves the web UI and provides /api/separate and /api/status endpoints.
Supports YouTube URLs and local FLAC / MP3 / WAV files.
Supports 4-stem and 6-stem (htdemucs_6s) models with Nepali Folk presets!
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
import socketserver
import sqlite3
import subprocess
import sys
import threading
import time
import traceback
import urllib.parse
import uuid

# Auto-configure bundled ffmpeg
try:
    import static_ffmpeg
    static_ffmpeg.add_paths()
except Exception:
    pass

PORT = 8099
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "separated_output")
os.makedirs(OUTPUT_DIR, exist_ok=True)

DB_PATH = os.path.join(OUTPUT_DIR, "library.db")
SONG_ID_RE = re.compile(r"^[0-9a-f]{8}$")
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
        "stem_count": len(stems),
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
    "drums": {"name": "Drums", "type": "drums", "desc": "Drums & Percussion"},
    "bass": {"name": "Bass", "type": "bass", "desc": "Bassline"},
    "other": {"name": "Instruments", "type": "other", "desc": "Accompaniment & Lead"}
}


_device_info_cache = None
_device_info_lock = threading.Lock()


def _detect_device_info():
    try:
        import torch
        if torch.cuda.is_available():
            dev_name = torch.cuda.get_device_name(0)
            vram = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
            return {
                "device": "cuda",
                "device_name": dev_name,
                "vram_gb": round(vram, 1),
                "cuda_available": True,
                "cuda_version": getattr(torch.version, "cuda", "12.6")
            }
    except Exception:
        pass
    return {
        "device": "cpu",
        "device_name": "CPU",
        "vram_gb": 0,
        "cuda_available": False,
        "cuda_version": None
    }


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

        cmd = [
            sys.executable, "-m", "demucs.separate",
            "-n", model,
            "-d", device_arg,
            "-o", job_dir,
            audio_file
        ]

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)

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
        if process.returncode != 0:
            tail = " | ".join(recent_output)
            if "No module named" in tail and "demucs" in tail:
                raise Exception("Demucs is not installed. Close the app and start it again from the shortcut to run first-time setup.")
            raise Exception(f"Demucs failed (code {process.returncode}): {tail}")

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

        # Pick mapping dictionary
        if preset == "nepali_folk":
            mapping = NEPALI_FOLK_STEM_MAP
        elif model == "htdemucs_6s":
            mapping = STANDARD_6S_STEM_MAP
        else:
            mapping = STANDARD_4S_STEM_MAP

        stems_result = []
        for sf in sorted(stem_files):
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
                      content_key, model, preset, stems_result)

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
        self.send_header("Access-Control-Allow-Origin", "*")
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

        if parsed.path == "/api/library":
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
            self.send_json(dict(dev_info, library=True))
            return

        elif parsed.path == "/api/status":
            query = urllib.parse.parse_qs(parsed.query)
            job_id = query.get("job_id", [""])[0]
            job = JOBS.get(job_id)

            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()

            if job:
                self.wfile.write(json.dumps(job).encode("utf-8"))
            else:
                self.wfile.write(json.dumps({"status": "not_found"}).encode("utf-8"))
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
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    with open(file_path, "rb") as f:
                        shutil.copyfileobj(f, self.wfile)
                    return

            self.send_error(404, "Stem file not found")
            return

        super().do_GET()

    def handle_post(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/api/separate":
            content_type = self.headers.get("Content-Type", "")
            job_id = str(uuid.uuid4())[:8]

            if "application/json" in content_type:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode("utf-8")
                data = json.loads(body)

                youtube_url = data.get("youtube_url", "").strip()
                model = data.get("model", "htdemucs_6s")
                preset = data.get("preset", "nepali_folk")

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
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(json.dumps({"job_id": job_id}).encode("utf-8"))
                return

            elif "multipart/form-data" in content_type:
                length = int(self.headers.get("Content-Length", 0))
                body_bytes = self.rfile.read(length)

                header_bytes = f"Content-Type: {content_type}\r\n\r\n".encode("utf-8")
                msg = email.parser.BytesParser().parsebytes(header_bytes + body_bytes)

                model = "htdemucs_6s"
                preset = "nepali_folk"
                file_bytes = None
                file_name = "uploaded_audio.wav"

                if msg.is_multipart():
                    for part in msg.get_payload():
                        cd = part.get("Content-Disposition", "")
                        if 'name="model"' in cd:
                            model = part.get_payload(decode=True).decode("utf-8").strip()
                        elif 'name="preset"' in cd:
                            preset = part.get_payload(decode=True).decode("utf-8").strip()
                        elif 'name="file"' in cd:
                            fname = part.get_filename()
                            if fname:
                                file_name = fname
                            file_bytes = part.get_payload(decode=True)

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
                self.send_header("Access-Control-Allow-Origin", "*")
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
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()


class ThreadedServer(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def start_server():
    warm_up_device_info()
    server = ThreadedServer(("127.0.0.1", PORT), StudioRequestHandler)
    print(f"Stems Studio Server running at http://localhost:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    start_server()
