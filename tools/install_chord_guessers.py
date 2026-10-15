"""Installs the extra chord guessers: Chordino, madmom, autochord and BTC.

Run by the installers (Install.bat / Install.command), or by hand:
    python tools/install_chord_guessers.py                 (all four)
    python tools/install_chord_guessers.py chordino btc    (only some)

The Python parts go into their own environment (.venv-chords). Like "cleaner vocals", it borrows
PyTorch and the other big packages from the main environment through a .pth file, so the main
environment is never changed. Programs and model files go into .chord-tools. Every download is
pinned to one release, and the plugin and model files are checked against a fingerprint (SHA-256).

    Chordino   sonic-annotator (a signed command-line tool from the Sonic Visualiser team) and
               the NNLS Chroma plugin, taken from the official Vamp Plugin Pack installer.
    autochord  TensorFlow and autochord's trained model. It reads the song with the Chordino
               plugin, so Chordino is installed first.
    madmom     madmom's chord recogniser and its trained models. Where a C compiler is missing
               (most Windows computers), only the parts the chord recogniser uses are installed.
    BTC        The Bi-directional Transformer for Chords and its trained model. Runs on PyTorch.
"""
import hashlib
import io
import json
import os
import shutil
import struct
import subprocess
import sys
import sysconfig
import tarfile
import tempfile
import urllib.request
import zipfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV = os.path.join(ROOT, ".venv-chords")
TOOLS = os.path.join(ROOT, ".chord-tools")
STATUS = os.path.join(TOOLS, "installed.json")
REQUIREMENTS = os.path.join(ROOT, "separator", "requirements-chords.txt")
ENGINES = ("chordino", "madmom", "autochord", "btc")

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
# The NNLS Chroma / Chordino plugin inside each Vamp Plugin Pack 2.0 installer.
PLUGIN = {
    "windows": ("Vamp.Plugin.Pack.Installer.2.0.exe", "nnls-chroma.dll", b"MZ", 531808,
                "9e6e8b0b9fdcec20807ed050d6a0a99d77c091fefe15058ad0466fbfd2e4ae71"),
    "mac": ("Vamp.Plugin.Pack.Installer-2.0.dmg", "nnls-chroma.dylib", b"\xca\xfe\xba\xbe", 662528,
            "22b001129db5beec65abb8ac6952be6ed2cd2d809aec3d8ebb50d2495afc2dd6"),
    "linux": ("vamp-plugin-pack-installer-2.0", "nnls-chroma.so", b"\x7fELF", 347672,
              "2908cb28c59c01330efd1bcb13300c7567b995d867e5ec796b55de5830e564ed"),
}[PLATFORM]

AUTOCHORD_MODEL = ("https://drive.usercontent.google.com/download?id=1XBn7FyYjF8Ff6EuC7PjwwPzFBLRXGP7n"
                   "&export=download&confirm=t")
AUTOCHORD_SHA = "1d0a356292e4faba632d65caefe9ebed547f2afebe8af424f8d53d144d63351a"

MADMOM = "https://github.com/CPJKU/madmom/archive/27f032e8947204902c675e5e341a3faf5dc86dae.zip"
MADMOM_MODELS = "https://github.com/CPJKU/madmom_models/archive/7e3dc1b0cad499792767074d03c38b194b9b0a79.zip"

BTC = "https://github.com/jayg996/BTC-ISMIR19/archive/2682317be668032e6e4b269ded36adaa2ad57df0.zip"
BTC_MODEL_SHA = "1673d23f8f9a55ae7f9e8b80a51da616debb22675b8d8b67ea6ce0ef37b0ab51"
BTC_FILES = ("btc_model.py", "run_config.yaml", "LICENSE", "utils/__init__.py", "utils/hparams.py",
             "utils/transformer_modules.py", "test/btc_model_large_voca.pt")


def venv_python():
    return os.path.join(VENV, "Scripts", "python.exe") if os.name == "nt" else os.path.join(VENV, "bin", "python")


def run(args, **kwargs):
    print("  > " + " ".join(str(arg) for arg in args), flush=True)
    subprocess.check_call(args, **kwargs)


def pip(*args):
    run([venv_python(), "-m", "pip", "install", "--disable-pip-version-check", *args])


