#!/bin/bash
# Stems Studio - setup for macOS and Linux.
#   Mac:    double-click this file (first time: right-click > Open if macOS asks).
#   Linux:  run   ./Install.command
# Safe to run again at any time. It only installs what is missing.

cd "$(dirname "$0")" || exit 1
ROOT="$(pwd)"
OS="$(uname -s)"
ARCH="$(uname -m)"
VENV_PY="$ROOT/.venv/bin/python"

pause_and_exit() {
    echo
    read -n 1 -s -r -p "Press any key to close this window..."
    echo
    exit "$1"
}

fail() {
    echo
    echo "$1"
    pause_and_exit 1
}

find_uv() {
    UV=""
    if command -v uv >/dev/null 2>&1; then UV="$(command -v uv)"; return 0; fi
    for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv"; do
        if [ -x "$candidate" ]; then UV="$candidate"; return 0; fi
    done
    return 1
}

echo "======================================================================"
echo "  Stems Studio - setup ($OS $ARCH)"
echo "  Safe to run again at any time. It only installs what is missing."
echo "======================================================================"
echo

# --- Step 1: private Python 3.12 environment (.venv) -------------------------
# The app always runs from its own environment, never from some other Python.
if [ ! -x "$VENV_PY" ]; then
    echo "Step 1 of 4: creating a private Python 3.12 environment..."
    if command -v python3.12 >/dev/null 2>&1 && python3.12 -m venv "$ROOT/.venv" >/dev/null 2>&1; then
        :
    else
        rm -rf "$ROOT/.venv"
        if ! find_uv; then
            echo "Installing the uv tool, which can fetch Python 3.12 for us..."
            if command -v curl >/dev/null 2>&1; then
                curl -LsSf https://astral.sh/uv/install.sh | sh
            fi
            find_uv || fail "Could not set up Python. Install Python 3.12 from python.org (or run: brew install python@3.12), then run this file again."
        fi
        "$UV" venv "$ROOT/.venv" --python 3.12 --managed-python --seed \
            || fail "Could not create the Python environment. Install Python 3.12 from python.org, then run this file again."
    fi
    [ -x "$VENV_PY" ] || fail "Could not create the Python environment."
    "$VENV_PY" -m pip install --upgrade pip
fi

# --- Step 2: PyTorch (the part that talks to the graphics card) --------------
torch_ok()   { "$VENV_PY" -c "import torch" >/dev/null 2>&1; }
cuda_ok()    { "$VENV_PY" -c "import sys, torch; sys.exit(0 if torch.cuda.is_available() else 1)" >/dev/null 2>&1; }

if [ "$OS" = "Darwin" ]; then
    # The standard Mac build already includes support for Apple Silicon GPUs (MPS).
    if ! torch_ok; then
        echo "Step 2 of 4: installing PyTorch for Mac..."
        "$VENV_PY" -m pip install "torch<2.9" "torchaudio<2.9" || fail "The PyTorch install did not finish. Please copy the messages above and send them over."
    fi
elif command -v nvidia-smi >/dev/null 2>&1; then
    if ! cuda_ok; then
        echo "Step 2 of 4: NVIDIA graphics card found. Installing the GPU version of PyTorch..."
        echo "(about 2.5 GB the first time - please be patient)"
        "$VENV_PY" -m pip uninstall -y torch torchaudio >/dev/null 2>&1
        "$VENV_PY" -m pip install "torch==2.5.1" "torchaudio==2.5.1" --index-url https://download.pytorch.org/whl/cu124 \
            || fail "The PyTorch install did not finish. Please copy the messages above and send them over."
    fi
else
    if ! torch_ok; then
        echo "Step 2 of 4: no NVIDIA graphics card found. Installing the CPU version of PyTorch..."
        "$VENV_PY" -m pip install "torch<2.9" "torchaudio<2.9" --index-url https://download.pytorch.org/whl/cpu \
            || fail "The PyTorch install did not finish. Please copy the messages above and send them over."
    fi
fi

# --- Step 3: the stem maker and its helpers ----------------------------------
if ! "$VENV_PY" -c "import demucs, yt_dlp, static_ffmpeg, soundfile, numpy" >/dev/null 2>&1; then
    echo "Step 3 of 4: installing the stem maker. This can take several minutes..."
    "$VENV_PY" -m pip install -r "$ROOT/separator/requirements.txt" \
        || fail "The install did not finish. Please copy the messages above and send them over."
