"""
Stems Studio - Unified Local Server & AI Separation Engine
Serves the web UI and provides /api/separate and /api/status endpoints.
Supports YouTube URLs and local FLAC / MP3 / WAV files.
Supports 4-stem and 6-stem (htdemucs_6s) models with Nepali Folk presets!
"""

import email.message
import email.parser
import http.server
import json
import os
import shutil
import socketserver
import subprocess
import sys
import threading
import time
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


def run_separation_job(job_id, source_type, source_val, model="htdemucs_6s", preset="nepali_folk"):
    job = JOBS[job_id]
    job_dir = os.path.join(OUTPUT_DIR, job_id)
    os.makedirs(job_dir, exist_ok=True)

    try:
        audio_file = None

        # Step 1: Acquire audio file
        if source_type == "youtube":
            job["message"] = "Downloading audio from YouTube..."
            job["progress"] = 15
            import yt_dlp
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
            job["title"] = os.path.splitext(os.path.basename(audio_file))[0]

        if not os.path.isfile(audio_file):
            raise Exception("Failed to prepare source audio file.")

        # Step 2: Run Demucs Separation
        job["message"] = f"Separating audio into stems using {model}..."
        job["progress"] = 35

        cmd = [
            sys.executable, "-m", "demucs.separate",
            "-n", model,
            "-o", job_dir,
            audio_file
        ]

        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)

        for line in process.stdout:
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
            raise Exception(f"Demucs separation process returned code {process.returncode}")

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

        job["stems"] = stems_result
        job["progress"] = 100
        job["status"] = "completed"
        job["message"] = "Stem separation complete!"

    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)
        job["message"] = f"Error: {e}"


class StudioRequestHandler(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=BASE_DIR, **kwargs)

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)

        if parsed.path == "/api/status":
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

                if os.path.isfile(file_path):
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

    def do_POST(self):
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

                JOBS[job_id] = {
                    "id": job_id,
                    "status": "processing",
                    "progress": 5,
                    "message": "Initializing job...",
                    "stems": []
                }

                t = threading.Thread(
                    target=run_separation_job,
                    args=(job_id, "youtube", youtube_url, model, preset),
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

                job_dir = os.path.join(OUTPUT_DIR, job_id)
                os.makedirs(job_dir, exist_ok=True)
                uploaded_path = os.path.join(job_dir, file_name)

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
                    args=(job_id, "file", uploaded_path, model, preset),
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


def start_server():
    server = socketserver.TCPServer(("", PORT), StudioRequestHandler)
    print(f"Stems Studio Server running at http://localhost:{PORT}")
    server.serve_forever()


if __name__ == "__main__":
    start_server()
