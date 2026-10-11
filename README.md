# Stems Studio

A modern multi-track audio stem mixer, AI separator, **vocal training studio**, and practice workstation featuring **6-Stem Neural Separation** optimized for acoustic and **Nepali folk music** (Madal, Sarangi, Bansuri, Harmonium, Plucks, Vocals).

**NEW: Vocal Training Features!**
- 🎤 **Record & Compare:** Record your voice while singing along, then compare with the original
- 🎵 **Note Teaching:** See the notes being sung in real-time with a pitch timeline visualization
- 📊 **Pitch Accuracy:** Get accuracy scores showing how closely you match the original vocals

![Stems Studio Interface](https://img.shields.io/badge/Audio-WebAudio%20API-6366f1?style=for-the-badge)
![AI-Model](https://img.shields.io/badge/AI-Demucs%206--Stem%20(htdemucs__6s)-f59e0b?style=for-the-badge)
![Status](https://img.shields.io/badge/Status-Active-10b981?style=for-the-badge)

---

## 🎯 What Makes This Different: 4 Stems vs. 6 Stems (Nepali Folk)

Most stem tools only offer 4 generic channels (*Vocals, Drums, Bass, Other*). For Nepali folk songs (Lok Dohori, Selo, Deuda, Teej, folk ballads, and acoustic arrangements), 4-stem models fail because:
1. Madal percussion gets split awkwardly between bass and drums.
2. Sarangi, Bansuri (flute), Harmonium, and Acoustic Guitars are all crammed into a messy "Other" channel.

**Stems Studio solves this with a dedicated 6-Stem AI Engine (`htdemucs_6s`):**
- 🎤 **Vocals / स्वर:** Lead singing & chorus
- 🪘 **Madal & Percussion / मादल:** Dual-head Madal (Baya bass thump & Dahina snaps), Tabla, Dholak
- 🎻 **Sarangi & Bansuri / सारङ्गी-बाँसुरी:** Folk fiddle, bamboo flute, acoustic melody leads
- 🎹 **Harmonium & Keys / हार्मोनियम:** Bellows harmonium chords, reed drone
- 🎸 **Acoustic Pluck / टुङ्ना-गितार:** Tungna, Sarod, acoustic rhythm guitar
- 🔊 **Bass & Low-End / बास:** Acoustic sub-bass and low frequencies

---

## 🚀 How to Feed Audio into Stems Studio

The bar at the top of the screen has four buttons.

### ✨ Create Stems (split a song)
1. Click **"✨ Create Stems"**.
2. Choose a song file (MP3 / WAV / FLAC / M4A), or paste a YouTube link.
3. Click **"✨ Create Stems"** in the window. A progress bar shows how it is going.
4. When it finishes, the stems load into the mixer by themselves.

This uses the 6-stem Nepali folk model (`htdemucs_6s`). The app starts the engine for you; the window tells you if it cannot reach it.

### 📚 My Library (never split the same song twice)
Every song you create is saved automatically in a small database on your computer (`library.db` in the data folder described below, with the stem files beside it). Click **"📚 My Library"** to see them all, open one instantly, or delete the ones you no longer need.

If you run **Create Stems** on a song that is already in the library, it is opened straight away instead of being processed again. This works for the same audio file even if you renamed it, and for the same YouTube video even if the link looks different. The library is stored only on this computer and is not uploaded to GitHub.

### 📁 Import Stems
Click **"Import Stems"** or drag several stem files into the window. File names containing "vocal", "madal", "drum", "bass", "guitar", "harmonium" or "sarangi" are matched to the right track.

### ▶ Demo
Synthesizes 6 stems in your browser so you can try everything without any download.

---

## 🎛️ Studio Mixer Features

- **Multi-Track Synchronized Playback:** Sample-accurate Web Audio synchronization across all channels.
- **Interactive High-DPI Waveforms:** Click-to-seek, drag-to-scrub, real-time playhead, and played-region shading.
- **Track Mixing Controls:**
  - Tactile glowing **Mute (M)** and **Solo (S)** buttons per channel.
  - Smooth volume faders (-inf to +6 dB).
  - Stereo Pan knobs (L100% to R100%).
  - Live dynamic VU meters responding to audio energy.
- **Master Transport Controls:**
  - Digital timecode readout (`MM:SS.ms`).
  - **Speed / Tempo Engine:** `0.5x` to `1.5x` playback rate.
  - **Pitch Shifter:** `-12` to `+12` semitone real-time shifting.
  - **A/B Region Looper:** Set Loop In (A), Set Loop Out (B), with shaded loop window across all waveforms.
- **1-Click Mix Presets:**
  - **Karaoke Mode (K):** Mutes vocals for singing practice.
  - **Acapella Mode:** Solos the vocal stem.
  - **Rhythm Mode:** Solos Madal / Drums & Bass for timing drills.
  - **Reset:** Restores all tracks to default levels.
- **Offline WAV Export Studio:**
  - Export Full Mixdown (`.wav`).
  - Export Backing Track / Karaoke (`.wav`).
  - Export Acapella (`.wav`).
  - Export Active Loop Region Only (`.wav`).

---

## 🎤 Vocal Training Studio / स्वर अभ्यास

The Vocal Training Studio helps you learn to sing songs by:

### 1. Record & Compare Your Vocals
- Click **"Setup Microphone"** to enable your microphone
- Click **"Record"** to start recording while the backing track plays
- After recording, toggle between **Original Vocal**, **My Recording**, or **Both** to compare
- Your recording is displayed alongside the original in the waveform view

### 2. Learn the Notes (Pitch Analysis)
- Click **"Analyze Vocals"** to extract the pitch/notes from the original vocal track
- The **Pitch Timeline** shows a piano-roll style view of what notes are being sung
- Your recorded pitch appears in **cyan** overlaid on the **red** original pitch
- Real-time **note display** shows the current note name (e.g., C4, G#5)

### 3. Get Accuracy Feedback
- After recording, see your **Pitch Accuracy Score** (0-100%)
- The **cents meter** shows if you're sharp (+) or flat (-) from the target pitch
- Color coding: 🟢 Green = on pitch, 🟡 Yellow = slightly off, 🔴 Red = off key

### Training Workflow
1. Load a song (YouTube URL, upload, or demo)
2. Click **"Analyze Vocals"** to see the pitch timeline
3. Practice with **Karaoke Mode** (vocals muted) first
4. When ready, click **"Setup Microphone"** then **"Record"**
5. Sing along with the backing track
6. Stop recording and review your pitch accuracy
7. Use **A/B loop** to practice difficult sections repeatedly

---

## 💻 Running the App

Stems Studio is a local desktop app. It runs entirely on your computer and opens in its own window (Chrome or Edge, with no tabs or address bar). GitHub is only used to keep a backup of the code and its history; the app never updates itself.

### Windows: install once
1. Double-click **`Install.bat`**. It sets up the stem maker (several minutes the first time; it uses your NVIDIA graphics card if it finds one) and puts a **Stems Studio** shortcut on your Desktop and in the Start menu. It is safe to run again whenever something needs repairing.
2. From then on, just open **Stems Studio** from the shortcut. Closing its window quits the app.

To get newer code later, run `git pull` in this folder yourself when you want it.

### Mac / Linux / development
```bash
pip install -r separator/requirements.txt
python app.py
```
`python server.py` runs only the engine, without opening a window (it keeps running until Ctrl+C).

### Where your songs are kept
The library and all stems are stored outside the code folder, so git never touches them:
- Windows: `%LOCALAPPDATA%\StemsStudio`
- Mac: `~/Library/Application Support/StemsStudio`
- Linux: `~/.local/share/stems-studio`

If something goes wrong at startup, the details are in `stems-studio.log` in that folder.

---

## ⌨️ Keyboard Shortcuts

| Shortcut | Action |
| :--- | :--- |
| `Space` | Play / Pause |
| `Enter` / `Home` | Return to 0:00 (Start) |
| `L` | Toggle Loop On / Off |
| `K` | Toggle Karaoke Mode (Mute Vocals) |
| `Click on Waveform` | Seek directly to timestamp |
| `Esc` | Close Modal |
