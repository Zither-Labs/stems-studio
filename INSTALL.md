# Stems Studio - Installation Guide
**Cross-Platform Setup for Windows, macOS, and Linux**

Stems Studio runs locally on your machine. The code is lightweight, and the installer automatically sets up a private Python environment, PyTorch, AI models, and audio dependencies.

---

## 🪟 Windows (10 / 11)

### Steps:
1. Extract the `StemsStudio.zip` archive to any directory on your computer (e.g. `C:\Music\StemsStudio` or `C:\StemsStudio`).
2. Double-click **`Install.bat`**.
3. The installer will:
   - Create an isolated Python 3.12 environment in `.venv/`.
   - Automatically detect an NVIDIA graphics card (via CUDA) or fall back to CPU multithreading.
   - Install Demucs, yt-dlp, and audio postprocessing packages.
   - Place **Stems Studio** shortcuts on your **Desktop** and **Start Menu**.
4. Open **Stems Studio** from your Desktop shortcut!

*Note: If you do not have Python installed, the installer automatically fetches a standalone Python 3.12 runtime.*

---

## 🍎 macOS (Apple Silicon M1/M2/M3/M4 & Intel)

### Steps:
1. Unzip the `StemsStudio.zip` archive.
2. Double-click **`Install.command`**.
   - *First-time launch:* If macOS displays a Gatekeeper prompt ("unidentified developer"), right-click `Install.command` and choose **Open**, then confirm.
3. The script will:
   - Set up an isolated Python 3.12 environment.
   - Configure PyTorch with **Apple Silicon GPU acceleration (Metal Performance Shaders / MPS)** for fast stem separation.
   - Install Demucs, yt-dlp, and audio libraries.
   - Automatically build and install **`~/Applications/Stems Studio.app`**.
4. Open **Stems Studio** directly from **Spotlight (`Cmd + Space`)**, **Launchpad**, or your **Applications** folder!

*Tip: Google Chrome or Microsoft Edge provides the best borderless app window experience on macOS.*

---

## 🐧 Linux (Ubuntu, Debian, Fedora, Arch, etc.)

### Steps:
1. Extract the `StemsStudio.zip` archive and open a terminal inside the folder.
2. Make the installer executable and run it:
   ```bash
   chmod +x Install.command
   ./Install.command
   ```
3. The script will:
   - Create the Python 3.12 virtual environment in `.venv/`.
   - Detect NVIDIA drivers (`nvidia-smi`) and install the CUDA build of PyTorch (or CPU build).
   - Install Demucs, yt-dlp, and audio processing tools.
   - Create a desktop launcher in `~/.local/share/applications/stems-studio.desktop`.
4. Launch **Stems Studio** from your system **Applications menu**, or execute:
   ```bash
   ./.venv/bin/python app.py
   ```

*Prerequisites: Ensure `python3`, `curl`, and `bash` are installed on your distribution.*

---

## ⚡ Hardware Acceleration & Separation Speeds

| Hardware | Acceleration Mode | Typical Speed (per song) |
| :--- | :--- | :--- |
| **Windows / Linux + NVIDIA GPU** | NVIDIA CUDA | ~30 - 60 seconds |
| **Mac Apple Silicon (M1 / M2 / M3 / M4)** | Apple Metal (MPS) | ~45 - 90 seconds |
| **CPU Only (Intel Mac, AMD/Intel graphics)** | CPU Multithreading | ~3 - 5 minutes |

---

## 🔄 Updates

To update Stems Studio to the newest version in the future:
- **Windows**: Double-click **`Update.bat`** (or the "Update Stems Studio" shortcut).
- **Mac / Linux**: Run `git pull origin main` inside the project folder.

---

*Created by Bikash Acharya*
