"""Installs the extra chord guessers: Chordino, madmom, autochord and BTC.

Run by the installers (Install.bat / Install.command), or by hand:
    python tools/install_chord_guessers.py                 (the ones not ready yet)
    python tools/install_chord_guessers.py chordino btc    (these again)

Everything goes into .chord-tools, and all four run with the app's own Python and the packages it
already has (NumPy, SciPy, soxr, soundfile, PyTorch). The few small Python packages madmom and BTC
add (madmom itself, PyYAML, mido) go into .chord-tools/python, so the app's own environment is
never changed. Every download is pinned to one release, and each plugin and model file is checked
against a fingerprint (SHA-256). Only the files a guesser uses are downloaded, about 35 MB in all.

    Chordino   sonic-annotator (a signed command-line tool from the Sonic Visualiser team) and
               the NNLS Chroma plugin, cut out of the official Vamp Plugin Pack installer.
    autochord  autochord's trained model (2 MB). It reads the song with the Chordino plugin, so
               Chordino is installed first.
    madmom     madmom's Python code and its two chord models, set up to need no C compiler.
    BTC        The Bi-directional Transformer for Chords and its trained model.
"""
import hashlib
import importlib.util
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import tarfile
import tempfile
import urllib.error
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, ".chord-tools")
PACKAGES = os.path.join(TOOLS, "python")
STATUS = os.path.join(TOOLS, "installed.json")
REQUIREMENTS = os.path.join(ROOT, "separator", "requirements-chords.txt")
RUNNER = os.path.join(ROOT, "separator", "chord_guess_run.py")
ENGINES = ("chordino", "madmom", "autochord", "btc")
# 2: no TensorFlow, librosa or .venv-chords; madmom without its compiled parts. Older layouts are tidied.
LAYOUT = 2

SONIC = "https://github.com/sonic-visualiser/sonic-annotator/releases/download/sonic-annotator-1.7/"
PACK = "https://github.com/vamp-plugins/vamp-plugin-pack/releases/download/v2.0/"
if os.name == "nt":
    PLATFORM = "windows"
elif sys.platform == "darwin":
    PLATFORM = "mac"
else:
    PLATFORM = "linux"
SONIC_ARCHIVE = {
    "windows": "sonic-annotator-1.7-win64.zip",
    "mac": "sonic-annotator-1.7.0-macos.tar.gz",
    "linux": "sonic-annotator-1.7.0-linux64-static.tar.gz",
}[PLATFORM]
# The NNLS Chroma / Chordino plugin inside each Vamp Plugin Pack 2.0 installer:
# (installer, plugin file, first bytes, size, SHA-256, where its length is stored in the installer).
PLUGIN = {
    "windows": ("Vamp.Plugin.Pack.Installer.2.0.exe", "nnls-chroma.dll", b"MZ", 531808,
                "9e6e8b0b9fdcec20807ed050d6a0a99d77c091fefe15058ad0466fbfd2e4ae71", 21883157),
    "mac": ("Vamp.Plugin.Pack.Installer-2.0.dmg", "nnls-chroma.dylib", b"\xca\xfe\xba\xbe", 662528,
            "22b001129db5beec65abb8ac6952be6ed2cd2d809aec3d8ebb50d2495afc2dd6", None),
    "linux": ("vamp-plugin-pack-installer-2.0", "nnls-chroma.so", b"\x7fELF", 347672,
              "2908cb28c59c01330efd1bcb13300c7567b995d867e5ec796b55de5830e564ed", None),
}[PLATFORM]

AUTOCHORD_MODEL = ("https://drive.usercontent.google.com/download?id=1XBn7FyYjF8Ff6EuC7PjwwPzFBLRXGP7n"
                   "&export=download&confirm=t")
AUTOCHORD_SHA = "1d0a356292e4faba632d65caefe9ebed547f2afebe8af424f8d53d144d63351a"

MADMOM = "https://github.com/CPJKU/madmom/archive/27f032e8947204902c675e5e341a3faf5dc86dae.zip"
MADMOM_MODELS = "https://raw.githubusercontent.com/CPJKU/madmom_models/7e3dc1b0cad499792767074d03c38b194b9b0a79/"
MADMOM_MODEL_FILES = {
    "__init__.py": "89b71c041c78770a217abe0d9eaf83f428f44c95bb70e41a1907eff29785a7cb",
    "LICENSE": "4ab453b7c3b87cfb097e6a1535b0660f2b5adf775be15651b70e3aa1cf7b1757",
    "README.rst": "a031ee7cc7579ffd6c94475cd74b17c83e1e9a2349c05503ccdbd0b9c91e9538",
    "chords/2016/chords_cnnfeat.pkl": "59ac731a514880d7ec22ed9ee33935fc1683d2a03d8a7b4b81d26a3da944ce7d",
    "chords/2016/chords_cnncrf.pkl": "4b8a63b4bb5bea076cf1babc76d5cb0a3618e6125d9a3a998f441d61308676af",
}

