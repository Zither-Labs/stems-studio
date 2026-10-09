# Stems Studio

A modern multi-track audio stem mixer, AI separator, and practice workstation featuring **6-Stem Neural Separation** optimized for acoustic and **Nepali folk music** (Madal, Sarangi, Bansuri, Harmonium, Plucks, Vocals).

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

You can also switch anytime between:
- **6 Stems: Nepali Folk & Acoustic** (Madal, Sarangi, Flute, Harmonium, Pluck, Bass)
- **6 Stems: Standard** (Vocals, Drums, Bass, Guitar, Piano, Other)
- **4 Stems: Studio** (Vocals, Drums, Bass, Other)

---

## 🚀 How to Feed Audio into Stems Studio

The app has a prominent intake bar right at the top of the screen:

### Option 1: Paste a YouTube Link 🎬
1. Paste any YouTube song link (e.g. `https://www.youtube.com/watch?v=...`).
2. Select your Stem Profile (**6 Stems Nepali Folk**, **6 Stems Standard**, or **4 Stems**).
3. Click **"✨ Separate Stems & Load Mixer"**.
4. The server downloads the audio, runs neural separation, and automatically loads all stems into the multi-track studio!

### Option 2: Upload Your Own Song File (FLAC / MP3 / WAV) 📁
1. Click the **"Upload File"** tab.
2. Drag and drop or browse any song file (`.flac`, `.mp3`, `.wav`, `.m4a`).
3. Click **"✨ Separate Stems & Load Mixer"**.

### Option 3: Drop Pre-Separated Stems 🎛️
1. Click **"Import Stems"** or drag multiple stem files into the window.
2. The studio automatically matches filenames matching "vocal", "madal", "drum", "bass", "guitar", "harmonium", "sarangi" to their track lanes!

### Option 4: 1-Click Built-in Demo 🎵
1. Click **"Load 6-Stem Folk Demo"** or **"Load Studio Demo"**.
2. Immediately synthesizes 6 synchronized stems in your browser with zero download needed so you can explore all features right away!

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

## 💻 Running the App

### 1-Click Launch (Windows)
Double-click:
```bat
Run-Stems-Studio.bat
```
This automatically starts the local server and opens **http://localhost:8099** in your browser!

### Command Line
```bash
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
