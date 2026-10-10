/**
 * Stems Studio - Main Application Controller
 * Handles Song Intake (YouTube URL / Audio File / Demo), AI Stem Separation,
 * 6-Stem Nepali Folk & Acoustic profiles, multi-track mixing, and waveforms.
 */

document.addEventListener('DOMContentLoaded', () => {
  const engine = new AudioEngine();
  let animationFrameId = null;

  // DOM Elements - Transport & Master
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

  // Intake Hero Elements
  const tabBtnYoutube = document.getElementById('tabBtnYoutube');
  const tabBtnUpload = document.getElementById('tabBtnUpload');
  const tabBtnDemo = document.getElementById('tabBtnDemo');
  const paneYoutube = document.getElementById('paneYoutube');
  const paneUpload = document.getElementById('paneUpload');
  const paneDemo = document.getElementById('paneDemo');

  const inputYoutubeUrl = document.getElementById('inputYoutubeUrl');
  const btnStartSeparationYoutube = document.getElementById('btnStartSeparationYoutube');

  const fileUploadStrip = document.getElementById('fileUploadStrip');
  const uploadFileName = document.getElementById('uploadFileName');
  const btnBrowseSingleFile = document.getElementById('btnBrowseSingleFile');
  const inputSingleAudioFile = document.getElementById('inputSingleAudioFile');
  const btnStartSeparationFile = document.getElementById('btnStartSeparationFile');

  const btnLoad6StemDemo = document.getElementById('btnLoad6StemDemo');
  const btnLoadDemo = document.getElementById('btnLoadDemo');

  const modelPillNepali = document.getElementById('modelPillNepali');
  const modelPillStd6s = document.getElementById('modelPillStd6s');
  const modelPillStd4s = document.getElementById('modelPillStd4s');

  const separationProgressCard = document.getElementById('separationProgressCard');
  const progressMessage = document.getElementById('progressMessage');
  const progressPercent = document.getElementById('progressPercent');
  const progressBarFill = document.getElementById('progressBarFill');

  // Presets & Modal
  const btnPresetKaraoke = document.getElementById('btnPresetKaraoke');
  const btnPresetAcapella = document.getElementById('btnPresetAcapella');
  const btnPresetRhythm = document.getElementById('btnPresetRhythm');
  const btnPresetReset = document.getElementById('btnPresetReset');

  const btnExportMix = document.getElementById('btnExportMix');
  const btnExportKaraoke = document.getElementById('btnExportKaraoke');
  const btnExportAcapella = document.getElementById('btnExportAcapella');
  const exportLoopOnlyCheckbox = document.getElementById('exportLoopOnly');

  const btnImportStems = document.getElementById('btnImportStems');
  const fileInputHidden = document.getElementById('fileInputHidden');
  const dropzoneModal = document.getElementById('dropzoneModal');
  const modalCloseBtn = document.getElementById('modalCloseBtn');
  const dropzoneBox = document.getElementById('dropzoneBox');

  const btnSaveSession = document.getElementById('btnSaveSession');
  const btnLoadSession = document.getElementById('btnLoadSession');
  const sessionFileInput = document.getElementById('sessionFileInput');

  // State: Current Model & Preset Selection
  let currentModel = 'htdemucs_6s';
  let currentPreset = 'nepali_folk';
  let selectedUploadFile = null;

  // Default 6-Stem Nepali Folk Definition
  const nepaliFolkTrackDefs = [
    { id: 'vocal', name: 'Vocals / स्वर', stemType: 'vocal' },
    { id: 'drums', name: 'Madal & Percussion / मादल', stemType: 'drums' },
    { id: 'other', name: 'Sarangi & Bansuri / सारङ्गी-बाँसुरी', stemType: 'other' },
    { id: 'piano', name: 'Harmonium & Keys / हार्मोनियम', stemType: 'piano' },
    { id: 'guitar', name: 'Acoustic Pluck / टुङ्ना-गितार', stemType: 'guitar' },
    { id: 'bass', name: 'Bass & Low-End / बास', stemType: 'bass' }
  ];

  // Initialize track models in audio engine
  function initializeTrackModels(defs) {
    engine.tracks.clear();
    defs.forEach(def => {
      engine.addTrack(def.id, def.name, def.stemType, null);
    });
    renderAllTrackCards();
  }

  initializeTrackModels(nepaliFolkTrackDefs);

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

    const iconSymbols = {
      vocal: '🎤',
      drums: '🪘',
      bass: '🔊',
      guitar: '🎸',
      piano: '🎹',
      other: '🎻',
      custom: '🎛️'
    };
    const iconSym = iconSymbols[track.stemType] || '🎛️';

    card.innerHTML = `
      <div class="track-mixer-strip">
        <div class="track-header-meta">
          <div class="track-identity">
            <div class="stem-badge-icon stem-${track.stemType}-icon">${iconSym}</div>
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
          <span>Ready for separation: ${track.name}</span>
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

  // Animation frame loop
  function startAnimationLoop() {
    function update() {
      const curTime = engine.getCurrentTime();
      const total = engine.totalDuration || 0;
      const progress = total > 0 ? (curTime / total) : 0;

      currentTimeEl.textContent = formatTime(curTime);
      totalTimeEl.textContent = formatTime(total);

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
        if (vuFill) vuFill.style.width = `${Math.min(100, levels.peak * 110)}%`;
        if (vuClip) vuClip.classList.toggle('clipping', levels.clip);
      }

      // Master VU Meters
      const masterLevels = engine.getMasterLevels();
      if (masterMeterL) masterMeterL.style.width = `${Math.min(100, masterLevels.left * 100)}%`;
      if (masterMeterR) masterMeterR.style.width = `${Math.min(100, masterLevels.right * 100)}%`;

      redrawAllWaveforms();
      animationFrameId = requestAnimationFrame(update);
    }
    cancelAnimationFrame(animationFrameId);
    animationFrameId = requestAnimationFrame(update);
  }

  // =========================================================================
  // Intake Tabs & Model Selection
  // =========================================================================
  function switchIntakeTab(activeTab) {
    tabBtnYoutube.classList.toggle('active', activeTab === 'youtube');
    tabBtnUpload.classList.toggle('active', activeTab === 'upload');
    tabBtnDemo.classList.toggle('active', activeTab === 'demo');

    paneYoutube.style.display = activeTab === 'youtube' ? 'flex' : 'none';
    paneUpload.style.display = activeTab === 'upload' ? 'flex' : 'none';
    paneDemo.style.display = activeTab === 'demo' ? 'flex' : 'none';
  }

  tabBtnYoutube.addEventListener('click', () => switchIntakeTab('youtube'));
  tabBtnUpload.addEventListener('click', () => switchIntakeTab('upload'));
  tabBtnDemo.addEventListener('click', () => switchIntakeTab('demo'));

  // Stem Profile Pills
  function selectStemProfile(model, preset) {
    currentModel = model;
    currentPreset = preset;

    modelPillNepali.className = `preset-pill ${preset === 'nepali_folk' ? 'nepali-active' : ''}`;
    modelPillStd6s.className = `preset-pill ${preset === 'standard_6s' ? 'active' : ''}`;
    modelPillStd4s.className = `preset-pill ${preset === 'standard_4s' ? 'active' : ''}`;

    if (preset === 'nepali_folk') {
      showToast('Selected: 6 Stems (Nepali Folk & Acoustic: Madal, Sarangi, Flute, Harmonium, Pluck, Bass)', 'info');
    } else if (preset === 'standard_6s') {
      showToast('Selected: 6 Stems Standard (Vocals, Drums, Bass, Guitar, Piano, Other)', 'info');
    } else {
      showToast('Selected: 4 Stems Standard (Vocals, Drums, Bass, Other)', 'info');
    }
  }

  modelPillNepali.addEventListener('click', () => selectStemProfile('htdemucs_6s', 'nepali_folk'));
  modelPillStd6s.addEventListener('click', () => selectStemProfile('htdemucs_6s', 'standard_6s'));
  modelPillStd4s.addEventListener('click', () => selectStemProfile('htdemucs', 'standard_4s'));

  // File Upload Handlers
  btnBrowseSingleFile.addEventListener('click', () => inputSingleAudioFile.click());
  fileUploadStrip.addEventListener('click', (e) => {
    if (e.target !== btnBrowseSingleFile) inputSingleAudioFile.click();
  });

  inputSingleAudioFile.addEventListener('change', (e) => {
    if (e.target.files && e.target.files.length > 0) {
      selectedUploadFile = e.target.files[0];
      uploadFileName.textContent = `${selectedUploadFile.name} (${(selectedUploadFile.size / (1024 * 1024)).toFixed(1)} MB)`;
      btnStartSeparationFile.disabled = false;
      showToast(`Selected "${selectedUploadFile.name}"`, 'success');
    }
  });

  fileUploadStrip.addEventListener('dragover', (e) => {
    e.preventDefault();
    fileUploadStrip.classList.add('drag-over');
  });

  fileUploadStrip.addEventListener('dragleave', () => fileUploadStrip.classList.remove('drag-over'));

  fileUploadStrip.addEventListener('drop', (e) => {
    e.preventDefault();
    fileUploadStrip.classList.remove('drag-over');
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      selectedUploadFile = e.dataTransfer.files[0];
      uploadFileName.textContent = `${selectedUploadFile.name} (${(selectedUploadFile.size / (1024 * 1024)).toFixed(1)} MB)`;
      btnStartSeparationFile.disabled = false;
      showToast(`Selected "${selectedUploadFile.name}"`, 'success');
    }
  });

  // =========================================================================
  // AI Stem Separation Backend Integration
  // =========================================================================
  async function triggerSeparation(payload, isFormData = false) {
    separationProgressCard.style.display = 'block';
    progressPercent.textContent = '5%';
    progressBarFill.style.width = '5%';
    progressMessage.textContent = 'Contacting Stems Studio neural separation engine...';

    btnStartSeparationYoutube.disabled = true;
    btnStartSeparationFile.disabled = true;

    try {
      const headers = isFormData ? {} : { 'Content-Type': 'application/json' };
      const body = isFormData ? payload : JSON.stringify(payload);

      const resp = await fetch('/api/separate', {
        method: 'POST',
        headers,
        body
      });

      if (!resp.ok) {
        throw new Error(`Server returned error ${resp.status}`);
      }

      const initData = await resp.json();
      const jobId = initData.job_id;

      // Poll job progress
      await pollJobStatus(jobId);

    } catch (err) {
      console.error(err);
      progressMessage.textContent = `Error: ${err.message}. Make sure server.py or Run-Stems-Studio.bat is running!`;
      progressBarFill.style.background = '#ef4444';
      showToast(`Separation failed: ${err.message}`, 'error');
    } finally {
      btnStartSeparationYoutube.disabled = false;
      btnStartSeparationFile.disabled = selectedUploadFile === null;
    }
  }

  async function pollJobStatus(jobId) {
    const pollInterval = setInterval(async () => {
      try {
        const resp = await fetch(`/api/status?job_id=${jobId}`);
        const data = await resp.json();

        if (data.status === 'processing') {
          progressPercent.textContent = `${data.progress}%`;
          progressBarFill.style.width = `${data.progress}%`;
          progressMessage.textContent = data.message || 'Separating audio stems...';
        } else if (data.status === 'completed') {
          clearInterval(pollInterval);
          progressPercent.textContent = '100%';
          progressBarFill.style.width = '100%';
          progressMessage.textContent = 'Separation complete! Decoding and loading audio tracks...';

          await loadSeparatedStemsIntoMixer(data.stems);
          setTimeout(() => {
            separationProgressCard.style.display = 'none';
          }, 4000);
        } else if (data.status === 'error') {
          clearInterval(pollInterval);
          progressMessage.textContent = `Separation failed: ${data.error}`;
          progressBarFill.style.background = '#ef4444';
          showToast(`Error: ${data.error}`, 'error');
        }
      } catch (e) {
        console.error('Polling error', e);
      }
    }, 800);
  }

  async function loadSeparatedStemsIntoMixer(stemsList) {
    await engine.resume();
    engine.tracks.clear();

    for (const stem of stemsList) {
      try {
        const audioResp = await fetch(stem.url);
        const arrayBuf = await audioResp.arrayBuffer();
        const decodedBuf = await engine.ctx.decodeAudioData(arrayBuf);

        engine.addTrack(stem.id, stem.name, stem.stemType, decodedBuf);
      } catch (err) {
        console.error(`Error loading stem ${stem.name}`, err);
      }
    }

    renderAllTrackCards();
    document.querySelectorAll('.track-empty-state').forEach(el => el.style.display = 'none');
    redrawAllWaveforms();
    showToast('All separated stems loaded successfully into mixer!', 'success');

    // Auto-start playback
    await engine.play();
  }

  // Trigger from YouTube
  btnStartSeparationYoutube.addEventListener('click', () => {
    const url = inputYoutubeUrl.value.trim();
    if (!url) {
      showToast('Please enter a YouTube video URL.', 'error');
      inputYoutubeUrl.focus();
      return;
    }
    triggerSeparation({
      youtube_url: url,
      model: currentModel,
      preset: currentPreset
    });
  });

  // Trigger from Single Audio File
  btnStartSeparationFile.addEventListener('click', () => {
    if (!selectedUploadFile) {
      showToast('Please choose an audio file first.', 'error');
      return;
    }
    const formData = new FormData();
    formData.append('file', selectedUploadFile);
    formData.append('model', currentModel);
    formData.append('preset', currentPreset);
    triggerSeparation(formData, true);
  });

  // =========================================================================
  // Procedural Demo Stems
  // =========================================================================
  async function loadDemoStems(is6Stems = true) {
    showToast(`Synthesizing ${is6Stems ? '6-Stem Nepali Folk' : '4-Stem'} demo audio...`, 'info');
    btnLoad6StemDemo.disabled = true;
    btnLoadDemo.disabled = true;

    try {
      await engine.resume();
      const demoStems = await DemoStemGenerator.generateDemoStems(engine.ctx, is6Stems);

      engine.tracks.clear();

      if (is6Stems) {
        engine.addTrack('vocal', 'Vocals / स्वर', 'vocal', demoStems.vocal);
        engine.addTrack('drums', 'Madal & Percussion / मादल', 'drums', demoStems.drums);
        engine.addTrack('other', 'Sarangi & Bansuri / सारङ्गी-बाँसुरी', 'other', demoStems.other);
        engine.addTrack('piano', 'Harmonium & Keys / हार्मोनियम', 'piano', demoStems.piano);
        engine.addTrack('guitar', 'Acoustic Pluck / टुङ्ना-गितार', 'guitar', demoStems.guitar);
        engine.addTrack('bass', 'Bass & Low-End / बास', 'bass', demoStems.bass);
      } else {
        engine.addTrack('vocal', 'Vocals', 'vocal', demoStems.vocal);
        engine.addTrack('drums', 'Drums', 'drums', demoStems.drums);
        engine.addTrack('bass', 'Bass', 'bass', demoStems.bass);
        engine.addTrack('other', 'Instruments', 'other', demoStems.other);
      }

      renderAllTrackCards();
      document.querySelectorAll('.track-empty-state').forEach(el => el.style.display = 'none');
      redrawAllWaveforms();
      showToast('Demo stems loaded! Press Spacebar or Play.', 'success');
    } catch (err) {
      console.error(err);
      showToast('Error generating demo stems: ' + err.message, 'error');
    } finally {
      btnLoad6StemDemo.disabled = false;
      btnLoadDemo.disabled = false;
    }
  }

  btnLoad6StemDemo.addEventListener('click', () => loadDemoStems(true));
  btnLoadDemo.addEventListener('click', () => loadDemoStems(true));

  // =========================================================================
  // Transport & Playback Controls
  // =========================================================================
  playToggleBtn.addEventListener('click', async () => {
    if (engine.isPlaying) {
      engine.pause();
    } else {
      await engine.play();
    }
  });

  rewindBtn.addEventListener('click', () => engine.seek(0));
  stopBtn.addEventListener('click', () => engine.stop());

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

  // Looping
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
    if (vocalTrack) vocalTrack.isMuted = true;
    engine.updateMuteSoloStates();
    syncMuteSoloButtons();
    showToast('Karaoke: Vocals Muted (गायन बन्द)', 'success');
  });

  btnPresetAcapella.addEventListener('click', () => {
    for (const track of engine.tracks.values()) {
      track.isSoloed = (track.id === 'vocal');
      track.isMuted = false;
    }
    engine.updateMuteSoloStates();
    syncMuteSoloButtons();
    showToast('Acapella: Solo Vocals (स्वर मात्र)', 'success');
  });

  btnPresetRhythm.addEventListener('click', () => {
    for (const track of engine.tracks.values()) {
      track.isSoloed = (track.id === 'drums' || track.id === 'bass');
      track.isMuted = false;
    }
    engine.updateMuteSoloStates();
    syncMuteSoloButtons();
    showToast('Rhythm: Solo Madal, Drums & Bass (मादल र ताल मात्र)', 'success');
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

  // Multi-Stem Import Modal
  btnImportStems.addEventListener('click', () => dropzoneModal.classList.add('open'));
  modalCloseBtn.addEventListener('click', () => dropzoneModal.classList.remove('open'));
  dropzoneModal.addEventListener('click', (e) => {
    if (e.target === dropzoneModal) dropzoneModal.classList.remove('open');
  });
  dropzoneBox.addEventListener('click', () => fileInputHidden.click());

  dropzoneBox.addEventListener('dragover', (e) => {
    e.preventDefault();
    dropzoneBox.classList.add('drag-over');
  });
  dropzoneBox.addEventListener('dragleave', () => dropzoneBox.classList.remove('drag-over'));
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

        const nameLower = file.name.toLowerCase();
        let targetId = 'other';
        if (nameLower.includes('vocal') || nameLower.includes('voice') || nameLower.includes('lead') || nameLower.includes('sing')) {
          targetId = 'vocal';
        } else if (nameLower.includes('drum') || nameLower.includes('madal') || nameLower.includes('beat') || nameLower.includes('perc')) {
          targetId = 'drums';
        } else if (nameLower.includes('bass') || nameLower.includes('808') || nameLower.includes('sub')) {
          targetId = 'bass';
        } else if (nameLower.includes('guitar') || nameLower.includes('tungna') || nameLower.includes('acoustic')) {
          targetId = 'guitar';
        } else if (nameLower.includes('piano') || nameLower.includes('harmonium') || nameLower.includes('keys')) {
          targetId = 'piano';
        } else if (nameLower.includes('sarangi') || nameLower.includes('flute') || nameLower.includes('bansuri')) {
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
      version: 2,
      timestamp: Date.now(),
      model: currentModel,
      preset: currentPreset,
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

  btnLoadSession.addEventListener('click', () => sessionFileInput.click());

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
          let track = engine.tracks.get(tData.id);
          if (!track) {
            track = engine.addTrack(tData.id, tData.name, tData.stemType, null);
          }
          track.name = tData.name || track.name;
          track.volume = tData.volume !== undefined ? tData.volume : 1.0;
          track.pan = tData.pan !== undefined ? tData.pan : 0;
          track.isMuted = !!tData.isMuted;
          track.isSoloed = !!tData.isSoloed;
          engine.setTrackVolume(track.id, track.volume);
          engine.setTrackPan(track.id, track.pan);
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
    }, 3500);
  }

  // Engine playback state update
  engine.on('playbackStateChanged', (playing) => {
    if (playing) {
      playToggleBtn.innerHTML = `<svg viewBox="0 0 24 24"><path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/></svg>`;
      playToggleBtn.title = "Pause (Space)";
    } else {
      playToggleBtn.innerHTML = `<svg viewBox="0 0 24 24"><path d="M8 5v14l11-7z"/></svg>`;
      playToggleBtn.title = "Play (Space)";
    }
  });

  // Query Server Engine & GPU Status
  async function checkEngineStatus() {
    const gpuBadgeText = document.getElementById('gpuBadgeText');
    const gpuEngineBadge = document.getElementById('gpuEngineBadge');
    if (!gpuBadgeText || !gpuEngineBadge) return;

    try {
      const resp = await fetch('/api/engine');
      if (resp.ok) {
        const data = await resp.json();
        if (data.cuda_available) {
          gpuBadgeText.textContent = `⚡ GPU Active: ${data.device_name} (${data.vram_gb} GB VRAM)`;
          gpuEngineBadge.style.color = '#34d399';
          gpuEngineBadge.style.borderColor = 'rgba(16, 185, 129, 0.4)';
          gpuEngineBadge.title = `NVIDIA CUDA ${data.cuda_version || '12.6'} acceleration enabled on ${data.device_name}`;
        } else {
          gpuBadgeText.textContent = `⚙️ Engine: ${data.device_name} Mode`;
          gpuEngineBadge.style.color = '#f59e0b';
          gpuEngineBadge.style.borderColor = 'rgba(245, 158, 11, 0.3)';
        }
      }
    } catch (e) {
      gpuBadgeText.textContent = '⚡ Web Audio Mode (Offline)';
    }
  }

  checkEngineStatus();
  startAnimationLoop();

  // =========================================================================
  // Vocal Training Studio Module (Compact Sidebar Version)
  // =========================================================================
  
  // DOM Elements - Vocal Training
  const btnSetupMic = document.getElementById('btnSetupMic');
  const micSetupText = document.getElementById('micSetupText');
  const micMeterFill = document.getElementById('micMeterFill');
  const micMonitorToggle = document.getElementById('micMonitorToggle');
  
  const btnRecord = document.getElementById('btnRecord');
  const btnStopRecording = document.getElementById('btnStopRecording');
  const recordingTimer = document.getElementById('recordingTimer');
  const recordingTimeDisplay = document.getElementById('recordingTimeDisplay');
  const btnClearRecording = document.getElementById('btnClearRecording');
  const btnDownloadRecording = document.getElementById('btnDownloadRecording');
  
  const pitchNoteCanvas = document.getElementById('pitchNoteCanvas');
  const btnAnalyzeVocals = document.getElementById('btnAnalyzeVocals');
  
  const targetNoteDisplay = document.getElementById('targetNoteDisplay');
  const yourNoteDisplay = document.getElementById('yourNoteDisplay');
  const accuracyDisplay = document.getElementById('accuracyDisplay');
  
  const btnSourceOriginal = document.getElementById('btnSourceOriginal');
  const btnSourceUser = document.getElementById('btnSourceUser');
  const btnSourceBoth = document.getElementById('btnSourceBoth');
  
  // State
  let recordingTimerInterval = null;
  let recordingStartTimestamp = 0;
  let microphoneReady = false;
  let currentUserPitch = null;

  // Setup Microphone Button
  if (btnSetupMic) {
    btnSetupMic.addEventListener('click', async () => {
      if (microphoneReady) {
        showToast('Microphone already connected!', 'info');
        return;
      }
      
      btnSetupMic.disabled = true;
      micSetupText.textContent = 'Requesting access...';
      
      const result = await engine.requestMicrophoneAccess();
      
      if (result.success) {
        microphoneReady = true;
        btnSetupMic.classList.add('active');
        micSetupText.textContent = 'Microphone Ready';
        btnRecord.disabled = false;
        showToast('Microphone connected! Ready to record.', 'success');
      } else {
        btnSetupMic.disabled = false;
        micSetupText.textContent = 'Setup Microphone';
        showToast(`Microphone access denied: ${result.error}`, 'error');
      }
    });
  }

  // Mic Level Updates
  engine.on('micLevelUpdate', (levels) => {
    if (micMeterFill) {
      micMeterFill.style.width = `${Math.min(100, levels.peak * 120)}%`;
    }
    if (micClipDot) {
      micClipDot.classList.toggle('clipping', levels.clipping);
    }
  });

  // Pitch Detection Updates
  engine.on('pitchDetected', (pitchInfo) => {
    currentUserPitch = pitchInfo;
    
    // Update pitch note canvas
    if (pitchNoteCanvas) {
      PitchVisualizer.renderNoteDisplay(pitchNoteCanvas, pitchInfo);
    }
    
    // Update your note display
    if (yourNoteDisplay) {
      if (pitchInfo.note && !pitchInfo.isSilent) {
        yourNoteDisplay.textContent = `${pitchInfo.note}${pitchInfo.octave}`;
        yourNoteDisplay.style.color = Math.abs(pitchInfo.cents) <= 15 ? '#10b981' : 
                                       Math.abs(pitchInfo.cents) <= 30 ? '#f59e0b' : '#ef4444';
      } else {
        yourNoteDisplay.textContent = '—';
        yourNoteDisplay.style.color = '';
      }
    }
    
    // Add to visualizer if recording
    if (engine.isRecordingVocals && pitchVisualizer) {
      pitchVisualizer.addUserPitchPoint({
        time: engine.getCurrentTime(),
        frequency: pitchInfo.frequency,
        confidence: pitchInfo.confidence
      });
    }
  });

  // Mic Gain Slider
  if (micGainSlider) {
    micGainSlider.addEventListener('input', (e) => {
      const val = parseFloat(e.target.value);
      engine.setMicInputLevel(val);
      if (micGainReadout) {
        micGainReadout.textContent = formatDb(val);
      }
    });
  }

  // Monitor Toggle
  if (micMonitorToggle) {
    micMonitorToggle.addEventListener('change', (e) => {
      engine.setMicMonitorEnabled(e.target.checked);
      showToast(e.target.checked ? 'Monitor ON - You can hear yourself' : 'Monitor OFF', 'info');
    });
  }

  // Record Button
  if (btnRecord) {
    btnRecord.addEventListener('click', async () => {
      if (engine.isRecordingVocals) {
        // Stop recording
        engine.stopVocalRecording();
      } else {
        // Start recording
        const success = await engine.startVocalRecording();
        if (success) {
          // Also start playback if not playing
          if (!engine.isPlaying) {
            await engine.play();
          }
        }
      }
    });
  }

  // Recording State Changes
  engine.on('recordingStateChanged', (state) => {
    if (state.recording) {
      btnRecord.classList.add('recording');
      if (btnStopRecording) btnStopRecording.disabled = false;
      if (recordingTimer) recordingTimer.classList.add('active');
      recordingStartTimestamp = Date.now();
      
      // Start timer
      recordingTimerInterval = setInterval(() => {
        const elapsed = (Date.now() - recordingStartTimestamp) / 1000;
        const mins = Math.floor(elapsed / 60);
        const secs = Math.floor(elapsed % 60);
        if (recordingTimeDisplay) {
          recordingTimeDisplay.textContent = `${mins}:${String(secs).padStart(2, '0')}`;
        }
      }, 100);
      
      showToast('🎤 Recording! Sing along...', 'success');
    } else {
      btnRecord.classList.remove('recording');
      if (btnStopRecording) btnStopRecording.disabled = true;
      if (recordingTimer) recordingTimer.classList.remove('active');
      
      if (recordingTimerInterval) {
        clearInterval(recordingTimerInterval);
        recordingTimerInterval = null;
      }
      
      showToast('Recording stopped.', 'info');
    }
  });

  // Stop Recording Button
  if (btnStopRecording) {
    btnStopRecording.addEventListener('click', () => {
      engine.stopVocalRecording();
      engine.pause();
    });
  }

  // User Recording Ready
  engine.on('userRecordingReady', (data) => {
    if (btnClearRecording) btnClearRecording.disabled = false;
    if (btnDownloadRecording) btnDownloadRecording.disabled = false;
    
    // Calculate and display accuracy
    const accuracy = engine.calculatePitchAccuracy();
    if (accuracy && accuracyDisplay) {
      accuracyDisplay.textContent = `${accuracy.accuracy.toFixed(0)}%`;
      accuracyDisplay.style.color = accuracy.accuracy >= 80 ? '#10b981' :
                                     accuracy.accuracy >= 60 ? '#f59e0b' : '#ef4444';
    }
    
    showToast('✅ Recording saved! Compare with original.', 'success');
  });

  // Clear Recording Button
  if (btnClearRecording) {
    btnClearRecording.addEventListener('click', () => {
      engine.clearUserRecording();
      btnClearRecording.disabled = true;
      if (btnDownloadRecording) btnDownloadRecording.disabled = true;
      if (recordingTimeDisplay) recordingTimeDisplay.textContent = '0:00';
      
      if (accuracyDisplay) {
        accuracyDisplay.textContent = '—';
        accuracyDisplay.style.color = '';
      }
      
      showToast('Recording cleared.', 'info');
    });
  }

  // Download Recording Button
  if (btnDownloadRecording) {
    btnDownloadRecording.addEventListener('click', async () => {
      const dateStr = new Date().toISOString().slice(0, 10);
      const success = await engine.downloadUserRecording(`my-vocals_${dateStr}.wav`);
      if (success) {
        showToast('Recording downloaded!', 'success');
      }
    });
  }

  // Analyze Vocals Button
  if (btnAnalyzeVocals) {
    btnAnalyzeVocals.addEventListener('click', async () => {
      const vocalTrack = engine.tracks.get('vocal');
      if (!vocalTrack || !vocalTrack.buffer) {
        showToast('Load a song first to analyze vocals.', 'error');
        return;
      }
      
      btnAnalyzeVocals.disabled = true;
      btnAnalyzeVocals.textContent = '...';
      
      showToast('Analyzing vocal pitch...', 'info');
      
      try {
        await engine.analyzeVocalStem();
        showToast('✅ Vocal analysis complete!', 'success');
      } catch (err) {
        console.error('Analysis error:', err);
        showToast('Error: ' + err.message, 'error');
      } finally {
        btnAnalyzeVocals.disabled = false;
        btnAnalyzeVocals.textContent = 'Analyze';
      }
    });
  }

  // Update target note display based on current playback position
  function updateTargetNote() {
    const originalPitchData = engine.getOriginalVocalPitchData();
    if (!originalPitchData || originalPitchData.length === 0) return;
    
    const currentTime = engine.getCurrentTime();
    
    // Find the nearest pitch point
    let nearest = null;
    let minDist = Infinity;
    
    for (const point of originalPitchData) {
      const dist = Math.abs(point.time - currentTime);
      if (dist < minDist && point.frequency) {
        minDist = dist;
        nearest = point;
      }
    }
    
    if (nearest && minDist < 0.2 && targetNoteDisplay) {
      const noteInfo = frequencyToNote(nearest.frequency);
      if (noteInfo.note) {
        targetNoteDisplay.textContent = `${noteInfo.note}${noteInfo.octave}`;
      }
    } else if (targetNoteDisplay) {
      targetNoteDisplay.textContent = '—';
    }
  }

  function frequencyToNote(frequency) {
    if (!frequency || frequency <= 0) return { note: null, octave: null };
    
    const A4_FREQ = 440;
    const A4_MIDI = 69;
    const NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
    
    const midiNumber = 12 * Math.log2(frequency / A4_FREQ) + A4_MIDI;
    const roundedMidi = Math.round(midiNumber);
    const noteIndex = ((roundedMidi % 12) + 12) % 12;
    const octave = Math.floor(roundedMidi / 12) - 1;
    
    return {
      note: NOTE_NAMES[noteIndex],
      octave: octave
    };
  }

  // Add target note update to animation loop
  const originalStartAnimationLoop = startAnimationLoop;
  startAnimationLoop = function() {
    function update() {
      const curTime = engine.getCurrentTime();
      const total = engine.totalDuration || 0;
      const progress = total > 0 ? (curTime / total) : 0;

      currentTimeEl.textContent = formatTime(curTime);
      totalTimeEl.textContent = formatTime(total);

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
        if (vuFill) vuFill.style.width = `${Math.min(100, levels.peak * 110)}%`;
        if (vuClip) vuClip.classList.toggle('clipping', levels.clip);
      }

      // Master VU Meters
      const masterLevels = engine.getMasterLevels();
      if (masterMeterL) masterMeterL.style.width = `${Math.min(100, masterLevels.left * 100)}%`;
      if (masterMeterR) masterMeterR.style.width = `${Math.min(100, masterLevels.right * 100)}%`;

      redrawAllWaveforms();
      
      // Update target note for vocal training
      updateTargetNote();

      animationFrameId = requestAnimationFrame(update);
    }
    cancelAnimationFrame(animationFrameId);
    animationFrameId = requestAnimationFrame(update);
  };
  
  startAnimationLoop();

  // Comparison Source Buttons
  const sourceButtons = [btnSourceOriginal, btnSourceUser, btnSourceBoth];
  sourceButtons.forEach(btn => {
    if (btn) {
      btn.addEventListener('click', () => {
        sourceButtons.forEach(b => b && b.classList.remove('active'));
        btn.classList.add('active');
        engine.setPlaybackSource(btn.dataset.source);
        
        const labels = {
          'original': 'Original vocal selected',
          'user': 'Your recording selected',
          'both': 'Both vocals playing'
        };
        showToast(labels[btn.dataset.source], 'info');
      });
    }
  });

});
