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

The bar at the top of the screen has three buttons.

### ✨ Create Stems (split a song)
1. Click **"✨ Create Stems"**.
2. Choose a song file (MP3 / WAV / FLAC / M4A), or paste a YouTube link.
3. Click **"✨ Create Stems"** in the window. A progress bar shows how it is going.
4. When it finishes, the stems load into the mixer by themselves.

This uses the 6-stem Nepali folk model (`htdemucs_6s`). It needs `server.py` to be running (see below); the window tells you if it is not.

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

### 1-Click Launch (Windows)
Double-click:
```bat
Run-Stems-Studio.bat
```
The first time, it installs the stem maker into a private `.venv` folder (several minutes; it uses your NVIDIA graphics card if it finds one). After that it just starts the local server and opens **http://localhost:8099** in your browser. Keep the black window open while you use the app.

> Do not start the app with `python -m http.server`. That only shows the page; **Create Stems** needs `server.py`.

### Command Line
```bash
pip install -r separator/requirements.txt
python server.py
```
Open [http://localhost:8099](http://localhost:8099).

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