def download(url, label):
    print(f"  downloading {label}...", flush=True)
    request = urllib.request.Request(url, headers={"User-Agent": "StemsStudio-installer"})
    with urllib.request.urlopen(request, timeout=120) as response:
        return response.read()


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def ensure_venv():
    if not os.path.isfile(venv_python()):
        print("Creating the chord-guesser environment...", flush=True)
        run([sys.executable, "-m", "venv", VENV])
        run([venv_python(), "-m", "pip", "install", "--disable-pip-version-check", "--upgrade", "pip"])
    main_packages = sysconfig.get_paths()["purelib"]
    venv_packages = subprocess.check_output(
        [venv_python(), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"], text=True).strip()
    with open(os.path.join(venv_packages, "main_environment.pth"), "w", encoding="utf-8") as handle:
        handle.write(main_packages + "\n")


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
    with open(path, "wb") as handle:
        handle.write(raw)
    if PLATFORM == "linux":
        os.chmod(path, 0o755)
        run([path, "--appimage-extract"], cwd=work, stdout=subprocess.DEVNULL)
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


def install_chordino():
    base = os.path.join(TOOLS, "sonic-annotator")
    if not sonic_annotator():
        raw = download(SONIC + SONIC_ARCHIVE, "sonic-annotator (about 15 MB)")
        shutil.rmtree(base, ignore_errors=True)
        os.makedirs(base)
        if SONIC_ARCHIVE.endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(raw)) as archive:
                for member in archive.infolist():
                    name = member.filename.replace("\\", "/").split("/", 1)[-1]
                    if not name or name.endswith("/"):
                        continue
                    target = os.path.join(base, *name.split("/"))
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with open(target, "wb") as handle:
                        handle.write(archive.read(member))
        else:
            with tarfile.open(fileobj=io.BytesIO(raw), mode="r:gz") as archive:
                for member in archive.getmembers():
                    name = member.name.split("/", 1)[-1]
                    if not member.isfile() or not name:
                        continue
                    target = os.path.join(base, *name.split("/"))
                    os.makedirs(os.path.dirname(target), exist_ok=True)
                    with open(target, "wb") as handle:
                        handle.write(archive.extractfile(member).read())
                    os.chmod(target, 0o755)
        if PLATFORM == "linux":
            run([os.path.join(base, "sonic-annotator"), "--appimage-extract"], cwd=base, stdout=subprocess.DEVNULL)
    plugin_dir = os.path.join(TOOLS, "vamp")
    plugin_path = os.path.join(plugin_dir, PLUGIN[1])
    if not os.path.isfile(plugin_path):
        raw = download(PACK + PLUGIN[0], "the Vamp Plugin Pack (about 35-50 MB), for the Chordino plugin")
        with tempfile.TemporaryDirectory() as work:
            program = pack_installer_program(raw, work)
        blob = embedded_plugin(program, *PLUGIN[2:])
        if blob is None:
            raise RuntimeError("the Chordino plugin was not found in the Vamp Plugin Pack (fingerprint did not match)")
        os.makedirs(plugin_dir, exist_ok=True)
        with open(plugin_path, "wb") as handle:
            handle.write(blob)
    listed = subprocess.run([sonic_annotator(), "-l"], capture_output=True, text=True,
                            env={**os.environ, "VAMP_PATH": plugin_dir}, timeout=120)
    if "vamp:nnls-chroma:chordino:simplechord" not in listed.stdout:
        raise RuntimeError("sonic-annotator could not load the Chordino plugin: " + (listed.stderr or "")[-300:])


# --- autochord ----------------------------------------------------------------------------

def install_autochord():
    if not read_status().get("chordino", {}).get("ok"):
        install_chordino()
    if PLATFORM == "mac" and os.uname().machine != "arm64":
        raise RuntimeError("TensorFlow has no build for Intel Macs")
    pip("-r", REQUIREMENTS)
    # tf-keras asks for the full "tensorflow" package; tensorflow-cpu is the same code without the GPU parts.
    pip("tensorflow-cpu>=2.16" if PLATFORM != "mac" else "tensorflow>=2.16")
    pip("--no-deps", "tf-keras")
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

HMM_STAND_IN = '''"""Stand-in for madmom's compiled HMM module (no C compiler was found).

The chord recogniser does not use it. Beat and note tracking need the full madmom build.
"""


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

PURE_SETUP = '''from setuptools import setup, find_packages

setup(
    name="madmom",
    version="0.17.dev0",
    packages=find_packages(exclude=["tests", "docs"]),
    package_data={"madmom": ["models/LICENSE", "models/README.rst", "models/chords/*/*", "models/chroma/*/*"]},
    install_requires=["numpy", "scipy>=1.13", "mido>=1.2.6"],
)
'''


def install_madmom():
    with tempfile.TemporaryDirectory() as work:
        for url, label in ((MADMOM, "madmom (3 MB)"), (MADMOM_MODELS, "madmom's models (30 MB)")):
            with zipfile.ZipFile(io.BytesIO(download(url, label))) as archive:
                archive.extractall(work)
        source = next(os.path.join(work, name) for name in os.listdir(work) if name.startswith("madmom-"))
        models = next(os.path.join(work, name) for name in os.listdir(work) if name.startswith("madmom_models-"))
        shutil.rmtree(os.path.join(source, "madmom", "models"), ignore_errors=True)
        shutil.move(models, os.path.join(source, "madmom", "models"))
        try:
            pip(source)
        except subprocess.CalledProcessError:
            print("  The full madmom build needs a C compiler. Installing only the chord recogniser.", flush=True)
            os.remove(os.path.join(source, "pyproject.toml"))
            with open(os.path.join(source, "setup.py"), "w", encoding="utf-8") as handle:
                handle.write(PURE_SETUP)
            with open(os.path.join(source, "madmom", "ml", "hmm.py"), "w", encoding="utf-8") as handle:
                handle.write(HMM_STAND_IN)
            pip(source)
    check("madmom")


# --- BTC ----------------------------------------------------------------------------------

def install_btc():
    pip("-r", REQUIREMENTS)
    target = os.path.join(TOOLS, "btc")
    if not os.path.isfile(os.path.join(target, "test", "btc_model_large_voca.pt")):
        with zipfile.ZipFile(io.BytesIO(download(BTC, "BTC and its model (about 60 MB)"))) as archive:
            prefix = archive.namelist()[0].split("/")[0]
            shutil.rmtree(target, ignore_errors=True)
            for name in BTC_FILES:
                data = archive.read(f"{prefix}/{name}")
                if name.endswith(".pt") and sha256(data) != BTC_MODEL_SHA:
                    raise RuntimeError("BTC's model did not match its fingerprint")
                if name.endswith(".py"):
                    # NumPy 2 dropped the np.float alias that BTC (2019) still uses.
                    data = data.replace(b"astype(np.float)", b"astype(np.float64)")
                path = os.path.join(target, *name.split("/"))
                os.makedirs(os.path.dirname(path), exist_ok=True)
                with open(path, "wb") as handle:
                    handle.write(data)
    check("btc")


def check(engine):
    """Load the engine in its environment, so a broken install is caught now and not on a song."""
    runner = os.path.join(ROOT, "separator", "chord_guess_run.py")
    done = subprocess.run([venv_python(), runner, "--check", engine, TOOLS], capture_output=True, text=True,
                          env={**os.environ, "TF_CPP_MIN_LOG_LEVEL": "2"})
    if done.returncode != 0:
        lines = (done.stderr or done.stdout or "").strip().splitlines()
        raise RuntimeError(f"{engine} does not load: {lines[-1] if lines else 'no message'}")
    print(done.stdout.strip(), flush=True)


INSTALLERS = {"chordino": install_chordino, "madmom": install_madmom,
              "autochord": install_autochord, "btc": install_btc}


def all_ready():
    status = read_status()
    return all(status.get(name, {}).get("ok") for name in ENGINES)


def main(argv):
    if argv == ["--all-ready"]:
        return 0 if all_ready() else 1
    status = read_status()
    # Named guessers are installed again. With no names, only the ones not ready yet.
    wanted = [name.lower() for name in argv] or [name for name in ENGINES if not status.get(name, {}).get("ok")]
    unknown = [name for name in wanted if name not in INSTALLERS]
    if unknown:
        print(f"Unknown chord guesser: {', '.join(unknown)}. Choose from {', '.join(ENGINES)}.", file=sys.stderr)
        return 2
    if not wanted:
        print("All four chord guessers are ready.", flush=True)
        return 0
    os.makedirs(TOOLS, exist_ok=True)
    ensure_venv()
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
    ready = [name for name in ENGINES if status.get(name, {}).get("ok")]
    print("\nChord guessers ready: " + (", ".join(ready) if ready else "none"), flush=True)
    return 0 if all(status.get(name, {}).get("ok") for name in wanted) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