BTC = "https://raw.githubusercontent.com/jayg996/BTC-ISMIR19/2682317be668032e6e4b269ded36adaa2ad57df0/"
BTC_MODEL = "test/btc_model_large_voca.pt"
BTC_MODEL_SHA = "1673d23f8f9a55ae7f9e8b80a51da616debb22675b8d8b67ea6ce0ef37b0ab51"
BTC_FILES = ("btc_model.py", "run_config.yaml", "LICENSE", "utils/__init__.py", "utils/hparams.py",
             "utils/transformer_modules.py", BTC_MODEL)


def run(args, **kwargs):
    print("  > " + " ".join(str(arg) for arg in args), flush=True)
    subprocess.check_call(args, **kwargs)


def pip(*args):
    run([sys.executable, "-m", "pip", "install", "--disable-pip-version-check", "--no-cache-dir", *args])


def download(url, label, start=None, size=None):
    """The bytes at url, or only size bytes from start when the server sends parts of files."""
    if label:
        print(f"  downloading {label}...", flush=True)
    headers = {"User-Agent": "StemsStudio-installer"}
    if start is not None:
        headers["Range"] = f"bytes={start}-{start + size - 1}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=120) as response:
        if start is not None and response.status != 206:
            raise ValueError("the server sent the whole file")
        return response.read()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def write_file(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as handle:
        handle.write(data)


def read_status():
    try:
        with open(STATUS, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, ValueError):
        return {}


def write_status(status):
    os.makedirs(TOOLS, exist_ok=True)
    with open(STATUS, "w", encoding="utf-8") as handle:
        json.dump(status, handle, indent=1)


def install_packages():
    """PyYAML and mido for madmom and BTC, in .chord-tools/python."""
    extra = [] if importlib.util.find_spec("soxr") else ["soxr"]   # usually there with the optional extras
    pip("--target", PACKAGES, "--upgrade", "--no-deps", "-r", REQUIREMENTS, *extra)
    shutil.rmtree(os.path.join(PACKAGES, "bin"), ignore_errors=True)


def tidy(status):
    """Removes what an older layout left behind (TensorFlow and librosa in .venv-chords, about 1.4 GB)."""
    if not status or status.get("layout") == LAYOUT:
        return status
    old = os.path.join(ROOT, ".venv-chords")
    if os.path.isdir(old):
        print("Removing the old chord-guesser environment (.venv-chords is no longer needed)...", flush=True)
        shutil.rmtree(old, ignore_errors=True)
    appimage = os.path.join(TOOLS, "sonic-annotator", "sonic-annotator")
    if PLATFORM == "linux" and os.path.isfile(appimage) and os.path.isdir(os.path.join(TOOLS, "sonic-annotator", "squashfs-root")):
        os.remove(appimage)
    status = {name: status[name] for name in ("chordino",) if name in status}
    status["layout"] = LAYOUT
    write_status(status)
    return status


# --- Chordino -----------------------------------------------------------------------------

def sonic_annotator():
    """The command that runs sonic-annotator, or None when it is not installed."""
    base = os.path.join(TOOLS, "sonic-annotator")
    for candidate in (os.path.join(base, "sonic-annotator.exe"),
                      os.path.join(base, "squashfs-root", "AppRun"),
                      os.path.join(base, "sonic-annotator")):
        if os.path.isfile(candidate):
            return candidate
    return None


def embedded_plugin(container, magic, size, digest):
    """The plugin file inside an installer. Its resources are stored as a length and then the file."""
    at = container.find(magic, 4)
    while at != -1:
        if struct.unpack_from(">I", container, at - 4)[0] == size:
            blob = container[at:at + size]
            if sha256(blob) == digest:
                return blob
        at = container.find(magic, at + 1)
    return None


def pack_installer_program(raw, work):
    """The installer program that holds the plugins, from what the Vamp Plugin Pack download is."""
    if PLATFORM == "windows":
        return raw
    path = os.path.join(work, PLUGIN[0])
    write_file(path, raw)
    if PLATFORM == "linux":
        os.chmod(path, 0o755)
        run([path, "--appimage-extract"], cwd=work, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        program = os.path.join(work, "squashfs-root", "usr", "bin", "vamp-plugin-pack-installer")
        with open(program, "rb") as handle:
            return handle.read()
    mount = os.path.join(work, "mount")
    os.makedirs(mount)
    run(["hdiutil", "attach", "-nobrowse", "-readonly", "-mountpoint", mount, path], stdout=subprocess.DEVNULL)
    try:
        for folder, _dirs, files in os.walk(mount):
            if folder.endswith(os.path.join("Contents", "MacOS")):
                for name in files:
                    with open(os.path.join(folder, name), "rb") as handle:
                        return handle.read()
    finally:
        subprocess.call(["hdiutil", "detach", mount], stdout=subprocess.DEVNULL)
    raise RuntimeError("the Vamp Plugin Pack installer had no program inside")


def chordino_plugin():
    installer, _name, magic, size, digest, offset = PLUGIN
    if offset is not None:
        # Only the plugin's own bytes (half a megabyte) instead of the whole 40 MB installer.
        try:
            blob = download(PACK + installer, "the Chordino plugin (0.5 MB)", offset, 4 + size)
            if struct.unpack_from(">I", blob)[0] == size and sha256(blob[4:]) == digest:
                return blob[4:]
        except (urllib.error.URLError, ValueError, struct.error):
            pass
    raw = download(PACK + installer, "the Vamp Plugin Pack (about 35-50 MB), for the Chordino plugin")
    with tempfile.TemporaryDirectory() as work:
        program = pack_installer_program(raw, work)
    blob = embedded_plugin(program, magic, size, digest)
    if blob is None:
        raise RuntimeError("the Chordino plugin was not found in the Vamp Plugin Pack (fingerprint did not match)")
    return blob


def install_chordino():
    base = os.path.join(TOOLS, "sonic-annotator")
    if not sonic_annotator():
        raw = download(SONIC + SONIC_ARCHIVE, "sonic-annotator (about 15 MB)")
        shutil.rmtree(base, ignore_errors=True)
        if SONIC_ARCHIVE.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                for member in archive.infolist():
                    name = member.filename.replace("\\", "/").split("/", 1)[-1]
                    if name and not name.endswith("/"):
                        write_file(os.path.join(base, *name.split("/")), archive.read(member))
        else:
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
                for member in archive.getmembers():
                    name = member.name.split("/", 1)[-1]
                    if member.isfile() and name:
                        target = os.path.join(base, *name.split("/"))
                        write_file(target, archive.extractfile(member).read())
                        os.chmod(target, 0o755)
        if PLATFORM == "linux":
            # An AppImage needs FUSE to run as it is; unpacked, it runs anywhere.
            appimage = os.path.join(base, "sonic-annotator")
            run([appimage, "--appimage-extract"], cwd=base, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            os.remove(appimage)
    plugin_dir = os.path.join(TOOLS, "vamp")
    plugin_path = os.path.join(plugin_dir, PLUGIN[1])
    if not os.path.isfile(plugin_path):
        write_file(plugin_path, chordino_plugin())
    listed = subprocess.run([sonic_annotator(), "-l"], capture_output=True, text=True,
                            env={**os.environ, "VAMP_PATH": plugin_dir}, timeout=120)
    if "vamp:nnls-chroma:chordino:simplechord" not in listed.stdout:
        raise RuntimeError("sonic-annotator could not load the Chordino plugin: " + (listed.stderr or "")[-300:])


# --- autochord ----------------------------------------------------------------------------

def install_autochord():
    if not read_status().get("chordino", {}).get("ok"):
        install_chordino()
    model_dir = os.path.join(TOOLS, "autochord")
    if not os.path.isdir(os.path.join(model_dir, "chroma-seq-bilstm-crf-v1")):
        raw = download(AUTOCHORD_MODEL, "autochord's model (2 MB)")
        if sha256(raw) != AUTOCHORD_SHA:
            raise RuntimeError("autochord's model did not match its fingerprint")
        shutil.rmtree(model_dir, ignore_errors=True)
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            archive.extractall(model_dir)
    check("autochord")


# --- madmom -------------------------------------------------------------------------------

HMM_STAND_IN = '''"""Stand-in for madmom's compiled HMM module, which the chord recogniser does not use."""


class TransitionModel(object):
    def __init__(self, *args, **kwargs):
        raise RuntimeError("this madmom was installed without its compiled parts")


class ObservationModel(TransitionModel):
    pass


class DiscreteObservationModel(ObservationModel):
    pass


class HiddenMarkovModel(TransitionModel):
    pass
'''

def install_madmom():
    # The chord recogniser is plain Python and NumPy, so the parts that need a C compiler
    # (beat and note tracking) are left out and every computer installs the same madmom.
    with tempfile.TemporaryDirectory() as work:
        with zipfile.ZipFile(io.BytesIO(download(MADMOM, "madmom (3 MB)"))) as archive:
            for member in archive.infolist():
                parts = member.filename.split("/", 1)
                if (len(parts) == 2 and parts[1].startswith("madmom/") and not member.is_dir()
                        and not parts[1].endswith((".pyx", ".pxd", ".c"))):
                    write_file(os.path.join(work, *parts[1].split("/")), archive.read(member))
        print("  downloading madmom's chord models (4 MB)...", flush=True)
        for name, digest in MADMOM_MODEL_FILES.items():
            data = download(MADMOM_MODELS + name, None)
            if sha256(data) != digest:
                raise RuntimeError(f"madmom's {name} did not match its fingerprint")
            write_file(os.path.join(work, "madmom", "models", *name.split("/")), data)
        write_file(os.path.join(work, "madmom", "ml", "hmm.py"), HMM_STAND_IN.encode("utf-8"))
        target = os.path.join(PACKAGES, "madmom")
        shutil.rmtree(target, ignore_errors=True)
        shutil.copytree(os.path.join(work, "madmom"), target)
    # madmom asks for its own version when it loads.
    write_file(os.path.join(PACKAGES, "madmom-0.17.dev0.dist-info", "METADATA"),
               b"Metadata-Version: 2.1\nName: madmom\nVersion: 0.17.dev0\n")
    check("madmom")


# --- BTC ----------------------------------------------------------------------------------

def install_btc():
    target = os.path.join(TOOLS, "btc")
    if not os.path.isfile(os.path.join(target, *BTC_MODEL.split("/"))):
        print("  downloading BTC and its model (12 MB)...", flush=True)
        shutil.rmtree(target, ignore_errors=True)
        for name in BTC_FILES:
            data = download(BTC + name, None)
            if name == BTC_MODEL and sha256(data) != BTC_MODEL_SHA:
                raise RuntimeError("BTC's model did not match its fingerprint")
            if name.endswith(".py"):
                # NumPy 2 dropped the np.float alias that BTC (2019) still uses.
                data = data.replace(b"astype(np.float)", b"astype(np.float64)")
            write_file(os.path.join(target, *name.split("/")), data)
    check("btc")


def check(engine):
    """Load the engine the way the app runs it, so a broken install is caught now and not on a song."""
    done = subprocess.run([sys.executable, RUNNER, "--check", engine, TOOLS], capture_output=True, text=True)
    if done.returncode != 0:
        lines = (done.stderr or done.stdout or "").strip().splitlines()
        raise RuntimeError(f"{engine} does not load: {lines[-1] if lines else 'no message'}")
    print(done.stdout.strip(), flush=True)


INSTALLERS = {"chordino": install_chordino, "madmom": install_madmom,
              "autochord": install_autochord, "btc": install_btc}
NEEDS_PACKAGES = ("madmom", "btc")


def main(argv):
    status = tidy(read_status())
    if argv == ["--all-ready"]:
        return 0 if all(status.get(name, {}).get("ok") for name in ENGINES) else 1
    # Named guessers are installed again. With no names, only the ones not ready yet.
    wanted = [name.lower() for name in argv] or [name for name in ENGINES if not status.get(name, {}).get("ok")]
    unknown = [name for name in wanted if name not in INSTALLERS]
    if unknown:
        print(f"Unknown chord guesser: {', '.join(unknown)}. Choose from {', '.join(ENGINES)}.", file=sys.stderr)
        return 2
    if not wanted:
        print("All four chord guessers are ready.", flush=True)
        return 0
    requested = list(wanted)
    os.makedirs(TOOLS, exist_ok=True)
    status["layout"] = LAYOUT
    if any(name in NEEDS_PACKAGES for name in wanted):
        try:
            install_packages()
        except Exception as exc:
            for name in NEEDS_PACKAGES:
                if name in wanted:
                    status[name] = {"ok": False, "error": f"PyYAML and mido could not be installed: {exc}"[-400:]}
            wanted = [name for name in wanted if name not in NEEDS_PACKAGES]
            print(f"  Could not install PyYAML and mido for madmom and BTC: {exc}", flush=True)
    for name in ENGINES:
        if name not in wanted:
            continue
        print(f"\nInstalling {name}...", flush=True)
        try:
            INSTALLERS[name]()
            status[name] = {"ok": True}
            print(f"  {name} is ready.", flush=True)
        except Exception as exc:
            status[name] = {"ok": False, "error": str(exc)[-400:]}
            print(f"  Could not install {name}: {exc}", flush=True)
        write_status(status)
    write_status(status)
    ready = [name for name in ENGINES if status.get(name, {}).get("ok")]
    print("\nChord guessers ready: " + (", ".join(ready) if ready else "none"), flush=True)
    return 0 if all(status.get(name, {}).get("ok") for name in requested) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
