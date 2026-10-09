"""
Stems Studio - AI Audio Stem Separator CLI
Uses Facebook Demucs (htdemucs) to split any song or YouTube URL into:
- vocals.wav
- drums.wav
- bass.wav
- other.wav

Output files can be dragged directly into Stems Studio!
"""

import argparse
import os
import shutil
import subprocess
import sys


def parse_args():
    parser = argparse.ArgumentParser(description="Split audio into stems for Stems Studio")
    parser.add_argument("input", nargs="?", help="Path to audio file (MP3/WAV/FLAC) or YouTube URL")
    parser.add_argument("--out", default="stems_output", help="Directory where stems will be saved")
    parser.add_argument("--model", default="htdemucs", help="Demucs model (htdemucs, htdemucs_ft, mdx_extra)")
    return parser.parse_args()


def download_youtube(url, output_dir):
    print(f"\n[1/3] Downloading audio from YouTube: {url}")
    try:
        import yt_dlp
    except ImportError:
        print("yt-dlp is required for YouTube URLs. Run: pip install yt-dlp")
        sys.exit(1)

    os.makedirs(output_dir, exist_ok=True)
    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(output_dir, '%(title)s.%(ext)s'),
        'postprocessors': [{
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'wav',
            'preferredquality': '192',
        }],
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        base, _ = os.path.splitext(filename)
        return f"{base}.wav"


def run_demucs(audio_path, output_dir, model="htdemucs"):
    print(f"\n[2/3] Separating stems with Demucs ({model})...")
    cmd = [
        sys.executable, "-m", "demucs.separate",
        "-n", model,
        "-o", output_dir,
        audio_path
    ]
    subprocess.check_call(cmd)


def organize_stems(audio_path, output_dir, model="htdemucs"):
    print("\n[3/3] Organizing stems...")
    base_name = os.path.splitext(os.path.basename(audio_path))[0]
    demucs_track_dir = os.path.join(output_dir, model, base_name)

    if not os.path.isdir(demucs_track_dir):
        print(f"Warning: Expected directory {demucs_track_dir} not found.")
        return

    final_dir = os.path.join(output_dir, base_name)
    os.makedirs(final_dir, exist_ok=True)

    stems = ["vocals.wav", "drums.wav", "bass.wav", "other.wav"]
    print(f"\nStem files ready in: {os.path.abspath(final_dir)}")
    for stem in stems:
        src = os.path.join(demucs_track_dir, stem)
        dst = os.path.join(final_dir, stem)
        if os.path.isfile(src):
            shutil.copy2(src, dst)
            print(f"  ✓ {stem}")


def main():
    args = parse_args()
    input_source = args.input

    if not input_source:
        print("=" * 60)
        print("  Stems Studio — AI Audio Stem Separator")
        print("=" * 60)
        input_source = input("\nEnter audio file path or YouTube URL: ").strip().strip('"')

    if not input_source:
        print("No input provided.")
        sys.exit(1)

    os.makedirs(args.out, exist_ok=True)

    if input_source.startswith("http://") or input_source.startswith("https://"):
        audio_file = download_youtube(input_source, args.out)
    else:
        audio_file = os.path.abspath(input_source)
        if not os.path.isfile(audio_file):
            print(f"Error: File not found: {audio_file}")
            sys.exit(1)

    run_demucs(audio_file, args.out, model=args.model)
    organize_stems(audio_file, args.out, model=args.model)

    print("\nDone! Drag these 4 stem files directly into Stems Studio.")


if __name__ == "__main__":
    main()
