/**
 * Stems Studio - Main Application Controller
 * Handles UI interactions, track rendering, transport updates, drag & drop, and animations.
 */

document.addEventListener('DOMContentLoaded', () => {
  const engine = new AudioEngine();
  let animationFrameId = null;

  // DOM Elements
  const tracksRack = document.getElementById('tracksRack');
  const playToggleBtn = document.getElementById('playToggleBtn');
  const rewindBtn = document.getElementById('rewindBtn');
  const stopBtn = document.getElementById('stopBtn');
  const currentTimeEl = document.getElementById('currentTime');
  const totalTimeEl = document.getElementById('totalTime');

  const scrubberTrack = document.getElementById('scrubberTrack');
  const scrubberProgress = document.getElementById('scrubberProgress');
  const scrubberPlayhead = document.getElementById('scrubberPlayhead');
  const scrubberLoopOverlay = document.getElementById('scrubberLoopOverlay');

  const speedSelect = document.getElementById('speedSelect');
  const pitchValEl = document.getElementById('pitchVal');
  const pitchDownBtn = document.getElementById('pitchDownBtn');
  const pitchUpBtn = document.getElementById('pitchUpBtn');

  const loopToggleBtn = document.getElementById('loopToggleBtn');
  const setLoopInBtn = document.getElementById('setLoopInBtn');
  const setLoopOutBtn = document.getElementById('setLoopOutBtn');
  const clearLoopBtn = document.getElementById('clearLoopBtn');

  const masterFader = document.getElementById('masterFader');
  const masterFaderVal = document.getElementById('masterFaderVal');
  const masterMeterL = document.getElementById('masterMeterL');
  const masterMeterR = document.getElementById('masterMeterR');

  const btnLoadDemo = document.getElementById('btnLoadDemo');
  const btnImportStems = document.getElementById('btnImportStems');
  const fileInputHidden = document.getElementById('fileInputHidden');
  const dropzoneModal = document.getElementById('dropzoneModal');
  const modalCloseBtn = document.getElementById('modalCloseBtn');
  const dropzoneBox = document.getElementById('dropzoneBox');

  const btnExportMix = document.getElementById('btnExportMix');
  const btnExportKaraoke = document.getElementById('btnExportKaraoke');
  const btnExportAcapella = document.getElementById('btnExportAcapella');
  const exportLoopOnlyCheckbox = document.getElementById('exportLoopOnly');

  const btnPresetKaraoke = document.getElementById('btnPresetKaraoke');
  const btnPresetAcapella = document.getElementById('btnPresetAcapella');
  const btnPresetRhythm = document.getElementById('btnPresetRhythm');
  const btnPresetReset = document.getElementById('btnPresetReset');

  const btnSaveSession = document.getElementById('btnSaveSession');
  const btnLoadSession = document.getElementById('btnLoadSession');
  const sessionFileInput = document.getElementById('sessionFileInput');

  // Track configurations default list
  const defaultTrackDefs = [
    { id: 'vocal', name: 'Vocals', stemType: 'vocal' },
    { id: 'drums', name: 'Drums', stemType: 'drums' },
    { id: 'bass', name: 'Bass', stemType: 'bass' },
    { id: 'other', name: 'Instruments', stemType: 'other' }
  ];

  // Initialize track models in audio engine
  defaultTrackDefs.forEach(def => {
    engine.addTrack(def.id, def.name, def.stemType, null);
  });

  // Render Track DOM Cards
  function renderAllTrackCards() {
    tracksRack.innerHTML = '';
    for (const track of engine.tracks.values()) {
      const card = createTrackCardElement(track);
      tracksRack.appendChild(card);
    }
  }

  function createTrackCardElement(track) {
    const card = document.createElement('div');
    card.className = `track-card active-stem-${track.stemType}`;
    card.id = `trackCard_${track.id}`;

    const iconChars = {
      vocal: 'MIC',
      drums: 'DRM',
      bass: 'BAS',
      other: 'INS',
      custom: 'STM'
    };
    const iconChar = iconChars[track.stemType] || 'STM';

    card.innerHTML = `
      <div class="track-mixer-strip">
        <div class="track-header-meta">
          <div class="track-identity">
            <div class="stem-badge-icon stem-${track.stemType}-icon">${iconChar}</div>
            <input type="text" class="track-name-input" value="${track.name}" data-track-id="${track.id}">
          </div>
          <div class="track-strip-buttons">
            <button class="btn-mute ${track.isMuted ? 'active' : ''}" data-track-id="${track.id}" title="Mute Track (M)">M</button>
            <button class="btn-solo ${track.isSoloed ? 'active' : ''}" data-track-id="${track.id}" title="Solo Track (S)">S</button>
          </div>
        </div>

        <div class="fader-group">
          <div class="slider-row">
            <span class="slider-label">VOL</span>
            <input type="range" class="studio-slider track-vol-slider" min="0" max="1.5" step="0.01" value="${track.volume}" data-track-id="${track.id}">
            <span class="slider-readout" id="volReadout_${track.id}">0.0 dB</span>
          </div>

          <div class="slider-row">
            <span class="slider-label">PAN</span>
            <input type="range" class="studio-slider track-pan-slider" min="-1" max="1" step="0.02" value="${track.pan}" data-track-id="${track.id}">
            <span class="slider-readout" id="panReadout_${track.id}">C</span>
          </div>

          <div class="track-vu-container">
            <div class="vu-meter-bar">
              <div class="vu-meter-fill" id="vuFill_${track.id}"></div>
            </div>
            <div class="vu-clip-dot" id="vuClip_${track.id}"></div>
          </div>
        </div>
      </div>

      <div class="track-waveform-zone" data-track-id="${track.id}">
        <canvas class="track-canvas" id="canvas_${track.id}"></canvas>
        <div class="track-playhead-line" id="playhead_${track.id}"></div>
        <div class="track-loop-highlight" id="loopHigh_${track.id}"></div>
        <div class="track-empty-state" id="emptyState_${track.id}" style="${track.buffer ? 'display:none;' : ''}">
          <svg viewBox="0 0 24 24" fill="none" stroke-width="1.5"><path d="M9 18V5l12-2v13M9 9l12-2M9 18a3 3 0 11-6 0 3 3 0 016 0zm12-2a3 3 0 11-6 0 3 3 0 016 0z"/></svg>
          <span>Drop audio or click Demo to load ${track.name}</span>
        </div>
      </div>
    `;

    // Bind event listeners for this track card
    const nameInput = card.querySelector('.track-name-input');
    nameInput.addEventListener('change', (e) => {
      track.name = e.target.value.trim() || track.name;
    });

    const muteBtn = card.querySelector('.btn-mute');
    muteBtn.addEventListener('click', () => {
      const isMuted = engine.toggleTrackMute(track.id);
      muteBtn.classList.toggle('active', isMuted);
    });

    const soloBtn = card.querySelector('.btn-solo');
    soloBtn.addEventListener('click', () => {
      const isSoloed = engine.toggleTrackSolo(track.id);
      soloBtn.classList.toggle('active', isSoloed);
    });

    const volSlider = card.querySelector('.track-vol-slider');
    const volReadout = card.querySelector(`#volReadout_${track.id}`);
    volSlider.addEventListener('input', (e) => {
      const val = parseFloat(e.target.value);
      engine.setTrackVolume(track.id, val);
      volReadout.textContent = formatDb(val);
    });

    const panSlider = card.querySelector('.track-pan-slider');
    const panReadout = card.querySelector(`#panReadout_${track.id}`);
    panSlider.addEventListener('input', (e) => {
      const val = parseFloat(e.target.value);
      engine.setTrackPan(track.id, val);
      panReadout.textContent = formatPan(val);
    });

    // Waveform click to seek
    const waveZone = card.querySelector('.track-waveform-zone');
    waveZone.addEventListener('click', (e) => {
      const rect = waveZone.getBoundingClientRect();
      const clickRatio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
      const targetSec = clickRatio * engine.totalDuration;
      engine.seek(targetSec);
    });

    return card;
  }

  function formatDb(val) {
    if (val <= 0.001) return '-inf dB';
    const db = 20 * Math.log10(val);
    return `${db >= 0 ? '+' : ''}${db.toFixed(1)} dB`;
  }

  function formatPan(val) {
    if (Math.abs(val) < 0.05) return 'C';
    if (val < 0) return `L${Math.round(Math.abs(val) * 100)}%`;
    return `R${Math.round(val * 100)}%`;
  }

  function formatTime(seconds) {
    if (isNaN(seconds) || seconds < 0) seconds = 0;
    const mins = Math.floor(seconds / 60);
    const secs = Math.floor(seconds % 60);
    const ms = Math.floor((seconds % 1) * 100);
    return `${String(mins).padStart(2, '0')}:${String(secs).padStart(2, '0')}.${String(ms).padStart(2, '0')}`;
  }

  // Update waveforms and canvases
  function redrawAllWaveforms() {
    const curTime = engine.getCurrentTime();
    const total = engine.totalDuration || 1;
    const progress = curTime / total;

    for (const track of engine.tracks.values()) {
      const canvas = document.getElementById(`canvas_${track.id}`);
      if (canvas && track.peaks) {
        const loopSpec = engine.isLooping ? {
          enabled: true,
          start: engine.loopStart / total,
          end: engine.loopEnd / total
        } : null;
        WaveformRenderer.renderTrackWaveform(canvas, track.peaks, track.stemType, progress, loopSpec);
      }
    }
  }

  // Real-time animation frame loop (Clock, Scrubber, Meters, Waveform playhead)
  function startAnimationLoop() {
    function update() {
      const curTime = engine.getCurrentTime();
      const total = engine.totalDuration || 0;
      const progress = total > 0 ? (curTime / total) : 0;

      // Digital Clock
      currentTimeEl.textContent = formatTime(curTime);
      totalTimeEl.textContent = formatTime(total);

      // Scrubber
      scrubberProgress.style.width = `${progress * 100}%`;
      scrubberPlayhead.style.left = `${progress * 100}%`;

      if (engine.isLooping && total > 0) {
        scrubberLoopOverlay.style.display = 'block';
        scrubberLoopOverlay.style.left = `${(engine.loopStart / total) * 100}%`;
        scrubberLoopOverlay.style.width = `${((engine.loopEnd - engine.loopStart) / total) * 100}%`;
      } else {
        scrubberLoopOverlay.style.display = 'none';
      }

      // Track VU Meters
      for (const track of engine.tracks.values()) {
        const levels = engine.getTrackLevels(track.id);
        const vuFill = document.getElementById(`vuFill_${track.id}`);
        const vuClip = document.getElementById(`vuClip_${track.id}`);
        if (vuFill) {
          vuFill.style.width = `${Math.min(100, levels.peak * 110)}%`;
        }
        if (vuClip) {
          vuClip.classList.toggle('clipping', levels.clip);
        }
      }

      // Master Stereo VU Meters
      const masterLevels = engine.getMasterLevels();
      if (masterMeterL) masterMeterL.style.width = `${Math.min(100, masterLevels.left * 100)}%`;
      if (masterMeterR) masterMeterR.style.width = `${Math.min(100, masterLevels.right * 100)}%`;

      // Redraw waveforms
      redrawAllWaveforms();

      animationFrameId = requestAnimationFrame(update);
    }
    cancelAnimationFrame(animationFrameId);
    animationFrameId = requestAnimationFrame(update);
  }

  // Transport Control Events
  playToggleBtn.addEventListener('click', async () => {
    if (engine.isPlaying) {
      engine.pause();
    } else {
      await engine.play();
    }
  });

  rewindBtn.addEventListener('click', () => {
    engine.seek(0);
  });

  stopBtn.addEventListener('click', () => {
    engine.stop();
  });

  scrubberTrack.addEventListener('click', (e) => {
    const rect = scrubberTrack.getBoundingClientRect();
    const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    engine.seek(ratio * engine.totalDuration);
  });

  speedSelect.addEventListener('change', (e) => {
    engine.setPlaybackRate(parseFloat(e.target.value));
  });

  pitchDownBtn.addEventListener('click', () => {
    const newPitch = Math.max(-12, engine.pitchSemitones - 1);
    engine.setPitchSemitones(newPitch);
    pitchValEl.textContent = `${newPitch >= 0 ? '+' : ''}${newPitch} st`;
  });

  pitchUpBtn.addEventListener('click', () => {
    const newPitch = Math.min(12, engine.pitchSemitones + 1);
    engine.setPitchSemitones(newPitch);
    pitchValEl.textContent = `${newPitch >= 0 ? '+' : ''}${newPitch} st`;
  });

  // Looping Events
  loopToggleBtn.addEventListener('click', () => {
    const nextState = !engine.isLooping;
    engine.setLoop(nextState);
    loopToggleBtn.classList.toggle('active', nextState);
    showToast(nextState ? 'Loop region active' : 'Loop disabled', 'info');
  });

  setLoopInBtn.addEventListener('click', () => {
    const pos = engine.getCurrentTime();
    engine.setLoop(true, pos, engine.loopEnd > pos ? engine.loopEnd : pos + 4);
    loopToggleBtn.classList.add('active');
    showToast(`Loop In set: ${formatTime(pos)}`, 'info');
  });

  setLoopOutBtn.addEventListener('click', () => {
    const pos = engine.getCurrentTime();
    if (pos > engine.loopStart) {
      engine.setLoop(true, engine.loopStart, pos);
      loopToggleBtn.classList.add('active');
      showToast(`Loop Out set: ${formatTime(pos)}`, 'info');
    }
  });

  clearLoopBtn.addEventListener('click', () => {
    engine.setLoop(false, 0, engine.totalDuration);
    loopToggleBtn.classList.remove('active');
    showToast('Loop markers cleared', 'info');
  });

  masterFader.addEventListener('input', (e) => {
    const val = parseFloat(e.target.value);
    engine.setMasterVolume(val);
    masterFaderVal.textContent = formatDb(val);
  });

  // Presets
  btnPresetKaraoke.addEventListener('click', () => {
    const vocalTrack = engine.tracks.get('vocal');
    if (!vocalTrack) return;
    vocalTrack.isMuted = true;
    engine.updateMuteSoloStates();
    syncMuteSoloButtons();
    showToast('Karaoke Mode: Vocals Muted', 'success');
  });

  btnPresetAcapella.addEventListener('click', () => {
    for (const track of engine.tracks.values()) {
      track.isSoloed = (track.id === 'vocal');
      track.isMuted = false;
    }
    engine.updateMuteSoloStates();
    syncMuteSoloButtons();
    showToast('Acapella Mode: Solo Vocals', 'success');
  });

  btnPresetRhythm.addEventListener('click', () => {
    for (const track of engine.tracks.values()) {
      track.isSoloed = (track.id === 'drums' || track.id === 'bass');
      track.isMuted = false;
    }
    engine.updateMuteSoloStates();
    syncMuteSoloButtons();
    showToast('Rhythm Mode: Solo Drums & Bass', 'success');
  });

  btnPresetReset.addEventListener('click', () => {
    for (const track of engine.tracks.values()) {
      track.isMuted = false;
      track.isSoloed = false;
      track.volume = 1.0;
      track.pan = 0;
      engine.setTrackVolume(track.id, 1.0);
      engine.setTrackPan(track.id, 0);
    }
    engine.updateMuteSoloStates();
    renderAllTrackCards();
    showToast('All track levels reset to default', 'info');
  });

  function syncMuteSoloButtons() {
    for (const track of engine.tracks.values()) {
      const card = document.getElementById(`trackCard_${track.id}`);
      if (card) {
        const mBtn = card.querySelector('.btn-mute');
        const sBtn = card.querySelector('.btn-solo');
        if (mBtn) mBtn.classList.toggle('active', track.isMuted);
        if (sBtn) sBtn.classList.toggle('active', track.isSoloed);
      }
    }
  }

  // Load Built-in Demo Stems
  btnLoadDemo.addEventListener('click', async () => {
    showToast('Synthesizing studio multi-track demo stems...', 'info');
    btnLoadDemo.disabled = true;
    btnLoadDemo.textContent = 'Generating...';

    try {
      await engine.resume();
      const demoStems = await DemoStemGenerator.generateDemoStems(engine.ctx);

      engine.setTrackBuffer('vocal', demoStems.vocal);
      engine.setTrackBuffer('drums', demoStems.drums);
      engine.setTrackBuffer('bass', demoStems.bass);
      engine.setTrackBuffer('other', demoStems.other);

      // Hide empty states
      document.querySelectorAll('.track-empty-state').forEach(el => el.style.display = 'none');
      redrawAllWaveforms();
      showToast('Demo stems loaded! Press Play or Spacebar.', 'success');
    } catch (err) {
      console.error(err);
      showToast('Error generating demo stems: ' + err.message, 'error');
    } finally {
      btnLoadDemo.disabled = false;
      btnLoadDemo.innerHTML = `<svg viewBox="0 0 24 24"><path d="M5 3l14 9-14 9V3z"/></svg> Load Studio Demo`;
    }
  });

  // File Dropzone & Import
  btnImportStems.addEventListener('click', () => {
    dropzoneModal.classList.add('open');
  });

  modalCloseBtn.addEventListener('click', () => {
    dropzoneModal.classList.remove('open');
  });

  dropzoneModal.addEventListener('click', (e) => {
    if (e.target === dropzoneModal) dropzoneModal.classList.remove('open');
  });

  dropzoneBox.addEventListener('click', () => {
    fileInputHidden.click();
  });

  dropzoneBox.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropzoneBox.classList.add('drag-over');
  });

  dropzoneBox.addEventListener('dragleave', () => {
    dropzoneBox.classList.remove('drag-over');
  });

  dropzoneBox.addEventListener('drop', (e) => {
    e.preventDefault();
    dropzoneBox.classList.remove('drag-over');
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      handleImportFiles(e.dataTransfer.files);
    }
  });

  fileInputHidden.addEventListener('change', (e) => {
    if (e.target.files && e.target.files.length > 0) {
      handleImportFiles(e.target.files);
    }
  });

  async function handleImportFiles(files) {
    dropzoneModal.classList.remove('open');
    await engine.resume();
    showToast(`Decoding ${files.length} audio file(s)...`, 'info');

    for (let i = 0; i < files.length; i++) {
      const file = files[i];
      try {
        const arrayBuf = await file.arrayBuffer();
        const audioBuffer = await engine.ctx.decodeAudioData(arrayBuf);

        // Detect stem type from filename
        const nameLower = file.name.toLowerCase();
        let targetId = 'other';
        if (nameLower.includes('vocal') || nameLower.includes('voice') || nameLower.includes('lead') || nameLower.includes('sing')) {
          targetId = 'vocal';
        } else if (nameLower.includes('drum') || nameLower.includes('beat') || nameLower.includes('perc')) {
          targetId = 'drums';
        } else if (nameLower.includes('bass') || nameLower.includes('808') || nameLower.includes('sub')) {
          targetId = 'bass';
        } else if (nameLower.includes('other') || nameLower.includes('inst') || nameLower.includes('music') || nameLower.includes('back')) {
          targetId = 'other';
        }

        let track = engine.tracks.get(targetId);
        if (!track) {
          track = engine.addTrack(targetId, file.name.replace(/\.[^/.]+$/, ""), targetId, audioBuffer);
          renderAllTrackCards();
        } else {
          track.name = file.name.replace(/\.[^/.]+$/, "");
          engine.setTrackBuffer(targetId, audioBuffer);
          const nameInput = document.querySelector(`#trackCard_${targetId} .track-name-input`);
          if (nameInput) nameInput.value = track.name;
          const emptyState = document.getElementById(`emptyState_${targetId}`);
          if (emptyState) emptyState.style.display = 'none';
        }

        showToast(`Loaded "${file.name}" as ${track.name}`, 'success');
      } catch (err) {
        console.error(err);
        showToast(`Could not decode "${file.name}": ${err.message}`, 'error');
      }
    }
    redrawAllWaveforms();
  }

  // Export Mixdown Handlers
  async function runExport(mode) {
    if (engine.totalDuration <= 0) {
      showToast('No audio loaded to export.', 'error');
      return;
    }

    const loopOnly = exportLoopOnlyCheckbox.checked;
    showToast(`Rendering ${mode} mixdown...`, 'info');

    try {
      const blob = await ExportEngine.renderMix(engine.tracks, engine.totalDuration, {
        mode,
        loopOnly,
        loopStart: engine.loopStart,
        loopEnd: engine.loopEnd
      });

      const dateStr = new Date().toISOString().slice(0, 10);
      const filename = `StemsStudio_${mode}_${dateStr}.wav`;
      ExportEngine.triggerDownload(blob, filename);
      showToast(`Exported ${filename}!`, 'success');
    } catch (err) {
      console.error(err);
      showToast('Export failed: ' + err.message, 'error');
    }
  }

  btnExportMix.addEventListener('click', () => runExport('full'));
  btnExportKaraoke.addEventListener('click', () => runExport('karaoke'));
  btnExportAcapella.addEventListener('click', () => runExport('acapella'));

  // Session Save & Load
  btnSaveSession.addEventListener('click', () => {
    const sessionData = {
      version: 1,
      timestamp: Date.now(),
      playbackRate: engine.playbackRate,
      pitchSemitones: engine.pitchSemitones,
      loop: {
        enabled: engine.isLooping,
        start: engine.loopStart,
        end: engine.loopEnd
      },
      tracks: []
    };

    for (const track of engine.tracks.values()) {
      sessionData.tracks.push({
        id: track.id,
        name: track.name,
        stemType: track.stemType,
        volume: track.volume,
        pan: track.pan,
        isMuted: track.isMuted,
        isSoloed: track.isSoloed
      });
    }

    const blob = new Blob([JSON.stringify(sessionData, null, 2)], { type: 'application/json' });
    ExportEngine.triggerDownload(blob, 'session.stems-studio.json');
    showToast('Session saved to file', 'success');
  });

  btnLoadSession.addEventListener('click', () => {
    sessionFileInput.click();
  });

  sessionFileInput.addEventListener('change', async (e) => {
    if (!e.target.files || e.target.files.length === 0) return;
    const file = e.target.files[0];
    try {
      const text = await file.text();
      const session = JSON.parse(text);

      if (session.playbackRate) {
        engine.setPlaybackRate(session.playbackRate);
        speedSelect.value = String(session.playbackRate);
      }
      if (session.pitchSemitones !== undefined) {
        engine.setPitchSemitones(session.pitchSemitones);
        pitchValEl.textContent = `${session.pitchSemitones >= 0 ? '+' : ''}${session.pitchSemitones} st`;
      }
      if (session.loop) {
        engine.setLoop(session.loop.enabled, session.loop.start, session.loop.end);
        loopToggleBtn.classList.toggle('active', session.loop.enabled);
      }
      if (session.tracks && Array.isArray(session.tracks)) {
        session.tracks.forEach(tData => {
          const track = engine.tracks.get(tData.id);
          if (track) {
            track.name = tData.name || track.name;
            track.volume = tData.volume !== undefined ? tData.volume : 1.0;
            track.pan = tData.pan !== undefined ? tData.pan : 0;
            track.isMuted = !!tData.isMuted;
            track.isSoloed = !!tData.isSoloed;
            engine.setTrackVolume(track.id, track.volume);
            engine.setTrackPan(track.id, track.pan);
          }
        });
        engine.updateMuteSoloStates();
        renderAllTrackCards();
      }
      showToast('Session restored successfully!', 'success');
    } catch (err) {
      showToast('Invalid session JSON: ' + err.message, 'error');
    }
  });

  // Global Keyboard Shortcuts
  window.addEventListener('keydown', (e) => {
    // Ignore keystrokes inside text inputs
    if (['INPUT', 'SELECT', 'TEXTAREA'].includes(e.target.tagName)) return;

    if (e.code === 'Space') {
      e.preventDefault();
      playToggleBtn.click();
    } else if (e.code === 'Enter' || e.code === 'Home') {
      e.preventDefault();
      engine.seek(0);
    } else if (e.code === 'KeyL') {
      e.preventDefault();
      loopToggleBtn.click();
    } else if (e.code === 'KeyK') {
      e.preventDefault();
      btnPresetKaraoke.click();
    } else if (e.code === 'Escape') {
      dropzoneModal.classList.remove('open');
    }
  });

  // Toast Notification System
  function showToast(message, type = 'info') {
    let container = document.getElementById('toastContainer');
    if (!container) {
      container = document.createElement('div');
      container.id = 'toastContainer';
      container.className = 'toast-container';
      document.body.appendChild(container);
    }

    const toast = document.createElement('div');
    toast.className = `toast ${type}`;
    toast.textContent = message;
    container.appendChild(toast);

    setTimeout(() => {
      toast.style.opacity = '0';
      toast.style.transform = 'translateX(100%)';
      toast.style.transition = 'all 0.3s ease';
      setTimeout(() => toast.remove(), 300);
    }, 3200);
  }

  // Handle Playback State changes from engine
  engine.on('playbackStateChanged', (playing) => {
    if (playing) {
      playToggleBtn.innerHTML = `<svg viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>`;
      playToggleBtn.title = "Pause (Space)";
    } else {
      playToggleBtn.innerHTML = `<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>`;
      playToggleBtn.title = "Play (Space)";
    }
  });

  // Initial render
  renderAllTrackCards();
  startAnimationLoop();
});
