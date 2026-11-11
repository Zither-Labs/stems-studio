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
2. Choose an audio file (MP3 / WAV / FLAC / M4A), or paste a supported media stream URL.
3. Choose **4 stems** (Vocals, Drums, Bass, Other: faster and cleanest) or **6 stems** (also splits out Guitar and Piano). Tick **Nepali folk music** only if the song is folk: that switches the lane names to Madal, Sarangi, Harmonium and so on. The model sorts sounds into groups and cannot tell a madal from a drum kit, so standard names (Vocals, Drums, Bass, Guitar, Piano, Other) are used unless you tick the box. Your choices are remembered.
   - With 6 stems you can also tick **Split the guitar into Lead and Rhythm** (experimental). No free model can reliably tell lead from rhythm, so this guesses by stereo position: guitar in the middle of the mix becomes *Lead Guitar (center)*, guitar panned left and right becomes *Rhythm Guitar (sides)*. It works well on records mixed that way (a centred lead over double-tracked, panned rhythm guitars). If a song's guitars are all in the middle or all spread wide, one of the two stems will be empty or the split will not match the real roles.
    - Tick **Cleaner vocals** when guitar or other instruments leak into the vocal (a guitar solo that shows up as "singing" on the highway, for example). The vocal is then made by a Roformer model, which leaks much less than Demucs. In a test on a song with a long guitar solo, the leftover sound in the vocal stem during the solo was about 24 dB quieter. The rest of the song is still split by Demucs. It is slower, needs the optional install (say yes to it in the installer) and downloads a 600 MB model the first time. The model weights come from the Ultimate Vocal Remover community; check their licence before using Stems Studio commercially.
    - Tick **Split the drums** to get kick, snare, toms, hi-hat, ride and crash as separate stems in the mixer, in place of the single Drums stem (empty parts are hidden). It uses the same optional install and a drum-splitting model (about 120 MB, downloaded the first time; its weights come from the same community, so check their licence before commercial use). It adds about a minute for a song on a graphics card. A song you already split keeps its stems, so for those use the **Split drums** button in My Library instead. The ride and hi-hat parts can still hold some leftover sound from the other cymbals. In the mixer the parts sit under one **Drums** bar: click it to fold the individual drum stems away or show them again (the choice is remembered; they are folded by default, keep playing, and stay on the highway's drum lane), and its **M** and **S** buttons mute or solo all the drums at once.
    - A song you already split can get **Clean vocals** from My Library without the original file. The song is put back together from its stems, the Roformer model makes a new vocal from it, and whatever the new vocal no longer holds (the guitar that had leaked in) is moved to the Guitar stem (or Other), so the stems still add up. On "Like A Stone" the vocal stem during a guitar solo (about 3:00 to 3:10) went from roughly -40 dB to below -80 dB. Some leftover sound at the start of a solo can remain. It takes a couple of minutes. **Undo clean vocals** puts the old vocal back: the app keeps a copy of the vocal, and of the stem that received the leftover, from before the first clean. A later clean does not overwrite those copies.
4. Click **"✨ Create Stems"** in the window. A progress bar shows how it is going.
5. When it finishes, the stems load into the mixer by themselves, with **Vocals on top**. Stems that have nothing in them (for example Piano in a song with no piano) are hidden, and a note under the mixer lets you show them anyway.

The app starts the engine for you; the window tells you if it cannot reach it.

### 📚 My Library (never split the same song twice)
Every song you create is saved automatically in a small database on your computer (`library.db` in the library folder described below, with one folder per song beside it, named like `Audioslave - Like A Stone`, holding that song's stems as ordinary `.wav` files you can open in any other program). Click **"📚 My Library"** to see them all, open one instantly, or delete the ones you no longer need. The window shows the folder the songs are in. **Change folder** points the app at a different one (for example a drive that already has your songs) and remembers it in `settings.json`. If a song's audio files cannot be opened, it stays in the list with a note, and it is not removed from `library.db`. Coach scores and the lyrics timing nudge for each song are kept in that song's folder (`practice.json`), so they stay with the library. Your voice type is kept on this computer.

If you run **Create Stems** on a song that is already in the library, it is opened straight away instead of being processed again. This works for the same audio file even if you renamed it, and for the same media URL even if the link formatting varies. The library is stored only on this computer and is not uploaded to GitHub.

### 📁 Import Stems
Click **"Import Stems"** or drag several stem files into the window. File names containing "vocal", "madal", "drum", "bass", "guitar", "harmonium" or "sarangi" are matched to the right track.

### ▶ Demo
Synthesizes 6 stems in your browser so you can try everything without any download.

---

## 🎛️ Studio Mixer Features

- **Multi-Track Synchronized Playback:** Sample-accurate Web Audio synchronization across all channels.
- **Vocal Highway:** Above the seek bar, the sung pitch of the vocal stem scrolls towards a fixed "now" line, like a karaoke game: note bars show which notes are coming, a thin curve shows slides and vibrato, and the readout shows the note and frequency being sung right now (for example `C#4  278 Hz`). It reads the vocal stem by itself when a song loads. Click it to jump to that moment. The pitch comes from [SwiftF0](https://github.com/lars76/swift-f0), a small neural pitch detector that runs on the CPU, followed by a clean-up that removes breaths and bleed, repairs octave errors and drops stray blips. It follows one voice at a time, so doubled vocals or harmonies can still confuse it. If SwiftF0 cannot be installed, the page falls back to a simpler built-in detector. A ghost-note check compares each note with the guitar, piano and other stems: a note that is just a quieter copy of what an instrument is playing (an instrument that leaked into the vocal stem) is removed.
- **Key, Sargam and Chords:** The app works out the song's key (and the tuning, if the recording is a little sharp or flat) by listening to the bass, the harmony stems (guitar, piano, other) and the sung notes together. The highway then labels every note of that scale, such as `C D E F G A B C`, with its sargam name (`Sa Re Ga Ma Pa Dha Ni`) next to it, with `Sa` on the key's root. Chord names appear along the top of the highway only after two passes. The first pass is a published chord chart the app looks up from the song's name: [Start Jamming](https://www.startjamming.com) for songs in that book, and [Karalyr](https://karalyr.com) when that recording already has a timed chart. The app slides that chart through all twelve keys until it follows the bass. **Chord sheet** takes the chords you know, by part (`verse G Em` and `chorus C G# F#`). You do not count lines or mark times. Inside a part the chords can repeat in any order, and the next part starts when the bass lands on one of its chords. The key you write can be wrong: the whole sheet slides together until it follows the bass. An outro made of other chords is left blank. The bass is not trusted note by note: the app finds the tempo and the meter (3/4, 4/4, and the other common ones) and reads the chord from the beat together with the rhythm guitar. It follows every beat as it lands, so a band that speeds up or slows down stays in step (the dynamic-programming beat tracker from Ellis, 2007), and it reads the chord on each half beat. The bass note comes from the bass line drawn on the highway, which is timed to a few hundredths of a second, so a chord changes when the bass does and not a beat early. A walking bass can move while that chord stays. When the guitar could be either of two chords, the bass root is what flips it back, and that change can fall on any beat. A later part that shares a root does not keep the song from returning to the earlier part. A new song does that listen while the stems are being made, on the same progress bar. A song already in the library does that listen again when the bass reading changes (the stems are not made again), and a bar on the highway and in Chord sheet shows how far that listen has got. The second pass is the app's own listening, and it only fills a gap when the bass note is the chord's root. A chord the bass does not agree with is left off a pasted sheet. When no chart covers the song, the app's own guess is still drawn along the top of the highway. The bar above the highway says how sure the app is, names the other possible key (a song in C major could also be A minor), and lets you choose the key yourself. This is a best guess from the audio: folk and modal songs are matched to the nearest major or minor key, and rarer chords are shown as the simpler triad.
- **Chords by (other chord guessers):** The **Chords by** list above the highway chooses who guesses the chords. **Stems Studio** (the default) is the app's own two passes described above. The others are well-known chord finders from research, offered so you can compare them on your songs: [Chordino](https://github.com/c4dm/nnls-chroma) (Mauch & Dixon: NNLS chroma and a chord HMM), [madmom](https://github.com/CPJKU/madmom) (Korzeniowski & Widmer: a deep chroma network and a CRF), [autochord](https://github.com/cjbayron/autochord) (NNLS chroma into a bi-LSTM-CRF) and [BTC](https://github.com/jayg996/BTC-ISMIR19) (Park et al.: a bi-directional transformer; it also names 7ths, sus, dim and slash chords). Each one hears the song without the vocal and the drums (the bass, guitar, piano and other stems added together), and its chords are drawn as it heard them, without the bass check. madmom and BTC use the graphics card the stems use (an NVIDIA card, or a Mac's own GPU) and the CPU on computers without one; Chordino and autochord are quick on the CPU. Reading a song takes a few seconds with any of them; the answer is kept with the song in `chords-<guesser>.json`, so switching back is instant. A pasted chord sheet still comes first. The four are an optional install (under 100 MB, see below); until then the list marks them *not installed* and the app's own chords are shown. madmom's trained models are free for non-commercial use only.
- **Karaoke Lyrics:** When the lyrics are timed, four lines sit under the highway: the line just sung, the line being sung (it fills in as it goes), and the next two. Click a line to jump to it. Lyrics without timing stay as a scrolling list. They come from the song file's own tags (FLAC, MP3, M4A) when it has them. If it does not, or the song came from an online stream, Stems Studio looks it up on [LRCLIB](https://lrclib.net), a free lyrics database with timed lyrics. If the timing is a little off for your version, use the `-0.5s` / `+0.5s` buttons. If it found the wrong song, use **Find lyrics** to search by artist and title.
- **Other Instruments on the Highway:** The **Show** list above the highway picks which stem it follows. *Vocals*, *Bass* and *Lead guitar* are shown as one line, found with the same pitch detector. The bass search goes down to the 5-string bass's low B (31 Hz). The detector's own floor is about 47 Hz, so a second reader follows the repeating period and keeps a lower octave only when that lower note is actually in the sound. A note in the middle of the bass stays there: the reader no longer replaces it with a fake lower period, which used to leave the highway saying it could not read the bass. A real higher note is left where it is. A low B recorded with almost no fundamental can still be reported an octave too high. Opening a song already in the library reads the bass line again; the stems are not separated again. *Piano*, *Rhythm guitar*, *Other* and *Guitar (chords)* are shown as a piano roll with a bar for every note that sounds, found with [Basic Pitch](https://github.com/spotify/basic-pitch) (Spotify, Apache-2.0; the small model is included in `separator/vendor/` and runs on the CPU through ONNX, no TensorFlow). The readout at the now line shows the notes sounding at that moment. Distorted guitar and busy mixes give stray and missing notes; the **Notes** slider hides the weakest guesses (fewer) or shows all of them (more).
- **Drum Hits:** Choose **Drums (hits)** in the **Show** list to see kick, snare, toms, hi-hat, ride and crash as hits scrolling towards the now line. If the drums are split into parts, each part is searched for hits on its own, which is fairly accurate. If not, the hits are guessed from three frequency bands of the whole drum track (low = kick, middle = snare, high = hi-hat) and the lane says it is approximate. It is only a display: the singing coach does not score it, and a very quiet or busy hit can be missed or doubled.
- **Rough voice (growls and screams):** The pitch detector is made for sung notes, so death-metal growls, screams and other harsh vocals used to leave the highway empty. When the vocal stem is loud but has no clean pitch, the app now makes a second, much more forgiving guess (it looks for the base pitch whose overtones line up best with the rough sound) and shows it as **dashed amber bars** and a dashed line. It switches on by itself when most of the loud vocal has no clean pitch (on the Cannibal Corpse test song about 29% of the song is shown, from almost nothing before); for other songs there is a **Rough voice (dashed)** tick box above the highway. Honest limits: a growl has hardly any pitch to find, so this is a guess at its low rumble, it can be an octave off, and short bars can wobble; it shows *when* and roughly *how low or high* the voice is. The singing coach does not score these bars, and the key and chords are worked out without them.
- **Key shifter and Fit my voice:** The **Key** control above the highway moves the song up or down by up to 12 semitones without changing its speed (and the **Speed** control no longer changes the key). Press **Fit my voice**, choose your voice (bass, baritone or tenor for a male voice; alto, mezzo-soprano or soprano for a female voice) and the app reads the range of the singer in the song and suggests the shift that puts it inside your comfortable range, so a song sung by a man can suit a woman and the other way round. The highway and the singing coach follow the new key. It uses a small open-source pitch shifter (SoundTouch, Mozilla Public License 2.0, included in `js/vendor`). The **drums are not shifted** (they have no key, and shifting them makes them sound soft and off): vocals, bass, guitar, piano and other stems are shifted, the drums are held back by the same fraction of a second so everything stays in time (your own recording is left unshifted too). Honest limits: big shifts (more than about 5 semitones) sound a little watery; the shifted sound arrives about 0.12 seconds late, which the app compensates for in the highway and the coach; a sound that is part of the full mix file (a song loaded as a single stem, not separated) is shifted entirely, since it cannot be split; the ranges are typical values for each voice type, not a measurement of your own voice.
- **Update check:** a few seconds after Stems Studio starts, it asks GitHub (with `git fetch`, so it uses the same sign-in as your git) whether the main copy is newer. If so, a small bar appears at the bottom with the list of changes and an **Update now** button. That button downloads the main copy and reopens the app, so the window is not left on the engine that was already running. It never updates by itself, never overwrites changes you made in the folder (it refuses if there are any), and tells you to run `Install.bat` again if the setup changed. It works only for a copy installed with git (cloned from the repository); a copy from a zip file, or a PC without git, simply shows nothing. It checks again every 6 hours while the app stays open. Set the environment variable `STEMS_STUDIO_NO_UPDATE_CHECK=1` to turn it off. On Windows the usual update is the **Update Stems Studio** shortcut: every time, it brings in the main copy, stops the old engine, and opens the new one.
- **Singing Coach:** Press **Sing along** under the highway and sing into the microphone. Your own pitch is drawn as a coloured line on the highway (green when you are close enough, amber and red when you drift), and the readout at the now line shows what you are singing, its sargam name and how many cents sharp or flat you are. **Level** sets how close counts as right (Beginner 50 cents and, by default, any octave; Medium 30; Advanced 15). Each note is outlined once it has passed: green for hit, amber for sung but off, red for missed. Phrases get a score and a tendency (a little flat, quite sharp...) and the notes you missed are named in sargam; click a phrase, or **Retry weakest phrase**, to loop it and try again. The best and last scores for each song are kept in that song's folder, so they stay with the library. Your voice type is kept on this computer. Practice tools: **Guide tone** plays a soft tone on the note you should sing; **Listen, then sing** uses the A/B loop (or the phrase at the playhead): the singer plays once, then goes quiet for your turn; the speed control slows a phrase down; and the **Pitch** control moves the highway's notes with it. **Headphones are strongly recommended**: with speakers the browser has to cancel the song out of the microphone, which can make held notes drop out. If your line always looks a little behind or ahead, move it with **Mic timing**. Note that the Pitch control changes the speed as well as the key (it is a varispeed), and that the coach follows one line at a time.
- **Interactive High-DPI Waveforms:** Click-to-seek, drag-to-scrub, real-time playhead, and played-region shading.
- **Track Mixing Controls:**
  - **Mute (M)** and **Solo (S)** buttons per channel.
  - Volume faders (-inf to +6 dB).
  - Live VU meters responding to audio energy.
- **Master Transport Controls:**
  - Digital timecode readout (`MM:SS.ms`).
  - **Speed / Tempo Engine:** `0.5x` to `1.5x` playback rate.
  - **Pitch Shifter:** `-12` to `+12` semitone real-time shifting.
  - **A/B Region Looper:** Set Loop In (A), Set Loop Out (B), with shaded loop window across all waveforms.
- **Mix switches** (only one of the first three can be on; click the lit one to turn it off; they do not move the volume sliders):
  - **Karaoke (K):** Mutes the vocals. Click again and they come back.
  - **Acapella:** Plays only the vocals. Click again and the other stems come back.
  - **Rhythm:** Plays only the drums (including the separate drum parts) and the bass. Click again and the rest come back.
  - **Reset:** Puts every stem volume back to the middle and clears mute and solo.
  - **Help**, at the right end of the top bar, explains the window. Escape closes it.
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
1. Load a song (Audio file, media stream, or demo)
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
1. Double-click **`Install.bat`**. It builds a private Python 3.12 environment in this folder (`.venv`, ignored by git), installs the GPU (CUDA) build of PyTorch when it finds an NVIDIA graphics card, installs the stem maker (several minutes the first time), and puts two shortcuts on your Desktop and in the Start menu: **Stems Studio**, and **Update Stems Studio** (the green arrow). It ends by printing which GPU the app will use. It is safe to run again whenever something needs repairing.
2. From then on, open **Stems Studio** from its shortcut. Closing its window quits the app. For every update, double-click **Update Stems Studio**. It closes the app if it is open, downloads the newest main copy, and opens it. You do not run `Install.bat` for that.

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

**Keeping the library on another drive (for example a network drive shared by several computers).** Open **My Library** and click **Change folder**, or create a file `settings.json` in that data folder containing `{"library_dir": "Z:\\Music\\Stems"}` (use your own folder), or set the environment variable `STEMS_STUDIO_LIBRARY` to the folder. When that variable is set, the button is hidden and the variable wins. The songs, stems and `library.db` then live there, and every computer pointed at the same folder sees the same songs. To move an existing library, close the app and copy the contents of the `library` folder in the data folder into the new folder first. If the folder cannot be reached when the app starts (the drive is off, for example), the app tells you and uses the computer's own library until it is back. Only the library is moved: the downloaded models stay on each computer. Update every computer that uses the same library to the same version of the app, since the song folder names changed (older versions looked for code-like names such as `d0d43c0c`). Two computers can open the library at once, but do not split or clean songs on both at the same moment.

If something goes wrong at startup, the details are in `stems-studio.log` in that folder.

### Setting it up on another computer
*(Last checked against the app on 2026-10-15. Not yet tried on a clean machine; Mac not tested. The update now refuses to reopen an older engine and loads the new page at a new address; that was checked with the decision tests, not by double-clicking the Windows shortcut. The library-folder button was checked against the engine; the folder window itself was not opened on Windows or Mac. The optional chord guessers were installed from scratch, and over the old TensorFlow layout (which was removed), on Linux only; there is no graphics card on the test machine, so the graphics-card path was checked only by forcing an unavailable card and watching it fall back to the CPU, and Apple's GPU has not been tried. BTC's sound reading was checked to give the same chords as librosa's on two songs. The Windows half-megabyte plugin download and the Windows and Mac fingerprints were checked, but the install has not been run on Windows or a Mac.)*

1. Install **Git**, **Chrome or Edge**, and **Python 3.12 from python.org** (`winget install Python.Python.3.12`, or the installer from python.org with "Add python.exe to PATH" ticked). Use the python.org one, not a Python that another tool fetched: Windows' **Smart App Control** blocks programs that are not digitally signed, and the python.org Python is signed by the Python Software Foundation while the uv-fetched one that `Install.bat` falls back to is not (on one PC it was blocked, and the shortcut did nothing). The optional cleaner-vocals and drum-splitting tool is started through its own python.exe (also signed) rather than the unsigned `audio-separator.exe` stub that pip makes. If Smart App Control is on and a program still gets blocked, the Windows Security app lists it under *App & browser control*.
2. Clone or download the repository using Git:
   ```bash
   git clone https://github.com/Zither-Labs/stems-studio.git C:\Music\StemsStudio
   ```
   *(Any folder works; avoid OneDrive folders).* Do **not** copy the `.venv`, `.venv-roformer` or `.chord-tools` folders from another computer; they only work where they were made.
3. Double-click **`Install.bat`** (Mac: `Install.command`). It builds the app's own Python environment, installs the GPU version of PyTorch if there is an NVIDIA card (otherwise it runs on the CPU, slowly), the stem maker and the extras, offers the optional "cleaner vocals" and drum splitting, offers the optional "more chord guessers" (Chordino, madmom, autochord and BTC for the **Chords by** list: under 100 MB, all in `.chord-tools`), and makes the shortcuts. The chord guessers download sonic-annotator and the Chordino plugin (both digitally signed by the Sonic Visualiser team's company, which is what Smart App Control looks for; on Windows only the plugin's own half megabyte is fetched from the plugin pack), the madmom, autochord and BTC models, and three small Python packages (PyYAML, mido, packaging). They run with the app's own Python and PyTorch, so they work on every computer the app does, Intel Macs included, and need no C compiler. A computer that installed the earlier, larger chord guessers has a `.venv-chords` folder with TensorFlow in it (about 1.4 GB): the next run of Install removes it and asks to install the guessers again, which takes under a minute. Install keeps asking about the chord guessers until all four are ready, and only installs the missing ones; `python tools/install_chord_guessers.py btc` reinstalls one by hand. **Update** does not install them; run `Install.bat` once more after updating to get them. On Windows those are **Stems Studio** and **Update Stems Studio** (the green arrow), on the Desktop and in the Start menu. The first time takes several minutes; safe to run again.
4. Open **Stems Studio** from the shortcut. The first split downloads the separation model.
5. **To see the same songs as another computer**, open **My Library** and click **Change folder**. Choose the folder that contains `library.db` (the drive has to be connected). The app remembers it in `%LOCALAPPDATA%\StemsStudio\settings.json`. The same file can still be written by hand, as `{"library_dir": "Z:\\Music\\Stems"}`. Without this, each computer has its own library, starting empty. If `STEMS_STUDIO_LIBRARY` is set, that folder is used and the button is hidden.
6. Updates: on Windows, double-click **Update Stems Studio** on the Desktop. That is the update step every time: it closes the app, downloads the newest main copy, and opens that copy. If an older engine is still running, the new launch stops it and opens a new window on the new page, instead of bringing the old window back. The **Update now** bar inside the app does the same download and then reopens. Keep every computer that shares a library on the same version.


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

---

## ⚖️ Disclaimer & Fair Use

Stems Studio is developed strictly as a personal practice, research, and educational workstation. It is intended for use with audio tracks that you own, have created, or have received explicit rights or permission to process and study. Media stream extraction capabilities rely on external third-party open-source utilities (`yt-dlp`); users are solely responsible for respecting the terms of service of any third-party content platforms, adhering to fair use limitations, and complying with all applicable copyright laws in their jurisdiction.

---

## 📄 License

This project is licensed under the **MIT License** — see the [LICENSE](LICENSE) file for details. Third-party models and components retain their respective licenses (Basic Pitch: Apache-2.0, SoundTouchJS: MPL-2.0, Demucs: MIT).