fi

# The extras (pitch detector, key finder, lyrics) are optional: the app still works without them.
if ! "$VENV_PY" -c "import swift_f0, soxr, mutagen" >/dev/null 2>&1; then
    echo "Installing the extras (pitch detector, key finder, lyrics)..."
    "$VENV_PY" -m pip install -r "$ROOT/separator/requirements-extras.txt" \
        || echo "  (Could not install it. The app still works; some features will be simpler or switched off.)"
fi

# Cleaner vocals (optional): a better vocal model that lets less guitar leak into the vocal.
# It lives in its own folder (.venv-roformer), so it can not disturb the rest of the app.
if [ ! -x "$ROOT/.venv-roformer/bin/audio-separator" ]; then
    echo
    echo "Optional: 'cleaner vocals' makes the vocal stem with a better model (less guitar bleed)."
    echo "It adds a few hundred MB now and a 600 MB model the first time you use it."
    read -r -p "Install it now? [y/N] " ANSWER
    case "$ANSWER" in
        [yY]*) "$VENV_PY" "$ROOT/tools/install_roformer.py" \
                   || echo "  (Could not install it. The app still works without it.)" ;;
    esac
fi

# More chord guessers (optional): Chordino, madmom, autochord and BTC, in their own folders
# (in .chord-tools). The app's own chord guess works without them.
if ! "$VENV_PY" "$ROOT/tools/install_chord_guessers.py" --all-ready >/dev/null 2>&1; then
    echo
    echo "Optional: 'more chord guessers' adds Chordino, madmom, autochord and BTC next to the"
    echo "app's own chord guess, so you can compare them. It adds under 100 MB."
    echo "Any that are already installed are kept."
    read -r -p "Install them now? [y/N] " ANSWER
    case "$ANSWER" in
        [yY]*) "$VENV_PY" "$ROOT/tools/install_chord_guessers.py" \
                   || echo "  (Some could not be installed. The app still works; the menu marks them.)" ;;
    esac
fi
# --- Step 4: launcher --------------------------------------------------------
echo "Step 4 of 4: creating the Stems Studio launcher..."
if [ "$OS" = "Darwin" ]; then
    APP="$HOME/Applications/Stems Studio.app"
    mkdir -p "$APP/Contents/MacOS"
    cat > "$APP/Contents/MacOS/StemsStudio" <<EOF
#!/bin/bash
mkdir -p "\$HOME/Library/Logs"
exec "$VENV_PY" "$ROOT/app.py" >> "\$HOME/Library/Logs/StemsStudio.log" 2>&1
EOF
    chmod +x "$APP/Contents/MacOS/StemsStudio"
    cat > "$APP/Contents/Info.plist" <<'EOF'
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>Stems Studio</string>
    <key>CFBundleDisplayName</key><string>Stems Studio</string>
    <key>CFBundleIdentifier</key><string>com.zitherlabs.stemsstudio</string>
    <key>CFBundleExecutable</key><string>StemsStudio</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleVersion</key><string>1</string>
    <key>LSUIElement</key><true/>
</dict>
</plist>
EOF
    echo "Created: $APP"
    LAUNCH_HINT="Open \"Stems Studio\" from Launchpad, Spotlight, or your Applications folder (~/Applications)."
else
    mkdir -p "$HOME/.local/share/applications"
    cat > "$HOME/.local/share/applications/stems-studio.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Stems Studio
Comment=Split songs into stems and practise with them
Exec="$VENV_PY" "$ROOT/app.py"
Terminal=false
Categories=AudioVideo;Audio;
EOF
    echo "Created: $HOME/.local/share/applications/stems-studio.desktop"
    LAUNCH_HINT="Open \"Stems Studio\" from your applications menu, or run: $VENV_PY $ROOT/app.py"
fi

echo
echo "Checking the compute device the app will use..."
"$VENV_PY" - <<'EOF'
import torch
if torch.cuda.is_available():
    print("  GPU: " + torch.cuda.get_device_name(0))
elif getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
    print("  GPU: Apple Silicon (MPS)")
else:
    print("  CPU only (no usable graphics card found) - songs will take longer")
EOF
echo
echo "All done. $LAUNCH_HINT"
pause_and_exit 0
