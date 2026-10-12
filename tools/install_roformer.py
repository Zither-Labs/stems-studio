"""Installs "cleaner vocals": the audio-separator tool in its own environment (.venv-roformer).

Run by the installers (Install.bat / Install.command), or by hand:
    python tools/install_roformer.py

The new environment borrows PyTorch and the other big packages from the main environment (the
one running this script) through a .pth file, so nothing is downloaded twice and the main
environment is never changed. The model file (about 610 MB) is downloaded on first use.
"""
import os
import subprocess
import sys
import sysconfig

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VENV = os.path.join(ROOT, ".venv-roformer")
REQUIREMENTS = os.path.join(ROOT, "separator", "requirements-roformer.txt")


def venv_python():
    return os.path.join(VENV, "Scripts", "python.exe") if os.name == "nt" else os.path.join(VENV, "bin", "python")


def run(args):
    print("  > " + " ".join(args), flush=True)
    subprocess.check_call(args)


def main():
    if not os.path.isfile(venv_python()):
        print("Creating the cleaner-vocals environment...", flush=True)
        run([sys.executable, "-m", "venv", VENV])

    # Let the new environment see PyTorch and friends from the main environment.
    main_packages = sysconfig.get_paths()["purelib"]
    venv_packages = subprocess.check_output(
        [venv_python(), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"], text=True).strip()
    with open(os.path.join(venv_packages, "main_environment.pth"), "w", encoding="utf-8") as handle:
        handle.write(main_packages + "\n")

    print("Installing the packages (a few hundred MB)...", flush=True)
    run([venv_python(), "-m", "pip", "install", "--upgrade", "pip"])
    run([venv_python(), "-m", "pip", "install", "-r", REQUIREMENTS])
    run([venv_python(), "-m", "pip", "install", "--no-deps", "audio-separator", "onnx2torch-py313"])

    print("Checking it works...", flush=True)
    run([venv_python(), "-c",
         "import torch, audio_separator.separator as s; print('  ok, PyTorch', torch.__version__, 'CUDA', torch.cuda.is_available())"])
    print("Cleaner vocals is installed.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Could not install cleaner vocals: {exc}", file=sys.stderr)
        sys.exit(1)
