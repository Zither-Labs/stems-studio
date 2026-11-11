/**
 * Stems Studio - Main Application Controller
 * Handles Song Intake (Media URL / Audio File / Demo), AI Stem Separation,
 * 6-Stem Nepali Folk & Acoustic profiles, multi-track mixing, and waveforms.
 */

document.addEventListener('DOMContentLoaded', () => {
  const engine = new AudioEngine();

  // Scrolling pitch highway above the seek bar; it follows the vocal stem by itself.
  const vocalHighwayCanvas = document.getElementById('vocalHighwayCanvas');
  let vocalHighway = null;
  if (vocalHighwayCanvas && typeof VocalHighway !== 'undefined') {
    vocalHighway = new VocalHighway({ canvas: vocalHighwayCanvas, engine, bar: document.getElementById('highwayBar') });
    if (typeof SingingCoach !== 'undefined' && document.getElementById('coachBar')) {
      window.singingCoach = new SingingCoach({ highway: vocalHighway, engine, root: document });
    }
    window.vocalHighway = vocalHighway;      // handy for trying things in the browser console
  }
  // Karaoke lyrics, from the song's own tags or from LRCLIB.
  let lyricsPanel = null;
  const lyricsPanelEl = document.getElementById('lyricsPanel');
  if (lyricsPanelEl && typeof LyricsPanel !== 'undefined') {
    lyricsPanel = new LyricsPanel({ engine, panel: lyricsPanelEl });
    window.lyricsPanel = lyricsPanel;
  }
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

  // Simple loader
  const btnLoadDemo = document.getElementById('btnLoadDemo');

  // Presets & Modal
  const btnPresetKaraoke = document.getElementById('btnPresetKaraoke');
  const btnPresetAcapella = document.getElementById('btnPresetAcapella');
  const btnPresetRhythm = document.getElementById('btnPresetRhythm');
  const btnPresetReset = document.getElementById('btnPresetReset');
  const helpModal = document.getElementById('helpModal');
  const installModal = document.getElementById('installModal');
  const aboutModal = document.getElementById('aboutModal');
  // Which mix switch is lit: 'karaoke', 'acapella', 'rhythm', or null.
  let activeMix = null;

  const btnExportMix = document.getElementById('btnExportMix');
  const btnExportKaraoke = document.getElementById('btnExportKaraoke');
  const btnExportAcapella = document.getElementById('btnExportAcapella');
  const exportLoopOnlyCheckbox = document.getElementById('exportLoopOnly');

  const btnImportStems = document.getElementById('btnImportStems');
  const fileInputHidden = document.getElementById('fileInputHidden');
  const dropzoneModal = document.getElementById('dropzoneModal');
  const modalCloseBtn = document.getElementById('modalCloseBtn');
  const dropzoneBox = document.getElementById('dropzoneBox');

  // Starting lanes, shown empty until a song is loaded. Neutral names: the app does not
  // assume any particular style of music.
  const defaultTrackDefs = [
    { id: 'vocal', name: 'Vocals', stemType: 'vocal' },
    { id: 'drums', name: 'Drums', stemType: 'drums' },
    { id: 'bass', name: 'Bass', stemType: 'bass' },
    { id: 'guitar', name: 'Guitar', stemType: 'guitar' },
    { id: 'piano', name: 'Piano', stemType: 'piano' },
    { id: 'other', name: 'Other', stemType: 'other' }
  ];

  // Initialize track models in audio engine
  function initializeTrackModels(defs) {
    engine.tracks.clear();
    defs.forEach(def => {
      engine.addTrack(def.id, def.name, def.stemType, null);
    });
    renderAllTrackCards();
  }

  initializeTrackModels(defaultTrackDefs);

  // Render Track DOM Cards
  function renderAllTrackCards() {
    tracksRack.innerHTML = '';
    const isDrumPart = track => track.id.startsWith('drums_');
    const drumParts = [...engine.tracks.values()].filter(isDrumPart);
    let groupAdded = false;
    for (const track of engine.tracks.values()) {
      // The split drums (kick, snare, ...) sit under one "Drums" bar that can fold them away.
      if (isDrumPart(track) && !groupAdded) {
        tracksRack.appendChild(createDrumGroupElement(drumParts));
        groupAdded = true;
      }
      const card = createTrackCardElement(track);
      if (isDrumPart(track)) card.classList.add('drum-part');
      tracksRack.appendChild(card);
    }
    applyDrumsExpanded();
    syncMixButtons();
  }

  // --- the Drums group: fold the individual drum stems away (they stay in the mix and on the highway) ---
  const DRUMS_EXPANDED_KEY = 'stemsStudio.drumsExpanded';
  var drumsExpanded = false;      // (var: the first render, just above, runs before this line)
  try { drumsExpanded = localStorage.getItem(DRUMS_EXPANDED_KEY) === '1'; } catch (err) { /* private mode: stay folded */ }

  function createDrumGroupElement(parts) {
    const group = document.createElement('div');
    group.className = 'drum-group';
    group.id = 'drumGroup';
    group.innerHTML = `
      <button type="button" class="drum-group-toggle" id="drumGroupToggle" aria-expanded="false">
        <span class="drum-group-chevron" aria-hidden="true"></span>
        <span class="drum-group-title">Drums</span>
        <span class="drum-group-parts"></span>
      </button>
      <div class="track-strip-buttons">
        <button class="btn-mute" id="drumGroupMute" title="Mute all the drums">M</button>
        <button class="btn-solo" id="drumGroupSolo" title="Solo all the drums">S</button>
      </div>`;
    group.querySelector('.drum-group-parts').textContent =
      `${parts.length} parts: ${parts.map(t => t.name).join(', ')}`;
    group.querySelector('#drumGroupToggle').addEventListener('click', () => {
      drumsExpanded = !drumsExpanded;
      try { localStorage.setItem(DRUMS_EXPANDED_KEY, drumsExpanded ? '1' : '0'); } catch (err) { /* ignore */ }
      applyDrumsExpanded();
    });
    const setAll = (flag, toggle) => {
      const target = !parts.every(t => t[flag]);
      parts.forEach(t => { if (t[flag] !== target) toggle(t.id); });
    };
    group.querySelector('#drumGroupMute').addEventListener('click', () => {
      clearActiveMix();
      setAll('isMuted', id => engine.toggleTrackMute(id));
    });
    group.querySelector('#drumGroupSolo').addEventListener('click', () => {
      clearActiveMix();
      setAll('isSoloed', id => engine.toggleTrackSolo(id));
    });
    return group;
  }

  function applyDrumsExpanded() {
    document.querySelectorAll('.track-card.drum-part').forEach(card => {
      card.classList.toggle('folded-away', !drumsExpanded);
    });
    const toggle = document.getElementById('drumGroupToggle');
    if (toggle) {
      toggle.setAttribute('aria-expanded', drumsExpanded ? 'true' : 'false');
      toggle.title = drumsExpanded ? 'Hide the individual drum stems' : 'Show the individual drum stems';
      toggle.querySelector('.drum-group-chevron').textContent = drumsExpanded ? '\u25BE' : '\u25B8';
    }
    // Folded waveforms have no size; draw them once they are visible.
    if (drumsExpanded) setTimeout(redrawAllWaveforms, 30);
  }

  // Keeps every Mute/Solo button in step with the mix (also when the drums group or a preset changed it).
  function syncMixButtons() {
    const parts = [...engine.tracks.values()].filter(t => t.id.startsWith('drums_'));
    for (const track of engine.tracks.values()) {
      const card = document.getElementById(`trackCard_${track.id}`);
      if (!card) continue;
      card.querySelector('.btn-mute')?.classList.toggle('active', !!track.isMuted);
      card.querySelector('.btn-solo')?.classList.toggle('active', !!track.isSoloed);
    }
    document.getElementById('drumGroupMute')?.classList.toggle('active', parts.length > 0 && parts.every(t => t.isMuted));
    document.getElementById('drumGroupSolo')?.classList.toggle('active', parts.length > 0 && parts.every(t => t.isSoloed));
  }
  engine.on('mixStateChanged', syncMixButtons);

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
            <span class="slider-readout" id="volReadout_${track.id}">${formatDb(track.volume)}</span>
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
      clearActiveMix();
      const isMuted = engine.toggleTrackMute(track.id);
      muteBtn.classList.toggle('active', isMuted);
    });

    const soloBtn = card.querySelector('.btn-solo');
    soloBtn.addEventListener('click', () => {
      clearActiveMix();
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
  // Procedural Demo Stems
  // =========================================================================
  async function loadDemoStems(is6Stems = true) {
    showToast(`Synthesizing ${is6Stems ? '6-Stem Nepali Folk' : '4-Stem'} demo audio...`, 'info');
    btnLoadDemo.disabled = true;

    try {
      await engine.resume();
      const demoStems = await DemoStemGenerator.generateDemoStems(engine.ctx, is6Stems);

      if (vocalHighway) { vocalHighway.songInfo = null; vocalHighway.analysisUrl = null; vocalHighway.resetKey(); }   // the demo has nothing saved
      if (lyricsPanel) { currentSongId = null; lyricsPanel.clear(); }
      engine.tracks.clear();
      renderHiddenStemsBar([], false);

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
      btnLoadDemo.disabled = false;
    }
  }

  if (btnLoadDemo) {
    btnLoadDemo.addEventListener('click', () => loadDemoStems(true));
  }

  // =========================================================================
  // Create Stems (talks to server.py, which runs Demucs)
  // =========================================================================
  const btnCreateStems = document.getElementById('btnCreateStems');
  const createStemsModal = document.getElementById('createStemsModal');
  const createStemsClose = document.getElementById('createStemsClose');
  const createStemsCancel = document.getElementById('createStemsCancel');
  const createStemsGo = document.getElementById('createStemsGo');
  const createStemsForm = document.getElementById('createStemsForm');
  const createStemsDrop = document.getElementById('createStemsDrop');
  const createStemsFile = document.getElementById('createStemsFile');
  const createStemsFileName = document.getElementById('createStemsFileName');
  const createStemsUrl = document.getElementById('createStemsUrl');
  const createStemsEngineNote = document.getElementById('createStemsEngineNote');
  const createStemsProgress = document.getElementById('createStemsProgress');
  const createStemsMessage = document.getElementById('createStemsMessage');
  const createStemsPercent = document.getElementById('createStemsPercent');
  const createStemsFill = document.getElementById('createStemsFill');

  const CREATE_DEFAULT_LABEL = 'Click to choose a song, or drop it here';
  let createFileChoice = null;
  let createBusy = false;
  let stemMakerReady = false;
  let engineBuild = '';
  let cleanVocalsInstalled = false;   // from the server: is the Roformer tool installed?
  let drumSplitInstalled = false;     // the same tool also splits the drums
  let createRunId = 0;

  function refreshCreateButton() {
    createStemsGo.disabled = createBusy || !stemMakerReady;
  }

  const RESTART_HINT = 'Close Stems Studio completely and open it again from its shortcut.';

  // Turns a failed request into a plain-English reason the user can act on.
  async function explainServerProblem(resp, err) {
    if (window.location.protocol === 'file:') {
      return 'This page was opened as a file. Open Stems Studio from its shortcut instead.';
    }
    if (resp) {
      let detail = '';
      try { detail = (await resp.json()).error || ''; } catch (e) { /* not JSON */ }
      if (resp.status === 404) {
        return `An older copy of Stems Studio is still running in the background. Close all Stems Studio windows, end every "python.exe" in Task Manager, then open the app again.`;
      }
      return `The stem maker hit a problem (error ${resp.status})${detail ? `: ${detail}` : ''}. ${RESTART_HINT}`;
    }
    console.error(err);
    if (err && err.name === 'AbortError') {
      return `The stem maker is not answering. If it only just started, wait a few seconds and try again. Otherwise: ${RESTART_HINT}`;
    }
    return `Cannot reach the stem maker at ${window.location.host}. ${RESTART_HINT}`;
  }

  // Never leave the page waiting forever on a server that is not answering.
  async function fetchWithTimeout(url, options = {}, timeoutMs = 8000) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      return await fetch(url, { ...options, signal: controller.signal });
    } finally {
      clearTimeout(timer);
    }
  }

  let stemMakerCheckId = 0;

  async function checkStemMaker(quiet = false) {
    const checkId = ++stemMakerCheckId;
    if (!quiet) {
      stemMakerReady = false;
      refreshCreateButton();
      createStemsEngineNote.className = 'create-engine-note';
      createStemsEngineNote.textContent = 'Checking the stem maker...';
    }
    let recheckSoon = false;
    try {
      let resp;
      try {
        resp = await fetchWithTimeout('/api/engine');
      } catch (err) {
        throw new Error(await explainServerProblem(null, err));
      }
      if (!resp.ok) throw new Error(await explainServerProblem(resp));
      const info = await resp.json();
      if (!info.library) {
        throw new Error(await explainServerProblem({ status: 404, json: async () => ({}) }));
      }
      if (checkId !== stemMakerCheckId) return;
      stemMakerReady = true;
      if (engineBuild && info.version && info.version !== engineBuild) {
        location.reload();
        return;
      }
      engineBuild = info.version || engineBuild;
      cleanVocalsInstalled = info.clean_vocals_available === true;
      const drumSplitChanged = drumSplitInstalled !== (info.drum_split_available === true);
      drumSplitInstalled = info.drum_split_available === true;
      syncCleanVocalsAvailability();
      if (drumSplitChanged) refreshLibrary();
      if (info.pending) {
        // The server is still loading its AI engine; you can already start.
        createStemsEngineNote.textContent = 'Ready. Still checking for your graphics card in the background...';
        recheckSoon = true;
      } else {
        createStemsEngineNote.textContent = (info.cuda_available || info.device === 'mps')
          ? `Ready. Using your graphics card (${info.device_name}).`
          : 'Ready. Using your CPU, so a song can take several minutes.';
      }
    } catch (err) {
      if (checkId !== stemMakerCheckId) return;
      stemMakerReady = false;
      createStemsEngineNote.className = 'create-engine-note warn';
      createStemsEngineNote.textContent = err.message;
    }
    refreshCreateButton();
    if (recheckSoon) {
      setTimeout(() => {
        if (checkId === stemMakerCheckId && createStemsModal.classList.contains('open')) {
          checkStemMaker(true);
        }
      }, 2000);
    }
  }

  // If Update replaced the engine while this page was open, load the new page.
  setInterval(async () => {
    try {
      const info = await (await fetch('/api/engine')).json();
      if (!info.version) return;
      if (!engineBuild) {
        engineBuild = info.version;
        return;
      }
      if (info.version !== engineBuild) location.reload();
    } catch (err) { /* the engine is restarting */ }
  }, 4000);

  function resetCreateDialog() {
    createFileChoice = null;
    createStemsFile.value = '';
    createStemsFileName.textContent = CREATE_DEFAULT_LABEL;
    createStemsUrl.value = '';
    createStemsForm.style.display = '';
    createStemsProgress.style.display = 'none';
    createStemsFill.style.background = '';
    createStemsFill.style.width = '0%';
    createStemsPercent.textContent = '0%';
  }

  function openCreateDialog() {
    if (!createBusy) resetCreateDialog();
    createStemsModal.classList.add('open');
    checkStemMaker();
  }

  function closeCreateDialog() {
    createStemsModal.classList.remove('open');
  }

  function chooseCreateFile(file) {
    if (!file) return;
    createFileChoice = file;
    createStemsFileName.textContent = `${file.name} (${(file.size / (1024 * 1024)).toFixed(1)} MB)`;
    createStemsUrl.value = '';
  }

  function setCreateProgress(percent, message, isError = false) {
    createStemsProgress.style.display = 'block';
    createStemsFill.style.width = `${percent}%`;
    createStemsFill.style.background = isError ? '#ef4444' : '';
    createStemsPercent.textContent = isError ? '' : `${percent}%`;
    createStemsMessage.textContent = message;
  }

  async function pollSeparation(jobId, runId, skipFirstWait = false) {
    while (runId === createRunId) {
      if (!skipFirstWait) await new Promise(resolve => setTimeout(resolve, 900));
      skipFirstWait = false;
      if (runId !== createRunId) return null;

      const resp = await fetch(`/api/status?job_id=${encodeURIComponent(jobId)}`);
      const job = await resp.json();

      if (job.status === 'completed') return job;
      if (job.status === 'error') throw new Error(job.error || 'Separation failed.');
      if (job.status === 'not_found') throw new Error('The stem maker restarted. Please try again.');
      setCreateProgress(job.progress || 0, job.message || 'Working...');
    }
    return null;
  }

  let currentSongStems = [];
  let currentSongTitle = '';
  let currentSongId = null;

  // Shows which stems were left out because nothing was found in them, with a switch.
  function renderHiddenStemsBar(hidden, showingAll) {
    let bar = document.getElementById('hiddenStemsBar');
    if (!hidden.length) {
      if (bar) bar.remove();
      return;
    }
    if (!bar) {
      bar = document.createElement('div');
      bar.id = 'hiddenStemsBar';
      bar.className = 'hidden-stems-bar';
      tracksRack.insertAdjacentElement('afterend', bar);
    }
    bar.innerHTML = '';
    const text = document.createElement('span');
    const names = hidden.map(h => h.name).join(', ');
    text.textContent = showingAll
      ? `Showing everything, including stems with nothing in them (${names}).`
      : `Hidden because nothing was found in them: ${names}.`;
    const toggle = document.createElement('button');
    toggle.type = 'button';
    toggle.className = 'preset-chip';
    toggle.textContent = showingAll ? 'Hide empty stems' : 'Show anyway';
    toggle.addEventListener('click', () => loadSeparatedStems(currentSongStems, !showingAll, currentSongTitle));
    bar.append(text, toggle);
  }

  async function loadSeparatedStems(stems, showEmpty = false, songTitle = '') {
    currentSongStems = stems;
    currentSongTitle = songTitle || currentSongTitle;
    // Vocals always sit at the top of the mixer, then the rest in a fixed order. This also
    // fixes songs saved in the library earlier, which were stored alphabetically.
    const laneOrder = ['vocal', 'drums', 'bass', 'guitar', 'piano', 'other'];
    const laneRank = stem => {
      const rank = laneOrder.indexOf(stem.stemType);
      return rank === -1 ? laneOrder.length : rank;
    };
    const ordered = [...stems].sort((a, b) => laneRank(a) - laneRank(b));
    const shown = showEmpty ? ordered : ordered.filter(stem => !stem.empty);
    const hidden = ordered.filter(stem => stem.empty);

    await engine.resume();
    engine.pause();
    engine.seek(0);
    engine.tracks.clear();

    // The vocal highway asks the engine for this song's vocal pitch, key and chords, and
    // the lyrics panel for its lyrics. All of them are looked up by the song's id.
    const anyStem = stems.find(stem => /^\/api\/stems\/[0-9a-f]{8}\//.test(stem.url));
    const songId = anyStem ? /^\/api\/stems\/([0-9a-f]{8})\//.exec(anyStem.url)[1] : null;
    if (vocalHighway) {
      // Every stem the highway can follow, with the name of its file (that is what the engine is asked for).
      const followable = [];
      for (const stem of shown) {
        const file = /\/api\/stems\/[0-9a-f]{8}\/([a-z_]+)\.wav/.exec(stem.url || '');
        if (!file || !songId) continue;
        const keepOwnId = stem.id === 'guitar_lead' || stem.id === 'guitar_rhythm' || stem.id.startsWith('drums_');
        const trackId = !keepOwnId && stem.stemType && stem.stemType !== 'custom' ? stem.stemType : stem.id;
        followable.push({ file: file[1], trackId });
      }
      vocalHighway.songInfo = songId && followable.length ? { songId, stems: followable } : null;
      vocalHighway.analysisUrl = songId ? `/api/analysis/${songId}` : null;
    }
    if (lyricsPanel && songId !== currentSongId) {
      currentSongId = songId;
      if (songId) lyricsPanel.loadSong(songId, currentSongTitle);
      else lyricsPanel.clear();
    }

    for (const stem of shown) {
      const audioResp = await fetch(stem.url);
      const decoded = await engine.ctx.decodeAudioData(await audioResp.arrayBuffer());
      // Karaoke, Acapella, Analyze and Compare look tracks up by type (e.g. "vocal").
      // The two halves of a split guitar share a type, so they keep their own ids.
      const keepOwnId = stem.id === 'guitar_lead' || stem.id === 'guitar_rhythm' || stem.id.startsWith('drums_');
      const trackId = !keepOwnId && stem.stemType && stem.stemType !== 'custom' ? stem.stemType : stem.id;
      engine.addTrack(trackId, stem.name, stem.stemType, decoded);
    }

    renderAllTrackCards();
    renderHiddenStemsBar(hidden, showEmpty);
    document.querySelectorAll('.track-empty-state').forEach(el => { el.style.display = 'none'; });
    redrawAllWaveforms();
  }

  // The choices made in the Create Stems dialog are remembered between sessions.
  const CREATE_OPTIONS_KEY = 'stemsStudio.createOptions';

  function getCreateOptions() {
    const checked = document.querySelector('input[name="createStemCount"]:checked');
    const folk = document.getElementById('createFolkNames');
    const split = document.getElementById('createGuitarSplit');
    const clean = document.getElementById('createCleanVocals');
    const drums = document.getElementById('createSplitDrums');
    const model = checked && checked.value === '4' ? 'htdemucs' : 'htdemucs_6s';
    return {
      model,
      preset: folk && folk.checked ? 'nepali_folk' : 'standard',
      guitarSplit: model === 'htdemucs_6s' && Boolean(split && split.checked),
      cleanVocals: cleanVocalsInstalled && Boolean(clean && clean.checked),
      splitDrums: drumSplitInstalled && Boolean(drums && drums.checked)
    };
  }

  // Splitting the guitar only makes sense when there is a guitar stem (6 stems).
  function syncGuitarSplitAvailability() {
    const split = document.getElementById('createGuitarSplit');
    if (!split) return;
    const sixStems = getCreateOptions().model === 'htdemucs_6s';
    split.disabled = !sixStems;
    const label = split.closest('label');
    if (label) label.classList.toggle('disabled', !sixStems);
  }

  // Cleaner vocals needs an extra tool. Without it the box is greyed out and says how to get it.
  function syncCleanVocalsAvailability() {
    const clean = document.getElementById('createCleanVocals');
    const label = document.getElementById('createCleanVocalsLabel');
    if (!clean || !label) return;
    clean.disabled = !cleanVocalsInstalled;
    label.classList.toggle('disabled', !cleanVocalsInstalled);
    label.title = cleanVocalsInstalled ? '' : 'Not installed yet. Close Stems Studio and run the installer (Install.bat), and say yes to cleaner vocals.';
    const drums = document.getElementById('createSplitDrums');
    const drumsLabel = document.getElementById('createSplitDrumsLabel');
    if (drums && drumsLabel) {
      drums.disabled = !drumSplitInstalled;
      drumsLabel.classList.toggle('disabled', !drumSplitInstalled);
      drumsLabel.title = drumSplitInstalled ? '' : 'Not installed yet. Close Stems Studio and run the installer (Install.bat), and say yes to cleaner vocals: the same extra tool splits the drums.';
    }
  }

  function restoreCreateOptions() {
    try {
      const saved = JSON.parse(localStorage.getItem(CREATE_OPTIONS_KEY) || '{}');
      const radio = document.querySelector(`input[name="createStemCount"][value="${saved.stems === 4 ? '4' : '6'}"]`);
      if (radio) radio.checked = true;
      const folk = document.getElementById('createFolkNames');
      if (folk) folk.checked = saved.folk === true;
      const split = document.getElementById('createGuitarSplit');
      if (split) split.checked = saved.guitarSplit === true;
      const clean = document.getElementById('createCleanVocals');
      if (clean) clean.checked = saved.cleanVocals === true;
      const drums = document.getElementById('createSplitDrums');
      if (drums) drums.checked = saved.splitDrums === true;
    } catch (err) { /* private mode or corrupt value: keep the defaults */ }
  }

  function saveCreateOptions() {
    const { model, preset } = getCreateOptions();
    const split = document.getElementById('createGuitarSplit');
    try {
      localStorage.setItem(CREATE_OPTIONS_KEY, JSON.stringify({
        stems: model === 'htdemucs' ? 4 : 6,
        folk: preset === 'nepali_folk',
        guitarSplit: Boolean(split && split.checked),
        cleanVocals: Boolean(document.getElementById('createCleanVocals') && document.getElementById('createCleanVocals').checked),
        splitDrums: Boolean(document.getElementById('createSplitDrums') && document.getElementById('createSplitDrums').checked)
      }));
    } catch (err) { /* ignore */ }
  }

  restoreCreateOptions();
  syncGuitarSplitAvailability();
  document.querySelectorAll('input[name="createStemCount"], #createFolkNames, #createGuitarSplit, #createCleanVocals, #createSplitDrums')
    .forEach(el => el.addEventListener('change', () => {
      syncGuitarSplitAvailability();
      saveCreateOptions();
    }));

  async function startCreateStems() {
    const url = createStemsUrl.value.trim();
    if (!createFileChoice && !url) {
      showToast('Choose an audio file or paste a media URL first.', 'error');
      return;
    }

    const options = getCreateOptions();
    createBusy = true;
    const runId = ++createRunId;
    refreshCreateButton();
    createStemsForm.style.display = 'none';
    setCreateProgress(3, 'Sending your song to the stem maker...');

    try {
      let resp;
      if (createFileChoice) {
        const formData = new FormData();
        formData.append('file', createFileChoice);
        formData.append('model', options.model);
        formData.append('preset', options.preset);
        formData.append('guitar_split', options.guitarSplit ? '1' : '0');
        formData.append('clean_vocals', options.cleanVocals ? '1' : '0');
        formData.append('split_drums', options.splitDrums ? '1' : '0');
        resp = await fetch('/api/separate', { method: 'POST', body: formData });
      } else {
        resp = await fetch('/api/separate', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ youtube_url: url, model: options.model, preset: options.preset, guitar_split: options.guitarSplit, clean_vocals: options.cleanVocals, split_drums: options.splitDrums })
        });
      }
      if (!resp.ok) throw new Error(`The stem maker refused the request (${resp.status}).`);

      const { job_id: jobId, cached } = await resp.json();
      if (cached) setCreateProgress(60, 'Already in your library - opening it instantly...');
      const job = await pollSeparation(jobId, runId, Boolean(cached));
      if (!job) return;

      setCreateProgress(100, 'Loading the stems into the mixer...');
      await loadSeparatedStems(job.stems, false, job.title || '');

      closeCreateDialog();
      resetCreateDialog();
      showToast(
        cached
          ? 'Found this song in your library - loaded without re-creating. Press Space to play.'
          : 'Stems ready and saved to your library! Press Space to play.',
        'success'
      );
    } catch (err) {
      console.error(err);
      createStemsForm.style.display = '';
      setCreateProgress(100, err.message, true);
      showToast(`Could not create stems: ${err.message}`, 'error');
    } finally {
      if (runId === createRunId) createBusy = false;
      refreshCreateButton();
    }
  }

  // =========================================================================
  // Keep-alive: the engine quits shortly after this window closes
  // =========================================================================
  let missedHeartbeats = 0;
  let engineLostShown = false;
  async function sendHeartbeat() {
    try {
      await fetchWithTimeout('/api/heartbeat', {}, 4000);
      missedHeartbeats = 0;
      engineLostShown = false;
    } catch (err) {
      missedHeartbeats++;
      if (missedHeartbeats >= 3 && !engineLostShown) {
        engineLostShown = true;
        showToast('Stems Studio lost its engine. Close this window and open the app again.', 'error');
      }
    }
  }
  sendHeartbeat();
  setInterval(sendHeartbeat, 5000);
  window.addEventListener('pagehide', () => navigator.sendBeacon('/api/closing'));

  // =========================================================================
  // My Library (songs already split, stored by server.py in SQLite)
  // =========================================================================
  const btnLibrary = document.getElementById('btnLibrary');
  const libraryModal = document.getElementById('libraryModal');
  const libraryClose = document.getElementById('libraryClose');
  const libraryList = document.getElementById('libraryList');
  const librarySearch = document.getElementById('librarySearch');
  const librarySummary = document.getElementById('librarySummary');

  let librarySongs = [];
  let libraryFolder = '';
  let libraryFolderLocked = false;
  let libraryOpening = false;
  const libraryFolderText = document.getElementById('libraryFolderText');
  const libraryChangeFolder = document.getElementById('libraryChangeFolder');
  const libraryFolderEditor = document.getElementById('libraryFolderEditor');
  const libraryFolderInput = document.getElementById('libraryFolderInput');
  const libraryFolderError = document.getElementById('libraryFolderError');

  function showLibraryFolder() {
    libraryFolderText.textContent = libraryFolder
      ? `Songs are kept in ${libraryFolder}`
      : 'Songs are kept on this computer.';
    if (libraryFolderLocked) {
      libraryChangeFolder.hidden = true;
      libraryFolderText.textContent += ' This computer\'s library folder is set by STEMS_STUDIO_LIBRARY.';
    } else {
      libraryChangeFolder.hidden = false;
    }
  }

  function showFolderEditor(open) {
    libraryFolderEditor.hidden = !open;
    libraryFolderError.textContent = '';
    if (open) libraryFolderInput.value = libraryFolder;
  }

  async function saveLibraryFolder() {
    libraryFolderError.textContent = '';
    const path = libraryFolderInput.value.trim();
    try {
      const resp = await fetch('/api/library/folder', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ path })
      });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || 'Could not use that folder.');
      showFolderEditor(false);
      showToast(`Library folder is now ${data.folder}.`, 'success');
      await refreshLibrary();
    } catch (err) {
      libraryFolderError.textContent = err.message;
    }
  }

  async function browseLibraryFolder() {
    libraryFolderError.textContent = 'Waiting for you to choose a folder...';
    try {
      const resp = await fetch('/api/library/browse', { method: 'POST' });
      const data = await resp.json();
      if (!resp.ok) throw new Error(data.error || 'Could not open a folder window.');
      libraryFolderError.textContent = '';
      if (data.path) libraryFolderInput.value = data.path;
    } catch (err) {
      libraryFolderError.textContent = err.message;
    }
  }

  function formatBytes(bytes) {
    if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(1)} GB`;
    return `${Math.max(1, Math.round(bytes / 1024 ** 2))} MB`;
  }

  function showLibraryMessage(text, isWarning = false) {
    libraryList.innerHTML = '';
    const msg = document.createElement('div');
    msg.className = `library-empty${isWarning ? ' warn' : ''}`;
    msg.textContent = text;
    libraryList.appendChild(msg);
  }

  function renderLibrary() {
    const query = librarySearch.value.trim().toLowerCase();
    const songs = librarySongs.filter(s => s.title.toLowerCase().includes(query));

    librarySearch.style.display = librarySongs.length > 5 ? '' : 'none';
    const presentSongs = librarySongs.filter(s => !s.missing);
    librarySummary.textContent = presentSongs.length
      ? `${presentSongs.length} song${presentSongs.length === 1 ? '' : 's'} saved, using ${formatBytes(presentSongs.reduce((n, s) => n + s.size_bytes, 0))}.`
      : '';

    if (!songs.length) {
      showLibraryMessage(librarySongs.length
        ? 'No songs match your search.'
        : 'Nothing in this folder yet. Songs you split with Create Stems are saved here.');
      return;
    }

    libraryList.innerHTML = '';
    for (const song of songs) {
      const item = document.createElement('div');
      item.className = `library-item${song.missing ? ' missing' : ''}`;

      const main = document.createElement('button');
      main.type = 'button';
      main.className = 'library-item-main';
      main.title = song.missing ? 'The audio files could not be opened' : 'Open in the mixer';
      const title = document.createElement('div');
      title.className = 'library-item-title';
      title.textContent = song.title;
      const meta = document.createElement('div');
      meta.className = 'library-item-meta';
      meta.textContent = song.missing
        ? 'The audio files could not be opened.'
        : `${new Date(song.created_at * 1000).toLocaleDateString(undefined, { year: 'numeric', month: 'short', day: 'numeric' })} · ${song.stem_count} stems · ${formatBytes(song.size_bytes)}`;
      main.append(title, meta);
      main.addEventListener('click', () => {
        if (song.missing) {
          showToast('The files for this song could not be opened.', 'error');
          return;
        }
        openLibrarySong(song);
      });

      const del = document.createElement('button');
      del.type = 'button';
      del.className = 'library-item-delete';
      del.textContent = 'Delete';
      del.addEventListener('click', () => deleteLibrarySong(song, del));
      del.addEventListener('blur', () => {
        del.classList.remove('confirm');
        del.textContent = 'Delete';
      });

      item.append(main);
      if (song.vocals_can_undo) {
        const undo = document.createElement('button');
        undo.type = 'button';
        undo.className = 'library-item-action';
        undo.textContent = 'Undo clean vocals';
        undo.title = 'Put back the vocal from before the first time it was cleaned';
        undo.addEventListener('click', () => runLibraryJob(song, undo, meta, 'undo-clean-vocals',
          'Putting the old vocal back...', 'Restored the vocal of', 'Could not restore the vocal:'));
        item.append(undo);
      }
      if (song.vocals_can_clean && cleanVocalsInstalled) {
        const clean = document.createElement('button');
        clean.type = 'button';
        clean.className = 'library-item-action';
        clean.textContent = 'Clean vocals';
        clean.title = 'Make the vocal again with the better model, so less guitar leaks into it (takes a couple of minutes). What it removes is moved to the guitar stem.';
        clean.addEventListener('click', () => runLibraryJob(song, clean, meta, 'clean-vocals',
          'Making a cleaner vocal...', 'Cleaned the vocals of', 'Could not clean the vocals:'));
        item.append(clean);
      }
      if (song.drums_can_split && drumSplitInstalled) {
        const split = document.createElement('button');
        split.type = 'button';
        split.className = 'library-item-action';
        split.textContent = 'Split drums';
        split.title = 'Split the drums into kick, snare, toms, hi-hat, ride and crash (takes about a minute)';
        split.addEventListener('click', () => runLibraryJob(song, split, meta, 'split-drums',
          'Splitting the drums...', 'Split the drums of', 'Could not split the drums:'));
        item.append(split);
      }
      item.append(del);
      libraryList.appendChild(item);
    }
  }

  async function refreshLibrary() {
    showLibraryMessage('Loading your songs...');
    let resp = null;
    try {
      try {
        resp = await fetchWithTimeout('/api/library');
      } catch (err) {
        throw new Error(await explainServerProblem(null, err));
      }
      if (!resp.ok) throw new Error(await explainServerProblem(resp));
      const listing = await resp.json();
      librarySongs = listing.songs;
      libraryFolder = listing.folder || '';
      libraryFolderLocked = listing.folder_locked === true;
      showLibraryFolder();
      if (listing.note) showToast(listing.note, 'error');
      renderLibrary();
    } catch (err) {
      librarySongs = [];
      librarySummary.textContent = '';
      showLibraryMessage(err.message, true);
    }
  }

  function openLibraryDialog() {
    librarySearch.value = '';
    libraryModal.classList.add('open');
    // The "Split drums" buttons need to know whether the extra tool is installed.
    fetch('/api/engine')
      .then(resp => (resp.ok ? resp.json() : null))
      .then(info => {
        if (info) {
          drumSplitInstalled = info.drum_split_available === true;
          cleanVocalsInstalled = info.clean_vocals_available === true;
        }
      })
      .catch(() => {})
      .then(() => refreshLibrary());
  }

  function closeLibraryDialog() {
    libraryModal.classList.remove('open');
  }

  async function openLibrarySong(song) {
    if (libraryOpening) return;
    libraryOpening = true;
    showLibraryMessage(`Opening "${song.title}"...`);
    try {
      const resp = await fetch(`/api/library/${encodeURIComponent(song.id)}`);
      if (!resp.ok) throw new Error('This song is no longer saved on this computer.');
      const saved = await resp.json();
      await loadSeparatedStems(saved.stems, false, saved.title || '');
      closeLibraryDialog();
      showToast(`Loaded "${song.title}". Press Space to play.`, 'success');
    } catch (err) {
      console.error(err);
      showToast(`Could not open song: ${err.message}`, 'error');
      refreshLibrary();
    } finally {
      libraryOpening = false;
    }
  }

  // Runs a slow job on a saved song (splitting its drums, making its vocal cleaner), showing the
  // progress in the song's row.
  async function runLibraryJob(song, button, meta, endpoint, doing, done, failed) {
    button.disabled = true;
    try {
      const resp = await fetch(`/api/library/${encodeURIComponent(song.id)}/${endpoint}`, { method: 'POST' });
      const started = await resp.json();
      if (!resp.ok) throw new Error(started.error || `error ${resp.status}`);
      for (;;) {
        await new Promise(resolve => setTimeout(resolve, 1000));
        const job = await (await fetch(`/api/status?job_id=${encodeURIComponent(started.job_id)}`)).json();
        if (job.status === 'error') throw new Error(job.error || failed);
        if (job.status === 'not_found') throw new Error('The stem maker restarted. Please try again.');
        meta.textContent = `${job.message || doing} (${job.progress || 0}%)`;
        if (job.status === 'completed') break;
      }
      showToast(`${done} "${song.title}". Open it to hear the difference.`, 'success');
      await refreshLibrary();
    } catch (err) {
      console.error(err);
      button.disabled = false;
      showToast(`${failed} ${err.message}`, 'error');
    }
  }

  async function deleteLibrarySong(song, button) {
    if (!button.classList.contains('confirm')) {
      button.classList.add('confirm');
      button.textContent = 'Really delete?';
      return;
    }
    try {
      const resp = await fetch(`/api/library/${encodeURIComponent(song.id)}`, { method: 'DELETE' });
      if (!resp.ok && resp.status !== 404) throw new Error(`error ${resp.status}`);
      librarySongs = librarySongs.filter(s => s.id !== song.id);
      renderLibrary();
      showToast(`Deleted "${song.title}" from your library.`, 'info');
    } catch (err) {
      showToast(`Could not delete song: ${err.message}`, 'error');
    }
  }

  btnLibrary.addEventListener('click', openLibraryDialog);
  libraryClose.addEventListener('click', closeLibraryDialog);
  libraryModal.addEventListener('click', (e) => {
    if (e.target === libraryModal) closeLibraryDialog();
  });
  librarySearch.addEventListener('input', renderLibrary);
  libraryChangeFolder.addEventListener('click', () => showFolderEditor(libraryFolderEditor.hidden));
  document.getElementById('libraryFolderCancel').addEventListener('click', () => showFolderEditor(false));
  document.getElementById('libraryFolderSave').addEventListener('click', saveLibraryFolder);
  document.getElementById('libraryFolderBrowse').addEventListener('click', browseLibraryFolder);
  libraryFolderInput.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') saveLibraryFolder();
  });

  btnCreateStems.addEventListener('click', openCreateDialog);
  createStemsClose.addEventListener('click', closeCreateDialog);
  createStemsCancel.addEventListener('click', () => {
    if (createBusy) createRunId++;
    createBusy = false;
    closeCreateDialog();
    resetCreateDialog();
    refreshCreateButton();
  });
  createStemsModal.addEventListener('click', (e) => {
    if (e.target === createStemsModal) closeCreateDialog();
  });
  createStemsGo.addEventListener('click', startCreateStems);
  createStemsDrop.addEventListener('click', () => createStemsFile.click());
  createStemsFile.addEventListener('change', (e) => chooseCreateFile(e.target.files[0]));
  createStemsDrop.addEventListener('dragover', (e) => {
    e.preventDefault();
    createStemsDrop.classList.add('drag-over');
  });
  createStemsDrop.addEventListener('dragleave', () => createStemsDrop.classList.remove('drag-over'));
  createStemsDrop.addEventListener('drop', (e) => {
    e.preventDefault();
    createStemsDrop.classList.remove('drag-over');
    chooseCreateFile(e.dataTransfer.files[0]);
  });
  createStemsUrl.addEventListener('input', () => {
    if (createStemsUrl.value.trim()) {
      createFileChoice = null;
      createStemsFile.value = '';
      createStemsFileName.textContent = CREATE_DEFAULT_LABEL;
    }
  });

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

  // The key shifter: moves the song up or down without changing its speed.
  function setKeyShift(semitones) {
    const value = Math.max(-12, Math.min(12, Math.round(semitones)));
    engine.setPitchSemitones(value);
    pitchValEl.textContent = `${value > 0 ? '+' : ''}${value} st`;
    updateKeyFit();
  }

  pitchDownBtn.addEventListener('click', () => setKeyShift(engine.pitchSemitones - 1));
  pitchUpBtn.addEventListener('click', () => setKeyShift(engine.pitchSemitones + 1));

  // "Fit my voice": picks the key shift that puts the song's singer inside your comfortable range.
  // Comfortable ranges, as MIDI notes (60 = middle C). They are kept narrower than the textbook
  // ranges, so the suggestion does not ask for the top or bottom note of anyone's voice.
  const VOICE_RANGES = {
    bass: { name: 'Bass', low: 43, high: 62 },
    baritone: { name: 'Baritone', low: 47, high: 67 },
    tenor: { name: 'Tenor', low: 50, high: 70 },
    alto: { name: 'Alto', low: 55, high: 74 },
    mezzo: { name: 'Mezzo-soprano', low: 59, high: 78 },
    soprano: { name: 'Soprano', low: 62, high: 81 }
  };
  const keyFitBtn = document.getElementById('keyFitBtn');
  const keyFitPanel = document.getElementById('keyFitPanel');
  const keyVoiceEl = document.getElementById('keyVoice');
  const keyFitText = document.getElementById('keyFitText');
  const keyFitApply = document.getElementById('keyFitApply');
  let keyFitSuggestion = null;      // the shift the panel offers
  let keyFitRange = null;           // the song's singer: { low, mid, high } as MIDI notes

  function noteName(midi) {
    const names = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
    const m = Math.round(midi);
    return `${names[((m % 12) + 12) % 12]}${Math.floor(m / 12) - 1}`;
  }

  // The sung range of the song's vocal (the 8th to 92nd percentile, so a stray note does not count).
  async function readVocalRange() {
    const hw = window.vocalHighway;
    if (!hw) return null;
    let midi = null;
    const cached = hw.cache.get('vocals:melody');
    if (cached && cached.midi) midi = cached.midi;
    else if (hw.active && hw.active.key === 'vocals:melody' && hw.midi) midi = hw.midi;
    else if (hw.songInfo && hw.songInfo.stems.some((s) => s.file === 'vocals')) {
      try {
        const resp = await fetch(`/api/pitch/${hw.songInfo.songId}?stem=vocals`);
        if (resp.ok) midi = (await resp.json()).midi;
      } catch (err) { /* no vocal reading: the panel says so */ }
    }
    if (!midi) return null;
    const voiced = Array.from(midi).filter((m) => m > 0).sort((a, b) => a - b);
    if (voiced.length < 50) return null;
    const at = (q) => voiced[Math.min(voiced.length - 1, Math.floor(voiced.length * q))];
    return { low: at(0.08), mid: at(0.5), high: at(0.92) };
  }

  // The shift (-12..+12) that keeps the singer inside the voice's range; among equal answers the smallest.
  function bestShift(range, voice) {
    let best = null;
    for (let s = -12; s <= 12; s++) {
      const below = Math.max(0, voice.low - (range.low + s));
      const above = Math.max(0, (range.high + s) - voice.high);
      const cost = below + above * 1.5 + Math.abs(s) * 0.01;
      if (!best || cost < best.cost - 1e-9) best = { shift: s, cost, below, above };
    }
    return best;
  }

  function keyName(semitones) {
    const hw = window.vocalHighway;
    if (!hw || !hw.key) return '';
    return `${hw.noteSpelling(hw.key.tonic + semitones)} ${hw.key.mode}`;
  }

  function updateKeyFit() {
    if (keyFitPanel.hidden) return;
    const voice = VOICE_RANGES[keyVoiceEl.value];
    keyFitSuggestion = null;
    keyFitApply.disabled = true;
    const notes = engine.keyShifterState === 'failed'
      ? '<br><em>This browser could not start the key shifter, so changing the key also changes the speed.</em>' : '';
    if (!keyFitRange) {
      keyFitText.innerHTML = 'The vocal of this song has not been read yet. Open a song from My Library or Create Stems, ' +
        'then try again. Meanwhile the + and - buttons move the key by hand.' + notes;
      return;
    }
    const best = bestShift(keyFitRange, voice);
    const r = keyFitRange;
    const song = `The singer here goes from <strong>${noteName(r.low)}</strong> to <strong>${noteName(r.high)}</strong>, mostly around ${noteName(r.mid)}.`;
    const fit = `${voice.name}s are comfortable from ${noteName(voice.low)} to ${noteName(voice.high)}.`;
    let advice;
    if (best.shift === 0 && best.cost < 0.05) {
      advice = '<strong>The original key already suits you.</strong>';
    } else {
      const word = best.shift > 0 ? 'up' : 'down';
      const to = keyName(best.shift);
      advice = `Move the key <strong>${word} ${Math.abs(best.shift)} semitone${Math.abs(best.shift) === 1 ? '' : 's'}</strong>` +
        `${to ? ` (to ${to})` : ''}.`;
    }
    if (best.below > 0 || best.above > 0) {
      advice += ' The song is wider than this voice, so some notes will stay out of reach.';
    }
    keyFitText.innerHTML = `${song}<br>${fit}<br>${advice}${notes}`;
    keyFitSuggestion = best.shift;
    keyFitApply.disabled = best.shift === engine.pitchSemitones;
    keyFitApply.textContent = best.shift === 0 ? 'Original key' : `Use ${best.shift > 0 ? '+' : ''}${best.shift}`;
  }

  async function openKeyFit() {
    keyFitPanel.hidden = false;
    keyFitBtn.classList.add('active');
    keyFitRange = null;
    keyFitText.textContent = 'Reading the singer in this song...';
    keyFitRange = await readVocalRange();
    updateKeyFit();
  }

  function closeKeyFit() {
    keyFitPanel.hidden = true;
    keyFitBtn.classList.remove('active');
  }

  async function loadVoiceType() {
    try {
      const resp = await fetch('/api/preferences');
      if (resp.ok) {
        const data = await resp.json();
        if (data.voice_type && VOICE_RANGES[data.voice_type]) {
          keyVoiceEl.value = data.voice_type;
          return;
        }
      }
    } catch (err) { /* use the browser copy, then this computer's settings */ }
    let saved = null;
    try { saved = localStorage.getItem('stemsStudio.voiceType'); } catch (err) { /* private mode */ }
    if (saved && VOICE_RANGES[saved]) {
      keyVoiceEl.value = saved;
      fetch('/api/preferences', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ voice_type: saved })
      }).catch(() => {});
      return;
    }
    keyVoiceEl.value = 'mezzo';
  }
  loadVoiceType();
  keyFitBtn.addEventListener('click', () => (keyFitPanel.hidden ? openKeyFit() : closeKeyFit()));
  document.getElementById('keyFitClose').addEventListener('click', closeKeyFit);
  document.getElementById('keyFitReset').addEventListener('click', () => setKeyShift(0));
  keyFitApply.addEventListener('click', () => { if (keyFitSuggestion !== null) setKeyShift(keyFitSuggestion); });
  keyVoiceEl.addEventListener('change', () => {
    try { localStorage.setItem('stemsStudio.voiceType', keyVoiceEl.value); } catch (err) { /* ignore */ }
    fetch('/api/preferences', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ voice_type: keyVoiceEl.value })
    }).catch(() => {});
    updateKeyFit();
  });
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape' && !keyFitPanel.hidden) closeKeyFit(); });

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

  // Mix switches. Only one of Karaoke, Acapella, and Rhythm can be on.
  // Clicking the lit one turns it off. None of them move the volume sliders.
  const MIX_ON = {
    karaoke: 'Karaoke: vocals are muted',
    acapella: 'Acapella: only the vocals',
    rhythm: 'Rhythm: drums and bass'
  };
  const MIX_OFF = {
    karaoke: 'Karaoke off: vocals are back',
    acapella: 'Acapella off: the other stems are back',
    rhythm: 'Rhythm off: the other stems are back'
  };

  function paintMixButtons() {
    btnPresetKaraoke.classList.toggle('active', activeMix === 'karaoke');
    btnPresetAcapella.classList.toggle('active', activeMix === 'acapella');
    btnPresetRhythm.classList.toggle('active', activeMix === 'rhythm');
    btnPresetKaraoke.setAttribute('aria-pressed', activeMix === 'karaoke' ? 'true' : 'false');
    btnPresetAcapella.setAttribute('aria-pressed', activeMix === 'acapella' ? 'true' : 'false');
    btnPresetRhythm.setAttribute('aria-pressed', activeMix === 'rhythm' ? 'true' : 'false');
  }

  function clearActiveMix() {
    if (activeMix === null) return;
    activeMix = null;
    paintMixButtons();
  }

  function clearMuteSolo() {
    for (const track of engine.tracks.values()) {
      track.isMuted = false;
      track.isSoloed = false;
    }
  }

  function applyMix(mode) {
    const turningOff = activeMix === mode;
    clearMuteSolo();
    if (!turningOff) {
      if (mode === 'karaoke') {
        const vocal = engine.tracks.get('vocal');
        if (vocal) vocal.isMuted = true;
      } else if (mode === 'acapella') {
        for (const track of engine.tracks.values()) track.isSoloed = track.id === 'vocal';
      } else if (mode === 'rhythm') {
        for (const track of engine.tracks.values()) {
          track.isSoloed = track.id === 'drums' || track.id.startsWith('drums_') || track.id === 'bass';
        }
      }
    }
    activeMix = turningOff ? null : mode;
    paintMixButtons();
    engine.updateMuteSoloStates();
    syncMuteSoloButtons();
    showToast(turningOff ? MIX_OFF[mode] : MIX_ON[mode], turningOff ? 'info' : 'success');
  }

  btnPresetKaraoke.addEventListener('click', () => applyMix('karaoke'));
  btnPresetAcapella.addEventListener('click', () => applyMix('acapella'));
  btnPresetRhythm.addEventListener('click', () => applyMix('rhythm'));

  btnPresetReset.addEventListener('click', () => {
    activeMix = null;
    paintMixButtons();
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
    showToast('Volumes are back to the middle', 'info');
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

  // Help
  const helpClose = document.getElementById('helpClose');
  document.getElementById('btnHelp').addEventListener('click', () => helpModal.classList.add('open'));
  helpClose.addEventListener('click', () => helpModal.classList.remove('open'));
  helpModal.addEventListener('click', (e) => {
    if (e.target === helpModal) helpModal.classList.remove('open');
  });

  // Installation Guide
  const installClose = document.getElementById('installClose');
  const btnInstallGuide = document.getElementById('btnInstallGuide');
  if (btnInstallGuide && installModal) {
    btnInstallGuide.addEventListener('click', () => installModal.classList.add('open'));
    if (installClose) installClose.addEventListener('click', () => installModal.classList.remove('open'));
    installModal.addEventListener('click', (e) => {
      if (e.target === installModal) installModal.classList.remove('open');
    });
  }

  // About
  const aboutClose = document.getElementById('aboutClose');
  const btnAbout = document.getElementById('btnAbout');
  if (btnAbout && aboutModal) {
    btnAbout.addEventListener('click', () => aboutModal.classList.add('open'));
    if (aboutClose) aboutClose.addEventListener('click', () => aboutModal.classList.remove('open'));
    aboutModal.addEventListener('click', (e) => {
      if (e.target === aboutModal) aboutModal.classList.remove('open');
    });
  }

  function closeOpenModals() {
    dropzoneModal.classList.remove('open');
    createStemsModal.classList.remove('open');
    libraryModal.classList.remove('open');
    helpModal.classList.remove('open');
    if (installModal) installModal.classList.remove('open');
    if (aboutModal) aboutModal.classList.remove('open');
  }

  // Global Keyboard Shortcuts
  window.addEventListener('keydown', (e) => {
    if (['INPUT', 'SELECT', 'TEXTAREA'].includes(e.target.tagName)) return;

    if (document.querySelector('.modal-backdrop.open')) {
      if (e.code === 'Escape') {
        e.preventDefault();
        closeOpenModals();
      }
      return;
    }

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
      closeOpenModals();
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

  startAnimationLoop();

  // =========================================================================
  // Vocal Training Studio Module (Compact Sidebar Version)
  // =========================================================================
  
  // DOM Elements - Vocal Training
  const btnSetupMic = document.getElementById('btnSetupMic');
  const micSetupText = document.getElementById('micSetupText');
  const micMeterFill = document.getElementById('micMeterFill');
  const micClipDot = document.getElementById('micClipDot');
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
      micSetupText.textContent = '...';
      
      const result = await engine.requestMicrophoneAccess();
      
      if (result.success) {
        microphoneReady = true;
        btnSetupMic.classList.add('active');
        micSetupText.textContent = 'Mic on';
        btnRecord.disabled = false;
        showToast('Microphone connected! Ready to record.', 'success');
      } else {
        btnSetupMic.disabled = false;
        micSetupText.textContent = 'Mic';
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
  });

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


  // --- Updates: the server checks GitHub in the background; this shows a bar when something newer exists ---
  const updateBar = document.getElementById('updateBar');
  if (updateBar) {
    const updateText = document.getElementById('updateText');
    const updateNow = document.getElementById('updateNow');
    const updateLater = document.getElementById('updateLater');
    const updateMore = document.getElementById('updateMore');
    let updateBusy = false;

    const showUpdate = (info) => {
      const n = info.behind || 0;
      updateText.textContent = `A new version of Stems Studio is available (${n} update${n === 1 ? '' : 's'}).`;
      updateMore.textContent = (info.changes || []).map(line => '\u2022 ' + line).join('\n');
      updateMore.hidden = !info.changes || !info.changes.length;
      updateNow.hidden = false;
      updateNow.disabled = false;
      updateLater.hidden = false;
      updateBar.hidden = false;
    };

    updateLater.addEventListener('click', () => { updateBar.hidden = true; });

    updateNow.addEventListener('click', async () => {
      if (updateBusy) return;
      updateBusy = true;
      updateNow.disabled = true;
      updateText.textContent = 'Updating...';
      try {
        const res = await fetch('/api/update/apply', { method: 'POST' });
        const out = await res.json();
        updateText.textContent = out.message + (out.run_install ? ' The setup changed too: run Install.bat once after reopening.' : '');
        updateMore.hidden = true;
        updateNow.hidden = out.ok;
        updateNow.disabled = false;
        updateLater.hidden = out.ok;
        if (!out.ok) updateLater.hidden = false;
        if (out.ok && out.restart) {
          const previous = engineBuild;
          // Reload only after the old engine has actually gone. An empty previous
          // version would otherwise match the still-running engine and reload too soon.
          let sawGap = false;
          const started = Date.now();
          const waitForRestart = async () => {
            if (Date.now() - started > 20000) {
              updateText.textContent = 'Updated. Close this window and open Stems Studio again.';
              return;
            }
            try {
              const info = await (await fetch('/api/engine')).json();
              if (sawGap && info.version && info.version !== previous) {
                location.reload();
                return;
              }
            } catch (err) {
              sawGap = true;
            }
            setTimeout(waitForRestart, 400);
          };
          setTimeout(waitForRestart, 700);
        }
      } catch (err) {
        updateText.textContent = 'The update could not be started.';
        updateNow.disabled = false;
      }
      updateBusy = false;
    });

    (async () => {
      for (let attempt = 0; attempt < 8; attempt++) {
        await new Promise(resolve => setTimeout(resolve, attempt === 0 ? 7000 : 5000));
        try {
          const info = await (await fetch('/api/update')).json();
          if (info.state === 'available') { showUpdate(info); return; }
          if (info.state !== 'idle' && info.state !== 'checking') return;
        } catch (err) { return; }
      }
    })();
  }
});
