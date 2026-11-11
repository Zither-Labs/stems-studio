#!/usr/bin/env python3
"""
Builds GitHub Release assets in dist/:
  1. Stamps version.json with the exact commit SHA and release tag.
  2. Creates dist/StemsStudio.zip (cross-platform package for Windows, macOS, and Linux,
     with executable permissions preserved on Install.command).
  3. Compiles dist/StemsStudio-Setup.exe on Windows if Inno Setup (ISCC.exe) is installed.
  4. Writes dist/RELEASE_NOTES.md for the GitHub Release page.
"""

import json
import os
import shutil
import stat
import subprocess
import time
import zipfile

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST_DIR = os.path.join(ROOT_DIR, "dist")

INCLUDED_FILES = [
    "app.py",
    "server.py",
    "updater.py",
    "version.json",
    "index.html",
    "manifest.json",
    "favicon.ico",
    "Install.bat",
    "Update.bat",
    "Install.command",
    "README.md",
    "INSTALL.md",
    "LICENSE",
]

INCLUDED_DIRS = [
    "assets",
    "css",
    "fonts",
    "js",
    "separator",
    "tools",
]


def get_commit_sha():
    sha = os.environ.get("GITHUB_SHA", "").strip()
    if sha:
        return sha
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT_DIR, capture_output=True, text=True, timeout=10
        )
        if res.returncode == 0 and res.stdout.strip():
            return res.stdout.strip()
    except Exception:
        pass
    return ""


def get_release_tag():
    tag = os.environ.get("GITHUB_REF_NAME", "").strip()
    if tag:
        return tag
    return "v1.0.0"


def update_version_json(sha, tag):
    vfile = os.path.join(ROOT_DIR, "version.json")
    payload = {
        "version": sha[:7] if sha else tag,
        "sha": sha,
        "tag": tag,
        "updated_at": int(time.time()),
    }
    with open(vfile, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)
        f.write("\n")


def add_file_to_zip(zf, abs_path, arc_path):
    st = os.stat(abs_path)
    mtime = time.localtime(st.st_mtime)[:6]
    zinfo = zipfile.ZipInfo(arc_path, date_time=mtime)
    zinfo.compress_type = zipfile.ZIP_DEFLATED
    if arc_path.endswith(".command") or arc_path.endswith(".sh") or arc_path.endswith(".py"):
        mode = stat.S_IFREG | 0o755
    else:
        mode = stat.S_IFREG | 0o644
    zinfo.external_attr = (mode & 0xFFFF) << 16
    with open(abs_path, "rb") as f:
        zf.writestr(zinfo, f.read())


def build_zip_archive():
    os.makedirs(DIST_DIR, exist_ok=True)
    zip_path = os.path.join(DIST_DIR, "StemsStudio.zip")
    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        sha = get_commit_sha()
        if sha:
            zf.comment = sha.encode("ascii")

        for rel in INCLUDED_FILES:
            abs_p = os.path.join(ROOT_DIR, rel)
            if os.path.isfile(abs_p):
                add_file_to_zip(zf, abs_p, f"StemsStudio/{rel}")

        for folder in INCLUDED_DIRS:
            folder_abs = os.path.join(ROOT_DIR, folder)
            if not os.path.isdir(folder_abs):
                continue
            for dirpath, dirnames, filenames in os.walk(folder_abs):
                dirnames[:] = [d for d in dirnames if d != "__pycache__" and not d.startswith(".")]
                for fn in sorted(filenames):
                    if fn.endswith((".pyc", ".pyo")):
                        continue
                    full_p = os.path.join(dirpath, fn)
                    rel_p = os.path.relpath(full_p, ROOT_DIR).replace(os.sep, "/")
                    add_file_to_zip(zf, full_p, f"StemsStudio/{rel_p}")

    print(f"Created {zip_path}")
    return zip_path


def find_iscc():
    found = shutil.which("ISCC") or shutil.which("iscc")
    if found:
        return found
    candidates = [
        r"C:\Program Files (x86)\Inno Setup 6\ISCC.exe",
        r"C:\Program Files\Inno Setup 6\ISCC.exe",
    ]
    for c in candidates:
        if os.path.isfile(c):
            return c
    return None


def build_inno_installer(tag):
    iscc = find_iscc()
    if not iscc:
        print("ISCC.exe not found locally; skipping StemsStudio-Setup.exe build on this machine.")
        return None
    clean_ver = tag.lstrip("vV") or "1.0.0"
    iss_path = os.path.join(ROOT_DIR, "tools", "installer.iss")
    cmd = [iscc, f"/DAppVersion={clean_ver}", iss_path]
    res = subprocess.run(cmd, cwd=ROOT_DIR)
    if res.returncode != 0:
        raise RuntimeError(f"Inno Setup compilation failed with exit code {res.returncode}")
    exe_path = os.path.join(DIST_DIR, "StemsStudio-Setup.exe")
    print(f"Created {exe_path}")
    return exe_path


def write_release_notes(tag):
    os.makedirs(DIST_DIR, exist_ok=True)
    notes_path = os.path.join(DIST_DIR, "RELEASE_NOTES.md")
    lines = [
        f"## Stems Studio {tag}",
        "",
        "Local AI Stem Separation, Pitch Highway, Chord Finder, and Singing Coach for Windows, macOS, and Linux.",
        "",
        "---",
        "",
        "### 🪟 Windows (Easiest: 1-Click Installer)",
        "1. Download **`StemsStudio-Setup.exe`** below and run it.",
        "   *(Or download **`StemsStudio.zip`**, right-click → **Extract All...**, and double-click **`Install.bat`**.)*",
        "2. The installer automatically sets up Python 3.12 if needed, configures GPU/CPU audio separation, and places **Stems Studio** and **Update Stems Studio** shortcuts on your Desktop.",
        "3. Open **Stems Studio** from your Desktop! Whenever a newer version is released, a 1-click **Update now** banner appears inside the app.",
        "",
        "### 🍎 macOS",
        "1. Download **`StemsStudio.zip`** below and double-click it to extract the **`StemsStudio`** folder.",
        "2. Open the folder and double-click **`Install.command`** (if macOS asks for confirmation, right-click **`Install.command`** → **Open**).",
        "3. Launch **Stems Studio** from Launchpad, Spotlight, or `~/Applications`.",
        "",
        "### 🐧 Linux",
        "1. Download **`StemsStudio.zip`** below, extract it, and run `./Install.command` in a terminal.",
        "2. Launch **Stems Studio** from your applications menu or via `python3 app.py`.",
        "",
    ]
    with open(notes_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))
    print(f"Created {notes_path}")
    return notes_path


def main():
    sha = get_commit_sha()
    tag = get_release_tag()
    update_version_json(sha, tag)
    build_zip_archive()
    write_release_notes(tag)
    build_inno_installer(tag)


if __name__ == "__main__":
    main()

