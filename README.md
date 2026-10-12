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
3. Choose **4 stems** (Vocals, Drums, Bass, Other: faster and cleanest) or **6 stems** (also splits out Guitar and Piano). Tick **Nepali folk music** only if the song is folk: that switches the lane names to Madal, Sarangi, Harmonium and so on. The model sorts sounds into groups and cannot tell a madal from a drum kit, so standard names (Vocals, Drums, Bass, Guitar, Piano, Other) are used unless you tick the box. Your choices are remembered.
   - With 6 stems you can also tick **Split the guitar into Lead and Rhythm** (experimental). No free model can reliably tell lead from rhythm, so this guesses by stereo position: guitar in the middle of the mix becomes *Lead Guitar (center)*, guitar panned left and right becomes *Rhythm Guitar (sides)*. It works well on records mixed that way (a centred lead over double-tracked, panned rhythm guitars). If a song's guitars are all in the middle or all spread wide, one of the two stems will be empty or the split will not match the real roles.
4. Click **"✨ Create Stems"** in the window. A progress bar shows how it is going.
5. When it finishes, the stems load into the mixer by themselves, with **Vocals on top**. Stems that have nothing in them (for example Piano in a song with no piano) are hidden, and a note under the mixer lets you show them anyway.

The app starts the engine for you; the window tells you if it cannot reach it.

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
- **Vocal Highway:** Above the seek bar, the sung pitch of the vocal stem scrolls towards a fixed "now" line, like a karaoke game: note bars show which notes are coming, a thin curve shows slides and vibrato, and the readout shows the note and frequency being sung right now (for example `C#4  278 Hz`). It reads the vocal stem by itself when a song loads. Click it to jump to that moment. The pitch comes from [SwiftF0](https://github.com/lars76/swift-f0), a small neural pitch detector that runs on the CPU, followed by a clean-up that removes breaths and bleed, repairs octave errors and drops stray blips. It follows one voice at a time, so doubled vocals or harmonies can still confuse it. If SwiftF0 cannot be installed, the page falls back to a simpler built-in detector.
- **Key, Sargam and Chords:** The app works out the song's key (and the tuning, if the recording is a little sharp or flat) by listening to the bass, the harmony stems (guitar, piano, other) and the sung notes together. The highway then labels every note of that scale, such as `C D E F G A B C`, with its sargam name (`Sa Re Ga Ma Pa Dha Ni`) next to it, with `Sa` on the key's root. A ribbon along the top shows the chord for each moment (`C`, `Am`, `F`, `G`...). The bar above the highway says how sure the app is, names the other possible key (a song in C major could also be A minor), and lets you choose the key yourself. This is a best guess from the audio: folk and modal songs are matched to the nearest major or minor key, and rarer chords are shown as the simpler triad.
- **Karaoke Lyrics:** The lyrics scroll under the highway and the current line fills in as it is sung. Click any line to jump to it. They come from the song file's own tags (FLAC, MP3, M4A) when it has them. If it does not, or the song came from a YouTube link, Stems Studio looks it up on [LRCLIB](https://lrclib.net), a free lyrics database with timed lyrics. If the timing is a little off for your version, use the `-0.5s` / `+0.5s` buttons. If it found the wrong song, use **Find lyrics** to search by artist and title.
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
1. Double-click **`Install.bat`**. It builds a private Python 3.12 environment in this folder (`.venv`, ignored by git), installs the GPU (CUDA) build of PyTorch when it finds an NVIDIA graphics card, installs the stem maker (several minutes the first time), and puts a **Stems Studio** shortcut on your Desktop and in the Start menu. It ends by printing which GPU the app will use. It is safe to run again whenever something needs repairing.
2. From then on, just open **Stems Studio** from the shortcut. Closing its window quits the app.

To get newer code later, run `git pull` in this folder yourself when you want it.

### Mac: install once
1. Install [Google Chrome](https://www.google.com/chrome/) if you do not have it (Edge also works; otherwise your default browser is used).
2. Double-click **`Install.command`**. (If macOS refuses to open it, right-click it, choose **Open**, then confirm. If nothing happens, run `chmod +x Install.command` in Terminal once.) It builds a private Python 3.12 environment in this folder, installs PyTorch, installs the stem maker, and creates **Stems Studio.app** in `~/Applications`.
3. Open **Stems Studio** from Launchpad or Spotlight. Drag it to the Dock if you like.

On Apple Silicon Macs (M1 and newer) the stem maker uses the Mac's GPU (MPS). Intel Macs have no usable GPU path, so they use the CPU, which is slow. If the GPU ever fails on a song, the app retries on the CPU by itself.

### Linux: install once
Run `./Install.command` in a terminal. With an NVIDIA card it installs the CUDA build of PyTorch, otherwise the CPU build, and adds **Stems Studio** to your applications menu.

### Which hardware does what
| Machine | Speed |
| :--- | :--- |
| Windows or Linux with an NVIDIA card | Fast (CUDA) |
| Mac with Apple Silicon (M1+) | Fast (MPS) |
| Anything else (Intel Mac, AMD/Intel graphics, no GPU) | Works, but runs on the CPU and takes several minutes per song |

To force a device, set the environment variable `STEMS_STUDIO_DEVICE` to `cpu`, `cuda` or `mps` before starting the app.

### Development
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
