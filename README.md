# Stems Studio

A modern multi-track audio stem mixer, practice station, and export workstation built with the Web Audio API and HTML5 Canvas.

![Stems Studio Interface](https://img.shields.io/badge/Audio-WebAudio%20API-6366f1?style=for-the-badge)
![Status](https://img.shields.io/badge/Status-Active-10b981?style=for-the-badge)

---

## Features

### 1. Multi-Track Mixer & Real-time Waveforms
- **Sample-accurate Synchronized Playback** across all stem channels (Vocals, Drums, Bass, Instruments, or custom stems).
- **Interactive High-DPI Waveforms:** Click-to-seek, drag-to-scrub, real-time playhead cursor and played-region shading.
- **Dedicated Track Controls:**
  - Tactile **Mute (M)** and **Solo (S)** buttons with glowing active indicators.
  - Smooth volume faders (-inf to +6 dB).
  - Stereo pan controls (L100% to R100%).
  - Real-time dynamic VU meters responding to live audio peaks.
  - Inline track renaming.

### 2. Master Transport & Tempo Engine
- Master digital time display (MM:SS.ms elapsed and total duration).
- Master Stereo VU meter with peak clipping detection.
- **Playback Speed / Tempo Control:** 0.5x, 0.75x, 0.9x, 1.0x, 1.1x, 1.25x, 1.5x.
- **Real-Time Pitch Shifter:** -12 to +12 semitones.
- **A/B Region Looper:** Set Loop In (A), Set Loop Out (B), toggle looping, or clear with visual shaded loop window across all waveforms.

### 3. One-Click Mix Presets
- **Karaoke Mode:** Instantly mutes the vocal track for singing along.
- **Acapella Mode:** Instantly isolates and solos the vocal stem.
- **Rhythm Only Mode:** Solos drums and bass for groove practice.
- **Reset:** Restores all levels, mutes, and solos to default.

### 4. 1-Click Multi-Track Demo Stems
- Built-in procedural synthesis engine (`DemoStemGenerator`) generates 4 synchronized, high-fidelity stems (Melody, Drums, Bass, Chords) directly inside the browser so you can test every studio feature immediately with no files needed.

### 5. High-Quality Offline WAV Export
- **Export Full Mix:** Renders current volume/pan/mute/solo mix to a 16-bit 44.1kHz stereo PCM WAV file.
- **Export Backing Track (Karaoke):** Automatically mutes vocals and renders accompaniment.
- **Export Acapella:** Renders isolated vocals.
- **Export Loop Region Only:** Option to render only between Loop In and Loop Out markers.

### 6. Session Persistence
- **Save Session:** Exports your entire mix setup (volumes, pans, mutes, solos, speed, pitch, loop markers) as a `.stems-session.json` file.
- **Load Session:** Restores saved sessions instantly.

---

## AI Stem Separator CLI (Optional)

Located in `separator/`, this Python utility uses Facebook's Demucs model to split any local audio file or YouTube video into the 4 standard stem files (`vocals.wav`, `drums.wav`, `bass.wav`, `other.wav`):

```bash
cd separator
pip install -r requirements.txt
python separate.py "https://www.youtube.com/watch?v=..."
# Or on Windows, double-click: Separate.bat
```

Once processed, drag and drop the generated `.wav` files directly into Stems Studio!

---

## Keyboard Shortcuts

| Shortcut | Action |
| :--- | :--- |
| `Space` | Play / Pause |
| `Enter` / `Home` | Return to 0:00 (Start) |
| `L` | Toggle Loop On / Off |
| `K` | Toggle Karaoke Mode (Mute Vocals) |
| `Click on Waveform` | Seek directly to timestamp |
| `Esc` | Close Import Modal |

---

## Running Locally

Simply open `index.html` in any modern web browser or serve it with any local HTTP server:

```bash
# Python
python -m http.server 8080

# Or Node npx serve
npx serve .
```
Navigate to `http://localhost:8080`.
