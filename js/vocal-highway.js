/**
 * Stems Studio - Vocal Highway
 *
 * A scrolling "note highway" that sits above the seek bar. It shows the pitch of the
 * vocal stem: the notes travel from the right towards a fixed "now" line, like a karaoke
 * game. Pitch is analysed automatically, in a background worker, whenever a vocal stem
 * is loaded.
 */

// Runs inside a Web Worker (it is turned into source text below, so it must not use
// anything from the page). Finds the sung pitch with the YIN method on a low-rate copy of
// the vocal, which keeps a whole song to a second or two.
function vocalHighwayWorkerMain() {
  self.onmessage = (e) => {
    const { id, samples, fs } = e.data;
    const W = 512;                                  // analysis window (samples)
    const hop = 256;                                // step between analyses
    const maxTau = Math.floor(fs / 70);             // lowest pitch we look for: 70 Hz
    const minTau = Math.max(2, Math.floor(fs / 1000)); // highest: 1000 Hz
    const need = W + maxTau + 1;
    const frames = samples.length >= need ? Math.floor((samples.length - need) / hop) + 1 : 0;

    // Loudness of each step, to skip silence and breath noise.
    const rms = new Float32Array(frames);
    for (let f = 0; f < frames; f++) {
      const s = f * hop;
      let sum = 0;
      for (let j = 0; j < W; j++) { const v = samples[s + j]; sum += v * v; }
      rms[f] = Math.sqrt(sum / W);
    }
    const sorted = Array.from(rms).sort((a, b) => a - b);
    const p90 = frames ? sorted[Math.floor(frames * 0.9)] : 0;
    const gate = Math.max(0.003, p90 * 0.08);

    const midi = new Float32Array(frames);          // 0 = no pitch (silence or noise)
    const d = new Float32Array(maxTau + 1);
    for (let f = 0; f < frames; f++) {
      if (rms[f] < gate) continue;
      const s = f * hop;
      d[0] = 1;
      let running = 0;
      for (let tau = 1; tau <= maxTau; tau++) {
        let sum = 0;
        for (let j = 0; j < W; j++) {
          const delta = samples[s + j] - samples[s + j + tau];
          sum += delta * delta;
        }
        running += sum;
        d[tau] = running > 0 ? (sum * tau) / running : 1;
      }
      let found = -1;
      for (let tau = minTau; tau < maxTau; tau++) {
        if (d[tau] < 0.12) {
          while (tau + 1 < maxTau && d[tau + 1] < d[tau]) tau++;
          found = tau;
          break;
        }
      }
      if (found < 0) continue;
      let better = found;
      if (found > 1 && found < maxTau) {
        const s0 = d[found - 1], s1 = d[found], s2 = d[found + 1];
        const den = 2 * (2 * s1 - s2 - s0);
        if (den !== 0) better = found + (s2 - s0) / den;
      }
      const hz = fs / better;
      if (hz < 70 || hz > 1000) continue;
      midi[f] = 69 + 12 * Math.log2(hz / 440);
    }
    self.postMessage({ id, midi, t0: (W / 2) / fs, dt: hop / fs }, [midi.buffer]);
  };
}

// The 12 notes of the Indian scale, counted from Sa. A small letter means "komal" (flat).
const SARGAM_12 = ['Sa', 're', 'Re', 'ga', 'Ga', 'Ma', "Ma'", 'Pa', 'dha', 'Dha', 'ni', 'Ni'];
const MAJOR_DEGREES = [0, 2, 4, 5, 7, 9, 11];
const MINOR_DEGREES = [0, 2, 3, 5, 7, 8, 10];
const FLAT_MAJOR_TONICS = [5, 10, 3, 8, 1, 6];
const FLAT_MINOR_TONICS = [2, 7, 0, 5, 10, 3];

// Colours of the drum lanes.
const DRUM_COLORS = { kick: '#f43f5e', snare: '#f59e0b', toms: '#a855f7', hh: '#22d3ee', ride: '#38bdf8', crash: '#facc15' };

// How each stem can be shown. "melody" suits instruments that play one note at a time.
// "notes" is the piano roll, for chords and anything polyphonic.
const HIGHWAY_SOURCES = {
  vocals: [{ kind: 'melody', label: 'Vocals' }],
  bass: [{ kind: 'melody', label: 'Bass' }],
  guitar_lead: [{ kind: 'melody', label: 'Lead guitar' }],
  guitar: [{ kind: 'melody', label: 'Guitar (one note at a time)' }, { kind: 'notes', label: 'Guitar (chords)' }],
  guitar_rhythm: [{ kind: 'notes', label: 'Rhythm guitar (chords)' }],
  piano: [{ kind: 'notes', label: 'Piano (chords)' }, { kind: 'melody', label: 'Piano (one note at a time)' }],
  other: [{ kind: 'notes', label: 'Other (chords)' }]
};

// Bar colours per stem: [start, end, lit, played]
const HIGHWAY_COLORS = {
  vocals: ['#8b5cf6', '#ec4899', '#f9a8d4', 'rgba(139, 92, 246, 0.32)'],
  bass: ['#0ea5e9', '#6366f1', '#bae6fd', 'rgba(14, 165, 233, 0.30)'],
  guitar: ['#22c55e', '#84cc16', '#d9f99d', 'rgba(34, 197, 94, 0.30)'],
  guitar_lead: ['#22c55e', '#84cc16', '#d9f99d', 'rgba(34, 197, 94, 0.30)'],
  guitar_rhythm: ['#16a34a', '#14b8a6', '#99f6e4', 'rgba(20, 184, 166, 0.30)'],
  piano: ['#f59e0b', '#f97316', '#fde68a', 'rgba(245, 158, 11, 0.30)'],
  other: ['#a855f7', '#6366f1', '#e9d5ff', 'rgba(168, 85, 247, 0.30)']
};

// Chord shapes: semitones above the root. The first match with the fewest extra notes wins.
const CHORD_SHAPES = [
  { suffix: '', tones: [0, 4, 7] },
  { suffix: 'm', tones: [0, 3, 7] },
  { suffix: '7', tones: [0, 4, 7, 10] },
  { suffix: 'maj7', tones: [0, 4, 7, 11] },
  { suffix: 'm7', tones: [0, 3, 7, 10] },
  { suffix: '6', tones: [0, 4, 7, 9] },
  { suffix: 'm6', tones: [0, 3, 7, 9] },
  { suffix: 'add9', tones: [0, 2, 4, 7] },
  { suffix: 'dim', tones: [0, 3, 6] },
  { suffix: 'm7b5', tones: [0, 3, 6, 10] },
  { suffix: 'aug', tones: [0, 4, 8] },
  { suffix: 'sus2', tones: [0, 2, 7] },
  { suffix: 'sus4', tones: [0, 5, 7] },
  { suffix: '5', tones: [0, 7] }
];

class VocalHighway {
  constructor({ canvas, engine, bar }) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.engine = engine;

    this.windowSeconds = 10;   // how much time is visible at once
    this.nowFraction = 0.25;   // where the "now" line sits across the lane
    this.gutter = 108;         // room for the note names and the Sa Re Ga names on the left
    this.chordBarHeight = 28;  // the chord ribbon along the top

    // The key found by the engine (detected) and the one being shown (it may be changed by hand).
    this.detected = null;      // { tonic, mode, name, flats, certainty, relative, alternatives }
    this.key = null;           // { tonic, mode, flats, manual }
    this.chords = [];          // [{ start, end, root, quality, name }]
    this.showChords = false;   // turned on only when a chord survived the bass check
    this.analysisUrl = null;   // set by the app: where the engine keeps this song's key and chords
    this.keyRequestId = 0;
    this.listenId = null;
    this.listenTimer = null;
    this.listenReveal = null;
    this.listenHide = null;
    this.tuningCents = 0;
    this.barEls = null;
    this.barRoot = bar || null;

    this.NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];

    // What the highway follows. Each source is one stem shown one way: as a single melody line
    // ("melody", found with the pitch tracker) or as every note that sounds ("notes", a piano roll).
    this.songInfo = null;      // set by the app: { songId, stems: [{ file, trackId }] } or null
    this.sources = [];         // [{ key, file, trackId, kind, label }]
    this.active = null;        // the source on show
    this.cache = new Map();    // source key -> its finished view, so switching is instant
    this.songToken = 0;        // changes with every song, so a late answer for an old song is ignored
    this.kind = 'melody';
    this.roll = [];            // piano-roll mode: [{ start, end, midi, strength }]
    this.rollChords = [];      // chords worked out from the notes that sound together
    this.lanes = [];           // drum mode: [{ id, label, hits: [[time, strength]...] }]
    this.approximateDrums = false;
    this.cleanNotes = [];      // melody mode: the sung notes
    this.roughNotes = [];      // melody mode: guesses at growls and screams (dashed, not scored)
    this.roughMidi = null;
    this.roughAuto = false;    // the server found the vocal mostly rough: show those guesses by default
    this.roughChoice = null;   // null = follow roughAuto, or what the singer ticked
    this.showRough = false;
    this.rollMinStrength = this.loadNumber('stemsStudio.rollMinStrength', 0.4);
    this.shift = 0;            // semitones the engine's pitch control moves everything up or down
    this.coach = null;         // the singing coach draws on top of the highway (js/singing-coach.js)

    this.state = 'idle';       // idle | analyzing | ready | nopitch | error
    this.pitchError = '';
    this.buffer = null;
    this.midi = null;
    this.t0 = 0;
    this.dt = 0.0213;
    this.notes = [];
    this.minMidi = 48;
    this.maxMidi = 72;
    this.analysisId = 0;
    this.worker = null;
    this.lastKey = '';
    this.width = 0;
    this.height = 0;

    this.resize();
    if (typeof ResizeObserver !== 'undefined') {
      new ResizeObserver(() => this.resize()).observe(canvas);
    } else {
      window.addEventListener('resize', () => this.resize());
    }
    canvas.addEventListener('click', (e) => this.handleClick(e));
    if (this.barRoot) this.setupBar(this.barRoot);

    this.loop = this.loop.bind(this);
    requestAnimationFrame(this.loop);
  }

  resize() {
    const dpr = window.devicePixelRatio || 1;
    const rect = this.canvas.getBoundingClientRect();
    if (!rect.width || !rect.height) return;
    this.canvas.width = Math.round(rect.width * dpr);
    this.canvas.height = Math.round(rect.height * dpr);
    this.ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    this.width = rect.width;
    this.height = rect.height;
    this.lastKey = '';
  }

  layout() {
    const plotW = Math.max(1, this.width - this.gutter);
    return {
      plotW,
      nowX: this.gutter + plotW * this.nowFraction,
      pxPerSec: plotW / this.windowSeconds
    };
  }

  handleClick(e) {
    if (this.state !== 'ready') return;
    const rect = this.canvas.getBoundingClientRect();
    const x = e.clientX - rect.left;
    if (x < this.gutter) return;
    const { nowX, pxPerSec } = this.layout();
    this.engine.seek(this.engine.getCurrentTime() + (x - nowX) / pxPerSec);
  }

  // --- following the song ----------------------------------------------------------

  loop() {
    if (this.analysisUrl) {
      const url = this.analysisUrl;
      this.analysisUrl = null;       // used once per song
      this.fetchAnalysis(url);
    }
    this.checkBuffer();
    this.followPitchControl();
    const t = this.engine.getCurrentTime();
    // The coach has a live line on top, so it needs a fresh picture on every frame while it runs.
    const live = this.coach && this.coach.needsRedraw() ? performance.now() : 0;
    const key = `${t.toFixed(3)}|${this.width}|${this.height}|${this.state}|${this.notes.length}|${live}`;
    if (key !== this.lastKey) {
      this.lastKey = key;
      this.draw(t);
    }
    requestAnimationFrame(this.loop);
  }

  loadNumber(name, fallback) {
    try {
      const value = Number(localStorage.getItem(name));
      return localStorage.getItem(name) !== null && Number.isFinite(value) ? value : fallback;
    } catch (err) {
      return fallback;
    }
  }

  // The engine's pitch control moves the whole song, so everything the highway shows moves with it.
  followPitchControl() {
    const shift = Math.round(this.engine.pitchSemitones || 0);
    if (shift === this.shift) return;
    this.shift = shift;
    this.applyKeyRange();
    this.refreshBar();
    this.lastKey = '';
  }

  // The home note as it sounds now (the key found in the song, moved by the pitch control).
  get tonic() {
    return this.key ? (((this.key.tonic + this.shift) % 12) + 12) % 12 : 0;
  }

  // A new song has loaded (or the old one is gone): work out which stems can be followed.
  checkBuffer() {
    const info = this.songInfo;
    const first = info && info.stems.length ? info.stems[0].trackId : 'vocal';
    const track = this.engine.tracks.get(first);
    const buffer = track && track.buffer ? track.buffer : null;
    if (buffer === this.buffer) return;
    this.buffer = buffer;
    this.songToken++;
    this.analysisId++;
    this.cache.clear();
    this.roughChoice = null;       // a new song starts with the automatic choice again
    this.active = null;
    this.clearView();
    if (!buffer) {
      this.sources = [];
      this.state = 'idle';
      this.refreshSources();
      return;
    }
    this.sources = this.buildSources(info);
    this.refreshSources();
    if (this.sources.length) this.selectSource(this.sources[0].key);
  }

  buildSources(info) {
    if (!info) return [{ key: 'vocals:melody', file: 'vocals', trackId: 'vocal', kind: 'melody', label: 'Vocals', url: null }];
    const out = [];
    let hasDrums = false;
    for (const stem of info.stems) {
      // The whole drum track or its parts (kick, snare...) both give one drum-hits view.
      if (stem.file === 'drums' || stem.file.startsWith('drums_')) {
        if (!hasDrums) out.push({ key: 'drums:drums', file: 'drums', trackId: stem.trackId, kind: 'drums', label: 'Drums (hits)', songId: info.songId });
        hasDrums = true;
        continue;
      }
      (HIGHWAY_SOURCES[stem.file] || []).forEach((mode) => {
        out.push({ key: `${stem.file}:${mode.kind}`, file: stem.file, trackId: stem.trackId, kind: mode.kind, label: mode.label, songId: info.songId });
      });
    }
    return out;
  }

  // What is held per source, so switching back to a source costs nothing.
  saveView() {
    if (!this.active) return;
    if (this.state === 'ready' || this.state === 'nopitch') {
      this.cache.set(this.active.key, {
        state: this.state, midi: this.midi, t0: this.t0, dt: this.dt, notes: this.notes,
        baseMin: this.baseMin, baseMax: this.baseMax, roll: this.roll, rawRoll: this.rawRoll,
        lanes: this.lanes, approximateDrums: this.approximateDrums,
        cleanNotes: this.cleanNotes, roughNotes: this.roughNotes, roughMidi: this.roughMidi,
        roughAuto: this.roughAuto, rangeClean: this.rangeClean, rangeRough: this.rangeRough
      });
    }
  }

  clearView() {
    this.midi = null;
    this.notes = [];
    this.roll = [];
    this.rawRoll = [];
    this.rollChords = [];
    this.lanes = [];
    this.approximateDrums = false;
    this.cleanNotes = [];
    this.roughNotes = [];
    this.roughMidi = null;
    this.roughAuto = false;
    this.rangeClean = null;
    this.rangeRough = null;
    this.showRough = false;
    this.baseMin = undefined;
    this.baseMax = undefined;
    this.pitchError = '';
  }

  applyView(view) {
    this.state = view.state;
    this.midi = view.midi;
    this.t0 = view.t0;
    this.dt = view.dt;
    this.notes = view.notes;
    this.baseMin = view.baseMin;
    this.baseMax = view.baseMax;
    this.rawRoll = view.rawRoll || [];
    this.lanes = view.lanes || [];
    this.approximateDrums = Boolean(view.approximateDrums);
    this.cleanNotes = view.cleanNotes || [];
    this.roughNotes = view.roughNotes || [];
    this.roughMidi = view.roughMidi || null;
    this.roughAuto = Boolean(view.roughAuto);
    this.rangeClean = view.rangeClean || null;
    this.rangeRough = view.rangeRough || null;
    this.filterRoll();
    this.chooseRough();
    this.applyKeyRange();
  }

  // Which melody notes are on show: the sung ones, and (when asked for, or when the voice is mostly
  // rough) the dashed guesses at growls and screams.
  chooseRough() {
    if (this.kind !== 'melody' || !this.cleanNotes.length && !this.roughNotes.length) {
      this.showRough = false;
    } else {
      this.showRough = this.roughNotes.length > 0 && (this.roughChoice === null ? this.roughAuto : this.roughChoice);
      this.notes = this.showRough
        ? this.cleanNotes.concat(this.roughNotes).sort((a, b) => a.start - b.start)
        : this.cleanNotes;
      const range = this.showRough && this.rangeRough ? this.rangeRough : this.rangeClean;
      if (range) { this.baseMin = range.min; this.baseMax = range.max; }
      if (this.state === 'nopitch' && this.notes.length) this.state = 'ready';
      if (this.state === 'ready' && !this.notes.length) this.state = 'nopitch';
    }
    this.singableCache = null;
    if (this.barEls && this.barEls.roughWrap) {
      this.barEls.roughWrap.hidden = !(this.kind === 'melody' && this.roughNotes.length);
      this.barEls.rough.checked = this.showRough;
    }
  }

  // The notes a singer can be scored on (growl guesses are not).
  get singableNotes() {
    if (this.singableCache && this.singableCache.source === this.notes) return this.singableCache.list;
    const list = this.notes.filter((note) => !note.rough);
    this.singableCache = { source: this.notes, list };
    return list;
  }

  selectSource(key) {
    const source = this.sources.find((s) => s.key === key);
    if (!source) return;
    if (this.active && this.active !== source) this.saveView();
    this.active = source;
    this.kind = source.kind;
    this.clearView();
    const cached = this.cache.get(key);
    if (cached) this.applyView(cached);
    else {
      this.state = 'analyzing';
      this.loadSource(source);
    }
    if (this.barEls && this.barEls.source) this.barEls.source.value = key;
    this.refreshSources();
    this.lastKey = '';
    if (this.coach) this.coach.sourceChanged();
  }

  async loadSource(source) {
    const token = this.songToken;
    const info = this.songInfo;
    const finish = (view) => {
      if (token !== this.songToken) return;
      this.cache.set(source.key, view);
      if (this.active === source) { this.applyView(view); this.lastKey = ''; if (this.coach) this.coach.sourceChanged(); }
    };
    const fail = (state, message) => {
      if (token !== this.songToken) return;
      if (this.active === source) {
        this.clearView();
        this.state = state;
        this.pitchError = message || '';
        this.lastKey = '';
      }
    };
    if (!info) {      // a stem that is not in the library: the browser does its own, simpler analysis
      const track = this.engine.tracks.get(source.trackId);
      if (!track || !track.buffer) return fail('error');
      this.analyze(track.buffer, source, finish, fail);
      return;
    }
    if (source.kind === 'drums') {
      try {
        const resp = await fetch(`/api/hits/${info.songId}`);
        if (!resp.ok) throw new Error(`request failed (${resp.status})`);
        const data = await resp.json();
        finish(this.makeDrumView(data));
      } catch (err) {
        console.warn(`Server could not find the drum hits (${err.message})`);
        fail('error');
      }
      return;
    }
    const base = source.kind === 'notes' ? '/api/notes/' : '/api/pitch/';
    try {
      const resp = await fetch(`${base}${info.songId}?stem=${encodeURIComponent(source.file)}`);
      const data = await resp.json().catch(() => ({}));
      if (!resp.ok) throw new Error(data.error || `request failed (${resp.status})`);
      if (source.kind === 'notes') finish(this.makeRollView(data.notes));
      else finish(this.makeMelodyView(Float32Array.from(data.midi), data.t0, data.dt, true, data));
    } catch (err) {
      console.warn(`Server could not read the ${source.label} (${err.message})`);
      const track = this.engine.tracks.get(source.trackId);
      if (source.kind === 'melody' && track && track.buffer) {
        this.analyze(track.buffer, source, finish, fail);   // the page's own pitch read, so the lane is not left blank
      } else {
        fail('error', err.message);
      }
    }
  }

  refreshSources() {
    const els = this.barEls;
    if (!els || !els.source) return;
    els.source.innerHTML = '';
    this.sources.forEach((source) => {
      const option = document.createElement('option');
      option.value = source.key;
      option.textContent = source.label;
      els.source.appendChild(option);
    });
    if (this.active) els.source.value = this.active.key;
    els.sourceWrap.hidden = this.sources.length < 2;
    els.detailWrap.hidden = this.kind !== 'notes';
  }

  makeDrumView(data) {
    const lanes = (data.lanes || []).filter((lane) => lane.hits.length);
    return { state: lanes.length ? 'ready' : 'nopitch', midi: null, t0: 0, dt: 0.02, notes: [], lanes, approximateDrums: data.approximate };
  }

  // --- piano-roll mode: all the notes, and the chords they make together ----------------

  makeRollView(rawNotes) {
    const raw = rawNotes.map(([start, end, midi, strength]) => ({ start, end, midi, strength }));
    if (raw.length < 3) return { state: 'nopitch', midi: null, t0: 0, dt: 0.02, notes: [], rawRoll: raw };
    // The range comes from the clearer notes, so a few stray high or low guesses do not stretch the lane.
    const clear = raw.filter((n) => n.strength >= 0.45);
    const midis = (clear.length >= 10 ? clear : raw).map((n) => n.midi).sort((a, b) => a - b);
    let lo = midis[Math.floor(midis.length * 0.03)] - 2;
    let hi = midis[Math.min(midis.length - 1, Math.floor(midis.length * 0.97))] + 2;
    while (hi - lo < 16) { lo--; hi++; }
    return {
      state: 'ready', midi: null, t0: 0, dt: 0.02, notes: [], rawRoll: raw,
      baseMin: Math.max(21, lo), baseMax: Math.min(100, hi)
    };
  }

  setRollSensitivity(minStrength) {
    this.rollMinStrength = minStrength;
    try { localStorage.setItem('stemsStudio.rollMinStrength', String(minStrength)); } catch (err) { /* private mode */ }
    this.filterRoll();
    this.lastKey = '';
  }

  filterRoll() {
    this.roll = this.kind === 'notes' ? (this.rawRoll || []).filter((n) => n.strength >= this.rollMinStrength) : [];
    this.rollChords = this.kind === 'notes' ? this.chordsFromNotes(this.roll) : [];
  }

  // Chords from the notes that sound together: cut the time at every note start and end, name the
  // set of notes in each piece, and join neighbours that got the same name. Rough, like the rest.
  chordsFromNotes(notes) {
    const edges = new Set();
    for (const n of notes) { edges.add(n.start); edges.add(n.end); }
    const times = Array.from(edges).sort((a, b) => a - b);
    const pieces = [];
    let cursor = 0;     // notes are sorted by start, so only look at the ones near this piece
    for (let i = 0; i + 1 < times.length; i++) {
      const start = times[i];
      const end = times[i + 1];
      if (end - start < 0.08) continue;
      while (cursor < notes.length && notes[cursor].end <= start - 30) cursor++;
      const sounding = [];
      for (let k = cursor; k < notes.length && notes[k].start < end; k++) {
        if (notes[k].start <= start + 0.001 && notes[k].end >= end - 0.001) sounding.push(notes[k].midi);
      }
      const chord = this.nameChord(sounding);
      if (chord) pieces.push({ start, end, ...chord });
    }
    const merged = [];
    for (const piece of pieces) {
      const last = merged[merged.length - 1];
      if (last && last.root === piece.root && last.quality === piece.quality && piece.start - last.end < 0.3) last.end = piece.end;
      else merged.push({ ...piece });
    }
    return merged.filter((c) => c.end - c.start >= 0.25);
  }

  // The best chord name for a set of MIDI notes, or null when they do not make one.
  nameChord(midis) {
    const classes = new Set(midis.map((m) => ((m % 12) + 12) % 12));
    if (classes.size < 2) return null;
    const bass = ((Math.min(...midis) % 12) + 12) % 12;
    let best = null;
    for (const root of classes) {
      for (const shape of CHORD_SHAPES) {
        if (shape.tones.length === 2 && (classes.size > 2 || root !== bass)) continue;   // a "5" chord: two notes, the root lowest
        if (!shape.tones.every((tone) => classes.has((root + tone) % 12))) continue;
        const extras = classes.size - shape.tones.length;
        const score = shape.tones.length * 2 - extras * 1.5 + (root === bass ? 1 : 0);
        if (!best || score > best.score) best = { score, root, quality: shape.suffix };
      }
    }
    if (!best) return null;
    return { root: best.root, quality: best.quality, bass: bass !== best.root ? bass : null };
  }

  // --- key, scale and chords ------------------------------------------------------------

  setupBar(bar) {
    const els = {
      text: bar.querySelector('#highwayKeyText'),
      tonic: bar.querySelector('#highwayTonic'),
      mode: bar.querySelector('#highwayMode'),
      reset: bar.querySelector('#highwayKeyReset'),
      chords: bar.querySelector('#highwayShowChords'),
      source: bar.querySelector('#highwaySource'),
      sourceWrap: bar.querySelector('#highwaySourceWrap'),
      detail: bar.querySelector('#highwayDetail'),
      detailWrap: bar.querySelector('#highwayDetailWrap'),
      roughWrap: bar.querySelector('#highwayRoughWrap'),
      rough: bar.querySelector('#highwayRough')
    };
    this.barEls = els;
    els.source.addEventListener('change', () => this.selectSource(els.source.value));
    if (els.rough) {
      els.rough.addEventListener('change', () => {
        this.roughChoice = els.rough.checked;
        this.chooseRough();
        this.applyKeyRange();
        this.lastKey = '';
        if (this.coach) this.coach.sourceChanged();
      });
    }
    // The slider runs from "fewer notes" (left) to "more notes" (right); the setting is the weakest
    // note strength that is still shown.
    els.detail.value = String(Math.round((0.7 - this.rollMinStrength) * 100));
    els.detail.addEventListener('input', () => this.setRollSensitivity(0.7 - Number(els.detail.value) / 100));
    // The "Sa =" list is spelled in sharps; flats are used on the lane when the key calls for them.
    this.NOTE_NAMES.forEach((name, pc) => {
      const option = document.createElement('option');
      option.value = String(pc);
      option.textContent = name;
      els.tonic.appendChild(option);
    });
    const changed = () => {
      this.key = {
        tonic: Number(els.tonic.value),
        mode: els.mode.value,
        flats: this.prefersFlats(Number(els.tonic.value), els.mode.value),
        manual: true
      };
      this.applyKeyRange();
      this.refreshBar();
      this.lastKey = '';
    };
    els.tonic.addEventListener('change', changed);
    els.mode.addEventListener('change', changed);
    els.reset.addEventListener('click', () => {
      if (this.detected) this.setKey(this.detected, false);
    });
    if (els.chords) {
      els.chords.checked = false;
      this.showChords = false;
    }
    const sheetBtn = bar.querySelector('#chordSheetBtn');
    const sheetPanel = bar.querySelector('#chordSheetPanel');
    const sheetSave = bar.querySelector('#chordSheetSave');
    const sheetClear = bar.querySelector('#chordSheetClear');
    const sheetBox = bar.querySelector('#chordSheetText');
    const sheetStatus = bar.querySelector('#chordSheetStatus');
    if (sheetBtn && sheetPanel) {
      const placeSheet = () => {
        const rect = sheetBtn.getBoundingClientRect();
        sheetPanel.style.top = `${Math.round(rect.bottom + 6)}px`;
        sheetPanel.style.left = `${Math.round(Math.min(rect.left, window.innerWidth - 336))}px`;
      };
      sheetBtn.addEventListener('click', () => {
        sheetPanel.hidden = !sheetPanel.hidden;
        if (!sheetPanel.hidden) placeSheet();
      });
      window.addEventListener('resize', () => {
        if (!sheetPanel.hidden) placeSheet();
      });
      const sendSheet = async (text) => {
        const songId = this.songInfo && this.songInfo.songId;
        if (!songId) {
          if (sheetStatus) sheetStatus.textContent = 'Open a song first.';
          return;
        }
        if (sheetStatus) sheetStatus.textContent = 'Checking the sheet against the bass.';
        try {
          const resp = await fetch(`/api/analysis/${songId}/sheet`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ sheet: text })
          });
          const data = await resp.json().catch(() => ({}));
          if (!resp.ok) throw new Error(data.error || 'Could not save that sheet.');
          this.analysisUrl = `/api/analysis/${songId}`;
        } catch (err) {
          if (sheetStatus) sheetStatus.textContent = err.message || 'Could not save that sheet.';
        }
      };
      if (sheetSave) sheetSave.addEventListener('click', () => sendSheet(sheetBox ? sheetBox.value : ''));
      if (sheetClear) sheetClear.addEventListener('click', () => {
        if (sheetBox) sheetBox.value = '';
        sendSheet('');
      });
    }
    this.refreshBar();
  }

  prefersFlats(tonic, mode) {
    return (mode === 'major' ? FLAT_MAJOR_TONICS : FLAT_MINOR_TONICS).includes(tonic);
  }

  setKey(key, manual) {
    this.key = { tonic: key.tonic, mode: key.mode, flats: this.prefersFlats(key.tonic, key.mode), manual };
    this.applyKeyRange();
    this.refreshBar();
    this.lastKey = '';
  }

  listenSongId(url) {
    const match = /\/api\/analysis\/([0-9a-f]{8})(?:$|[/?])/.exec(url || '');
    return match ? match[1] : '';
  }

  showListenBars() {
    const highway = document.getElementById('highwayListen');
    const sheet = document.getElementById('chordSheetProgress');
    if (highway) highway.hidden = false;
    if (sheet) sheet.hidden = false;
    for (const id of ['highwayListenFill', 'chordSheetFill']) {
      const fill = document.getElementById(id);
      if (fill && (!fill.style.width || fill.style.width === '0%')) fill.style.width = '3%';
    }
  }

  paintListen(percent, message, running) {
    const width = `${Math.max(0, Math.min(100, percent))}%`;
    const highwayFill = document.getElementById('highwayListenFill');
    const sheetFill = document.getElementById('chordSheetFill');
    const label = document.getElementById('chordSheetProgressLabel');
    if (highwayFill) highwayFill.style.width = width;
    if (sheetFill) sheetFill.style.width = width;
    if (label && message) label.textContent = message;
    if (running && message && this.barEls) this.barEls.text.textContent = message;
  }

  // The listen can take a while on an older song. Poll its stages and draw them.
  startListenProgress(songId, requestId) {
    this.stopListenProgress(false);
    this.listenId = requestId;
    const reveal = () => {
      if (this.listenId === requestId) this.showListenBars();
    };
    this.listenReveal = setTimeout(reveal, 450);
    const tick = async () => {
      if (this.listenId !== requestId) return;
      try {
        const resp = await fetch(`/api/analysis/${songId}/progress`);
        if (!resp.ok || this.listenId !== requestId) return;
        const data = await resp.json();
        if (this.listenId !== requestId) return;
        const percent = Number(data.progress) || 0;
        if (data.running) this.showListenBars();
        this.paintListen(percent, data.message || '', Boolean(data.running));
      } catch (err) {
        // The analysis request still owns the result.
      }
    };
    tick();
    this.listenTimer = setInterval(tick, 400);
  }

  stopListenProgress(done) {
    if (this.listenTimer) {
      clearInterval(this.listenTimer);
      this.listenTimer = null;
    }
    if (this.listenReveal) {
      clearTimeout(this.listenReveal);
      this.listenReveal = null;
    }
    if (this.listenHide) {
      clearTimeout(this.listenHide);
      this.listenHide = null;
    }
    this.listenId = null;
    const highway = document.getElementById('highwayListen');
    const sheet = document.getElementById('chordSheetProgress');
    const highwayFill = document.getElementById('highwayListenFill');
    const sheetFill = document.getElementById('chordSheetFill');
    if (!done) {
      if (highway) highway.hidden = true;
      if (sheet) sheet.hidden = true;
      if (highwayFill) highwayFill.style.width = '0%';
      if (sheetFill) sheetFill.style.width = '0%';
      return;
    }
    if (highway && !highway.hidden) {
      if (highwayFill) highwayFill.style.width = '100%';
    }
    if (sheet && !sheet.hidden) {
      if (sheetFill) sheetFill.style.width = '100%';
    }
    this.listenHide = setTimeout(() => {
      if (this.listenId) return;
      if (highway) highway.hidden = true;
      if (sheet) sheet.hidden = true;
      if (highwayFill) highwayFill.style.width = '0%';
      if (sheetFill) sheetFill.style.width = '0%';
    }, 700);
  }

  // Forget the key and chords (a new song is loading, or the song has none).
  resetKey() {
    this.keyRequestId++;
    this.stopListenProgress(false);
    this.detected = null;
    this.key = null;
    this.chords = [];
    this.showChords = false;
    this.applyKeyRange();
    this.refreshBar();
    this.lastKey = '';
  }

  async fetchAnalysis(url) {
    this.resetKey();
    const id = this.keyRequestId;
    const songId = this.listenSongId(url);
    if (this.barEls) this.barEls.text.textContent = 'Key: finding it from the bass, instruments and vocal...';
    if (songId) this.startListenProgress(songId, id);
    try {
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`analysis request failed (${resp.status})`);
      const data = await resp.json();
      if (id !== this.keyRequestId) return;
      this.stopListenProgress(true);
      this.detected = data.key || null;
      this.chords = Array.isArray(data.chords) ? data.chords : [];
      this.showChords = this.chords.length > 0;
      this.tuningCents = data.tuning_cents || 0;
      const sheetBox = document.getElementById('chordSheetText');
      const sheetStatus = document.getElementById('chordSheetStatus');
      if (sheetStatus && data.note) sheetStatus.textContent = data.note;
      if (sheetBox && document.activeElement !== sheetBox && typeof data.sheet === 'string') {
        sheetBox.value = data.sheet;
      }
      if (this.detected) this.setKey(this.detected, false);
      else this.refreshBar();
    } catch (err) {
      console.warn('Key and chords unavailable:', err);
      if (id === this.keyRequestId) {
        this.chords = [];
        this.refreshBar('Key: not available (install the extras to turn this on).');
      }
    } finally {
      if (id === this.keyRequestId) this.stopListenProgress(true);
    }
    this.lastKey = '';
  }

  noteSpelling(pc, flats = this.key ? this.prefersFlats(this.tonic, this.key.mode) : false) {
    return (flats ? ['C', 'Db', 'D', 'Eb', 'E', 'F', 'Gb', 'G', 'Ab', 'A', 'Bb', 'B'] : this.NOTE_NAMES)[((pc % 12) + 12) % 12];
  }

  refreshBar(message) {
    const els = this.barEls;
    if (!els) return;
    if (!this.key) {
      els.text.textContent = message || 'Key: not found yet';
      els.reset.hidden = true;
      return;
    }
    // The "Sa =" list is spelled the way this key is spelled (Bb, not A#).
    Array.from(els.tonic.options).forEach((option) => { option.textContent = this.noteSpelling(Number(option.value), this.key.flats); });
    els.tonic.value = String(this.key.tonic);
    els.mode.value = this.key.mode;
    const name = `${this.noteSpelling(this.tonic)} ${this.key.mode}`;
    const d = this.detected;
    let text;
    if (this.key.manual) {
      text = `Key: ${name} (your choice)`;
    } else {
      text = `Key: ${name}`;
      if (d) {
        text += `  \u00B7  ${d.certainty}`;
        if (d.relative) text += `  \u00B7  could also be ${d.relative.name}`;
      }
      if (this.tuningCents && Math.abs(this.tuningCents) >= 10) {
        text += `  \u00B7  tuned ${this.tuningCents > 0 ? '+' : ''}${this.tuningCents} cents`;
      }
    }
    text += `  \u00B7  Sa = ${this.noteSpelling(this.tonic)}`;
    if (this.chords.length) text += '  \u00B7  chords along the top';
    if (this.shift) text += `  (moved ${this.shift > 0 ? '+' : ''}${this.shift} by the pitch control)`;
    els.text.textContent = text;
    els.reset.hidden = !(this.key.manual && this.detected);
  }

  // Which of the 12 notes belong to the scale in use.
  inScale(pc) {
    if (!this.key) return false;
    const degrees = this.key.mode === 'major' ? MAJOR_DEGREES : MINOR_DEGREES;
    return degrees.includes((((pc - this.tonic) % 12) + 12) % 12);
  }

  sargam(pc) {
    if (!this.key) return null;
    return SARGAM_12[(((pc - this.tonic) % 12) + 12) % 12];
  }

  chordName(chord) {
    const bass = chord.bass === null || chord.bass === undefined ? '' : `/${this.noteSpelling(chord.bass + this.shift)}`;
    return `${this.noteSpelling(chord.root + this.shift)}${chord.quality}${bass}`;
  }

  // --- pitch analysis -------------------------------------------------------------
  // The engine (server.py) finds the pitch with a neural detector and cleans it up (see loadSource).
  // When it is not available, the browser falls back to this simpler analysis of the vocal.

  analyze(buffer, source, finish, fail) {
    this.state = 'analyzing';
    const id = ++this.analysisId;
    try {
      // Mono, at about 11-12 kHz: plenty for a singing voice and much faster to analyse.
      const factor = Math.max(1, Math.round(buffer.sampleRate / 11025));
      const fs = buffer.sampleRate / factor;
      const channels = [];
      for (let c = 0; c < buffer.numberOfChannels; c++) channels.push(buffer.getChannelData(c));
      const length = Math.floor(buffer.length / factor);
      const samples = new Float32Array(length);
      const scale = 1 / (factor * channels.length);
      for (let i = 0; i < length; i++) {
        let sum = 0;
        const base = i * factor;
        for (let c = 0; c < channels.length; c++) {
          const data = channels[c];
          for (let k = 0; k < factor; k++) sum += data[base + k];
        }
        samples[i] = sum * scale;
      }

      if (this.worker) this.worker.terminate();
      const source = `(${vocalHighwayWorkerMain.toString()})()`;
      const url = URL.createObjectURL(new Blob([source], { type: 'text/javascript' }));
      this.worker = new Worker(url);
      URL.revokeObjectURL(url);
      this.worker.onmessage = (e) => {
        if (e.data.id !== this.analysisId) return;
        finish(this.makeMelodyView(e.data.midi, e.data.t0, e.data.dt, false));
      };
      this.worker.onerror = (err) => {
        console.error('Vocal highway worker failed', err);
        if (id === this.analysisId) fail('error');
      };
      this.worker.postMessage({ id, samples, fs }, [samples.buffer]);
    } catch (err) {
      console.error('Vocal highway could not start', err);
      fail('error');
    }
  }

  // The finished picture of one melody line: its bars, and how much of the pitch range to show.
  makeMelodyView(midi, t0, dt, alreadyCleaned, extra) {
    // The server's track has had octave errors, breaths and stray blips removed already.
    const smooth = alreadyCleaned ? midi : this.medianSmooth(midi);
    const cleanNotes = this.buildNotes(smooth, t0, dt);
    const view = { state: 'ready', midi: smooth, t0, dt, notes: cleanNotes, cleanNotes, roughNotes: [] };

    // How much of the pitch range to show for a list of MIDI values (or null if there are too few).
    const rangeOf = (values) => {
      const voiced = values.filter((m) => m > 0).sort((a, b) => a - b);
      if (voiced.length < 10) return null;
      const pick = (q) => voiced[Math.min(voiced.length - 1, Math.floor(voiced.length * q))];
      let lo = Math.floor(pick(0.03)) - 2;
      let hi = Math.ceil(pick(0.97)) + 2;
      while (hi - lo < 16) { lo--; hi++; }   // never zoom in tighter than about an octave and a half
      return { min: Math.max(21, lo), max: Math.min(100, hi) };
    };

    // Growls and screams: the server's rough guesses, kept apart from the sung notes.
    let rough = null;
    if (extra && extra.rough_midi) {
      rough = Float32Array.from(extra.rough_midi);
      view.roughMidi = rough;
      view.roughNotes = this.buildNotes(rough, t0, dt).map((note) => Object.assign(note, { rough: true }));
      view.roughAuto = Boolean(extra.rough_auto);
      view.rangeRough = rangeOf(Array.from(smooth).concat(Array.from(rough)));
    }
    view.rangeClean = rangeOf(Array.from(smooth));

    const showingRough = view.roughNotes.length > 0 && (this.roughChoice === null ? view.roughAuto : this.roughChoice);
    const range = showingRough && view.rangeRough ? view.rangeRough : view.rangeClean;
    if (!range || (!cleanNotes.length && !showingRough)) {
      if (!view.roughNotes.length) { view.state = 'nopitch'; return view; }
      view.state = 'nopitch';        // nothing to show unless the singer asks for the rough guesses
      view.baseMin = (view.rangeRough || { min: 48 }).min;
      view.baseMax = (view.rangeRough || { max: 72 }).max;
      return view;
    }
    view.baseMin = range.min;
    view.baseMax = range.max;
    return view;
  }

  // With a key, the lane is stretched to start and end on a Sa, so a whole Sa-to-Sa scale
  // (for example C D E F G A B C) is always on screen. The pitch control moves it all.
  applyKeyRange() {
    if (this.baseMin === undefined) return;
    let lo = this.baseMin + this.shift;
    let hi = this.baseMax + this.shift;
    if (this.key) {
      while ((((lo % 12) + 12) % 12) !== this.tonic) lo--;
      while ((((hi % 12) + 12) % 12) !== this.tonic) hi++;
    }
    this.minMidi = Math.max(21, lo);
    this.maxMidi = Math.min(108, hi);
  }

  // Removes single-frame glitches (octave jumps) by taking the median of neighbours.
  medianSmooth(midi) {
    const out = new Float32Array(midi.length);
    const near = [];
    for (let i = 0; i < midi.length; i++) {
      if (!midi[i]) continue;
      near.length = 0;
      for (let k = Math.max(0, i - 2); k <= Math.min(midi.length - 1, i + 2); k++) {
        if (midi[k]) near.push(midi[k]);
      }
      near.sort((a, b) => a - b);
      out[i] = near[near.length >> 1];
    }
    return out;
  }

  // Turns the pitch track into note bars: one bar per steady note, like a karaoke game.
  buildNotes(midi, t0, dt) {
    const notes = [];
    const n = midi.length;
    const minRun = Math.ceil(0.15 / dt);          // shorter blips are breaths and bleed, not singing
    const bridge = Math.max(1, Math.round(0.045 / dt));
    let i = 0;
    while (i < n) {
      if (!midi[i]) { i++; continue; }
      // A sung phrase: voiced frames, bridging very short gaps.
      let j = i;
      let last = i;
      while (j < n) {
        if (midi[j]) { last = j; j++; }
        else if (j - last <= bridge) j++;
        else break;
      }
      if (last - i + 1 >= minRun) this.splitPhrase(midi, i, last, notes, t0, dt);
      i = last + 1;
    }
    return notes;
  }

  splitPhrase(midi, from, to, notes, t0, dt) {
    const bridge = Math.max(1, Math.round(0.045 / dt));
    const frames = [];
    let held = null;
    for (let k = from; k <= to; k++) {
      const m = midi[k];
      if (!m) continue;
      // Hysteresis: stay on a note until the voice has clearly moved off it.
      if (held === null || Math.abs(m - held) > 0.65) held = Math.round(m);
      frames.push({ k, note: held });
    }
    const groups = [];
    let group = [frames[0]];
    for (let f = 1; f < frames.length; f++) {
      const prev = group[group.length - 1];
      if (frames[f].note === prev.note && frames[f].k - prev.k <= bridge + 1) group.push(frames[f]);
      else { groups.push(group); group = [frames[f]]; }
    }
    groups.push(group);
    for (const g of groups) {
      if (g.length < Math.ceil(0.05 / dt) && groups.length > 1) continue;   // too short to be a note
      notes.push({
        start: t0 + g[0].k * dt,
        end: t0 + (g[g.length - 1].k + 1) * dt,
        midi: g[0].note
      });
    }
  }

  // --- drawing --------------------------------------------------------------------

  // The lane sits under the chord ribbon (when there are chords to show).
  get laneTop() {
    return this.showChords && this.chordsNow.length ? this.chordBarHeight : 0;
  }

  // Chord names that survived the bass check. The piano roll's own guesses stay off this ribbon.
  get chordsNow() {
    if (this.kind === 'drums') return [];
    return this.chords;
  }

  midiToY(midi) {
    const rows = this.maxMidi - this.minMidi + 1;
    const top = this.laneTop;
    const laneH = this.height - top;
    return top + laneH - ((midi - this.minMidi + 0.5) / rows) * laneH;
  }

  noteLabel(midi) {
    return `${this.noteSpelling(midi)}${Math.floor(midi / 12) - 1}`;
  }

  drawMessage(text) {
    const ctx = this.ctx;
    ctx.fillStyle = 'rgba(255, 255, 255, 0.45)';
    ctx.font = '13px "Inter", sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, this.width / 2 + this.gutter / 2, this.height / 2);
  }

  roundedBar(x, y, w, h) {
    const ctx = this.ctx;
    const r = Math.min(h / 2, w / 2);
    ctx.beginPath();
    ctx.moveTo(x + r, y);
    ctx.lineTo(x + w - r, y);
    ctx.arc(x + w - r, y + r, r, -Math.PI / 2, Math.PI / 2);
    ctx.lineTo(x + r, y + h);
    ctx.arc(x + r, y + r, r, Math.PI / 2, (3 * Math.PI) / 2);
    ctx.closePath();
  }

  // Chord names along the top, scrolling with the notes. The chord playing now is lit up.
  drawChordRibbon(t, nowX, pxPerSec) {
    const ctx = this.ctx;
    const gutter = this.gutter;
    const h = this.chordBarHeight;
    ctx.fillStyle = 'rgba(255, 255, 255, 0.025)';
    ctx.fillRect(gutter, 0, this.width - gutter, h);

    ctx.save();
    ctx.beginPath();
    ctx.rect(gutter, 0, this.width - gutter, h);
    ctx.clip();
    const viewStart = t - this.nowFraction * this.windowSeconds - 1;
    const viewEnd = t + (1 - this.nowFraction) * this.windowSeconds + 1;
    ctx.font = 'bold 12px "Inter", sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    for (const chord of this.chordsNow) {
      if (chord.end < viewStart) continue;
      if (chord.start > viewEnd) break;
      const x1 = nowX + (chord.start - t) * pxPerSec;
      const x2 = nowX + (chord.end - t) * pxPerSec;
      const active = chord.start <= t && chord.end > t;
      const past = chord.end <= t;
      ctx.fillStyle = active ? 'rgba(244, 114, 182, 0.9)' : past ? 'rgba(139, 92, 246, 0.14)' : 'rgba(139, 92, 246, 0.32)';
      ctx.fillRect(x1 + 1, 3, Math.max(2, x2 - x1 - 2), h - 6);
      if (x2 - x1 > 16) {
        ctx.fillStyle = active ? '#0b0d12' : past ? 'rgba(255, 255, 255, 0.4)' : '#ffffff';
        ctx.fillText(this.chordName(chord), (Math.max(x1, gutter) + x2) / 2, h / 2 + 1, Math.max(8, x2 - x1 - 4));
      }
    }
    ctx.restore();
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillStyle = 'rgba(255, 255, 255, 0.6)';
    ctx.font = '10px "Inter", sans-serif';
    ctx.fillText(this.kind === 'notes' ? 'Chords from notes' : 'Chords', gutter / 2, h / 2 - 5, gutter - 6);
    ctx.fillStyle = '#fbbf24';
    ctx.font = 'bold 8px "Inter", sans-serif';
    ctx.fillText('VERY EXPERIMENTAL', gutter / 2, h / 2 + 7, gutter - 6);
  }

  drawNowLine({ nowX, top, h }) {
    const ctx = this.ctx;
    ctx.save();
    ctx.shadowColor = 'rgba(99, 102, 241, 0.8)';
    ctx.shadowBlur = 12;
    ctx.strokeStyle = '#ffffff';
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(nowX, top);
    ctx.lineTo(nowX, h);
    ctx.stroke();
    ctx.restore();
  }

  // One melody line: bars, the exact pitch curve over them, and a dot on what sounds now.
  drawMelodyBars(t, hp, colors, barH) {
    const ctx = this.ctx;
    const { timeToX, shift, viewStart, viewEnd, nowX, top } = hp;
    const pcOf = (m) => ((m % 12) + 12) % 12;
    for (const note of this.notes) {
      if (note.end < viewStart || note.start > viewEnd) continue;
      const midi = note.midi + shift;
      if (midi < this.minMidi || midi > this.maxMidi) continue;
      const x1 = timeToX(note.start);
      const x2 = timeToX(note.end);
      const barW = Math.max(4, x2 - x1);
      const y = this.midiToY(midi) - barH / 2;
      const active = note.start <= t && note.end >= t;
      const past = note.end < t;

      ctx.save();
      if (active) {
        ctx.shadowColor = colors[2];
        ctx.shadowBlur = 16;
        ctx.fillStyle = colors[2];
      } else if (past) {
        ctx.fillStyle = colors[3];
      } else {
        const grad = ctx.createLinearGradient(x1, 0, x1 + barW, 0);
        grad.addColorStop(0, colors[0]);
        grad.addColorStop(1, colors[1]);
        ctx.fillStyle = grad;
      }
      // A growl or scream: only a guess at a pitch, so it is drawn amber and dashed.
      if (note.rough) ctx.fillStyle = active ? 'rgba(251, 191, 36, 0.9)' : past ? 'rgba(251, 191, 36, 0.18)' : 'rgba(251, 191, 36, 0.36)';
      this.roundedBar(x1, y, barW, barH);
      ctx.fill();
      if (note.rough) {
        ctx.setLineDash([5, 3]);
        ctx.lineWidth = 1.4;
        ctx.strokeStyle = 'rgba(251, 191, 36, 0.95)';
        ctx.stroke();
      }
      ctx.restore();

      // The singing coach marks each note once it has gone by: green hit, amber off, red missed.
      const result = this.coach ? this.coach.noteResult(note, t) : null;
      if (result) {
        ctx.save();
        ctx.lineWidth = 2;
        ctx.strokeStyle = result === 'hit' ? '#34d399' : result === 'off' ? '#fbbf24' : '#f87171';
        this.roundedBar(x1, y - 1, barW, barH + 2);
        ctx.stroke();
        if (result === 'miss') {
          ctx.fillStyle = 'rgba(248, 113, 113, 0.28)';
          ctx.fill();
        }
        ctx.restore();
      }
    }

    // The exact pitch curve over the bars: shows slides and vibrato inside a note.
    const first = Math.max(0, Math.floor((viewStart - this.t0) / this.dt));
    const lastFrame = Math.min(this.midi.length - 1, Math.ceil((viewEnd - this.t0) / this.dt));
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.7)';
    ctx.lineWidth = 1.4;
    ctx.lineJoin = 'round';
    ctx.beginPath();
    let drawing = false;
    for (let k = first; k <= lastFrame; k++) {
      const m = this.midi[k] ? this.midi[k] + shift : 0;
      // Skip silence and stray detections outside the lane (they would draw wild spikes).
      if (!m || m < this.minMidi - 0.5 || m > this.maxMidi + 0.5) { drawing = false; continue; }
      const x = timeToX(this.t0 + k * this.dt);
      const y = this.midiToY(m);
      if (drawing) ctx.lineTo(x, y);
      else { ctx.moveTo(x, y); drawing = true; }
    }
    ctx.stroke();

    if (this.showRough && this.roughMidi) {
      ctx.save();
      ctx.strokeStyle = 'rgba(251, 191, 36, 0.85)';
      ctx.setLineDash([4, 3]);
      ctx.lineWidth = 1.3;
      ctx.beginPath();
      let roughDrawing = false;
      let previous = 0;
      for (let k = first; k <= Math.min(lastFrame, this.roughMidi.length - 1); k++) {
        const m = this.roughMidi[k] ? this.roughMidi[k] + shift : 0;
        if (!m || m < this.minMidi - 0.5 || m > this.maxMidi + 0.5) { roughDrawing = false; continue; }
        const x = timeToX(this.t0 + k * this.dt);
        const y = this.midiToY(m);
        // A big jump is the guess changing its mind (often by an octave): do not draw a wall across it.
        if (roughDrawing && Math.abs(m - previous) <= 4) ctx.lineTo(x, y);
        else { ctx.moveTo(x, y); roughDrawing = true; }
        previous = m;
      }
      ctx.stroke();
      ctx.restore();
    }

    // The "now" line and a dot on the pitch being sung right now.
    this.drawNowLine(hp);
    const here = Math.round((t - this.t0) / this.dt);
    const nowMidi = here >= 0 && here < this.midi.length && this.midi[here] ? this.midi[here] + shift : 0;
    if (nowMidi) {
      ctx.save();
      ctx.shadowColor = '#ffffff';
      ctx.shadowBlur = 14;
      ctx.fillStyle = '#ffffff';
      ctx.beginPath();
      ctx.arc(nowX, this.midiToY(nowMidi), 5, 0, Math.PI * 2);
      ctx.fill();
      ctx.restore();

      const hz = 440 * Math.pow(2, (nowMidi - 69) / 12);
      const swara = this.sargam(pcOf(Math.round(nowMidi)));
      ctx.fillStyle = 'rgba(255, 255, 255, 0.85)';
      ctx.font = 'bold 11px "JetBrains Mono", monospace';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'top';
      ctx.fillText(`${this.noteLabel(Math.round(nowMidi))}${swara ? '  ' + swara : ''}  ${Math.round(hz)} Hz`, nowX + 10, top + 6);
    }
  }

  // Piano roll: a bar for every note, brighter the stronger the note was found to be.
  drawRollBars(t, hp, colors, barH) {
    const ctx = this.ctx;
    const { timeToX, shift, viewStart, viewEnd } = hp;
    for (const note of this.roll) {
      if (note.end < viewStart) continue;
      if (note.start > viewEnd) break;                 // sorted by start time
      const midi = note.midi + shift;
      if (midi < this.minMidi || midi > this.maxMidi) continue;
      const x1 = timeToX(note.start);
      const barW = Math.max(3, timeToX(note.end) - x1);
      const y = this.midiToY(midi) - barH / 2;
      const active = note.start <= t && note.end >= t;
      const past = note.end < t;
      ctx.save();
      if (active) {
        ctx.shadowColor = colors[2];
        ctx.shadowBlur = 10;
        ctx.fillStyle = colors[2];
      } else if (past) {
        ctx.fillStyle = colors[3];
      } else {
        const grad = ctx.createLinearGradient(x1, 0, x1 + barW, 0);
        grad.addColorStop(0, colors[0]);
        grad.addColorStop(1, colors[1]);
        ctx.fillStyle = grad;
        ctx.globalAlpha = 0.55 + 0.45 * Math.min(1, note.strength);
      }
      this.roundedBar(x1, y, barW, barH);
      ctx.fill();
      ctx.restore();
    }
  }

  // The notes sounding now, as a short line of names next to the now line.
  drawRollNow(t, hp, colors) {
    const ctx = this.ctx;
    const { nowX, top, shift } = hp;
    this.drawNowLine(hp);
    const sounding = [];
    for (const note of this.roll) {
      if (note.start > t) break;
      if (note.end > t) sounding.push(note.midi);
    }
    if (!sounding.length) return;
    sounding.sort((a, b) => a - b);
    for (const midi of sounding) {
      const m = midi + shift;
      if (m < this.minMidi || m > this.maxMidi) continue;
      ctx.fillStyle = '#ffffff';
      ctx.beginPath();
      ctx.arc(nowX, this.midiToY(m), 3, 0, Math.PI * 2);
      ctx.fill();
    }
    const chord = this.nameChord(sounding);
    const names = Array.from(new Set(sounding.map((m) => this.noteSpelling(m + shift)))).join(' ');
    ctx.fillStyle = 'rgba(255, 255, 255, 0.9)';
    ctx.font = 'bold 11px "JetBrains Mono", monospace';
    ctx.textAlign = 'left';
    ctx.textBaseline = 'top';
    ctx.fillText(`${chord ? this.chordName(chord) + '   ' : ''}${names}`, nowX + 10, top + 6);
  }
  // Drum mode: one row per drum, a mark for every hit, lit as it reaches the now line.
  drawDrums(t) {
    const ctx = this.ctx;
    const { plotW, nowX, pxPerSec } = this.layout();
    const { width: w, height: h, gutter } = this;
    const lanes = this.lanes;
    const rowH = h / lanes.length;
    const timeToX = (time) => nowX + (time - t) * pxPerSec;
    const viewStart = t - this.nowFraction * this.windowSeconds - 0.5;
    const viewEnd = t + (1 - this.nowFraction) * this.windowSeconds + 0.5;

    lanes.forEach((lane, index) => {
      if (index % 2 === 0) {
        ctx.fillStyle = 'rgba(255, 255, 255, 0.025)';
        ctx.fillRect(gutter, index * rowH, plotW, rowH);
      }
    });

    ctx.save();
    ctx.beginPath();
    ctx.rect(gutter, 0, plotW, h);
    ctx.clip();
    const firstSecond = Math.floor(t - this.nowFraction * this.windowSeconds);
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
    ctx.lineWidth = 1;
    for (let s = firstSecond; s <= t + this.windowSeconds; s++) {
      ctx.beginPath();
      ctx.moveTo(timeToX(s), 0);
      ctx.lineTo(timeToX(s), h);
      ctx.stroke();
    }
    lanes.forEach((lane, index) => {
      const colour = DRUM_COLORS[lane.id] || '#a78bfa';
      const markH = Math.max(6, Math.min(rowH * 0.62, 26));
      const y = index * rowH + (rowH - markH) / 2;
      for (const [time, strength] of lane.hits) {
        if (time < viewStart) continue;
        if (time > viewEnd) break;
        const x = timeToX(time);
        const lit = Math.abs(time - t) < 0.07;
        ctx.save();
        if (lit) {
          ctx.shadowColor = colour;
          ctx.shadowBlur = 18;
        }
        ctx.globalAlpha = time < t - 0.07 ? 0.3 : lit ? 1 : 0.5 + 0.5 * strength;
        ctx.fillStyle = colour;
        this.roundedBar(x - 3, y + markH * (1 - (0.55 + 0.45 * strength)) / 2, 7, markH * (0.55 + 0.45 * strength));
        ctx.fill();
        ctx.restore();
      }
    });
    this.drawNowLine({ nowX, top: 0, h });
    ctx.restore();

    // Left edge: the name of each drum.
    ctx.fillStyle = 'rgba(13, 16, 23, 0.97)';
    ctx.fillRect(0, 0, gutter, h);
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.12)';
    ctx.beginPath();
    ctx.moveTo(gutter, 0);
    ctx.lineTo(gutter, h);
    ctx.stroke();
    ctx.textAlign = 'left';
    ctx.textBaseline = 'middle';
    ctx.font = 'bold 12px "Inter", sans-serif';
    lanes.forEach((lane, index) => {
      ctx.fillStyle = DRUM_COLORS[lane.id] || '#a78bfa';
      ctx.fillText(lane.label, 12, index * rowH + rowH / 2);
    });
    if (this.approximateDrums) {
      ctx.fillStyle = '#fbbf24';
      ctx.font = 'bold 8px "Inter", sans-serif';
      ctx.fillText('APPROXIMATE: split the drums', 8, h - 8, gutter - 12);
    }
  }

  draw(t) {
    const ctx = this.ctx;
    const w = this.width;
    const h = this.height;
    if (!w || !h) return;

    ctx.clearRect(0, 0, w, h);
    ctx.fillStyle = '#090b10';
    ctx.fillRect(0, 0, w, h);

    if (this.state !== 'ready') {
      const messages = {
        idle: 'Highway: open a song to see the singing pitch here.',
        analyzing: `Reading the ${this.active ? this.active.label.toLowerCase() : 'pitch'}...`,
        nopitch: this.kind === 'notes' ? 'No clear notes were found in this stem.'
          : this.kind === 'drums' ? 'No drum hits were found.'
          : this.roughNotes.length ? 'No clear singing pitch here. Tick "Rough voice" above to see a guess at the growls.'
          : 'No clear pitch was found in this stem.',
        error: this.pitchError
          ? `Could not read the pitch of this stem. ${this.pitchError}`
          : 'Could not read the pitch of this stem.'
      };
      if (this.showChords && this.chordsNow.length) {
        const { nowX, pxPerSec } = this.layout();
        this.drawChordRibbon(t, nowX, pxPerSec);
      }
      this.drawMessage(messages[this.state] || '');
      return;
    }

    if (this.kind === 'drums') {
      this.drawDrums(t);
      return;
    }

    const { plotW, nowX, pxPerSec } = this.layout();
    const rows = this.maxMidi - this.minMidi + 1;
    const top = this.laneTop;
    const rowH = (h - top) / rows;
    const gutter = this.gutter;
    const timeToX = (time) => nowX + (time - t) * pxPerSec;
    const pcOf = (m) => ((m % 12) + 12) % 12;

    // Pitch rows. With a key: the notes of the scale are lit and the others are dark, and every
    // Sa (home note) gets a line. Without one: the usual piano-key look.
    for (let m = this.minMidi; m <= this.maxMidi; m++) {
      const yTop = this.midiToY(m) - rowH / 2;
      const pc = pcOf(m);
      if (this.key) {
        if (this.inScale(pc)) {
          ctx.fillStyle = 'rgba(139, 92, 246, 0.07)';
          ctx.fillRect(gutter, yTop, plotW, rowH);
        }
        if (pc === this.tonic) {
          ctx.strokeStyle = 'rgba(251, 191, 36, 0.35)';
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(gutter, this.midiToY(m));
          ctx.lineTo(w, this.midiToY(m));
          ctx.stroke();
        }
      } else {
        if ([1, 3, 6, 8, 10].includes(pc)) {
          ctx.fillStyle = 'rgba(255, 255, 255, 0.025)';
          ctx.fillRect(gutter, yTop, plotW, rowH);
        }
        if (pc === 0) {
          ctx.strokeStyle = 'rgba(255, 255, 255, 0.14)';
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(gutter, this.midiToY(m));
          ctx.lineTo(w, this.midiToY(m));
          ctx.stroke();
        }
      }
    }

    // Everything below scrolls and is clipped to the lane.
    ctx.save();
    ctx.beginPath();
    ctx.rect(gutter, top, plotW, h - top);
    ctx.clip();

    // One faint line per second.
    const firstSecond = Math.floor(t - this.nowFraction * this.windowSeconds);
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
    ctx.lineWidth = 1;
    for (let s = firstSecond; s <= t + this.windowSeconds; s++) {
      const x = timeToX(s);
      ctx.beginPath();
      ctx.moveTo(x, top);
      ctx.lineTo(x, h);
      ctx.stroke();
    }

    // Note bars (or, in piano-roll mode, one bar per note that sounds).
    const colors = HIGHWAY_COLORS[this.active ? this.active.file : 'vocals'] || HIGHWAY_COLORS.vocals;
    const shift = this.shift;
    const barH = Math.max(this.kind === 'notes' ? 3 : 6, Math.min(rowH * 0.85, 18));
    const viewStart = t - this.nowFraction * this.windowSeconds - 1;
    const viewEnd = t + (1 - this.nowFraction) * this.windowSeconds + 1;
    const helpers = {
      t, nowX, top, h, gutter, plotW, pxPerSec, timeToX, shift,
      midiToY: (m) => this.midiToY(m), minMidi: this.minMidi, maxMidi: this.maxMidi, viewStart, viewEnd
    };
    if (this.kind === 'notes') {
      this.drawRollBars(t, helpers, colors, barH);
      this.drawRollNow(t, helpers, colors);
    } else {
      this.drawMelodyBars(t, helpers, colors, barH);
    }
    if (this.coach) this.coach.drawOverlay(ctx, helpers);
    ctx.restore();
    // Left edge: the note names, and the Sa Re Ga names next to them.
    ctx.fillStyle = 'rgba(13, 16, 23, 0.97)';
    ctx.fillRect(0, top, gutter, h - top);
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.12)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(gutter, top);
    ctx.lineTo(gutter, h);
    ctx.stroke();
    ctx.textBaseline = 'middle';
    const fontPx = Math.max(8, Math.min(11, rowH - 0.5));
    for (let m = this.minMidi; m <= this.maxMidi; m++) {
      const pc = pcOf(m);
      const y = this.midiToY(m);
      if (this.key) {
        if (!this.inScale(pc)) {
          // a small tick for notes outside the scale, so the lane still reads as a keyboard
          ctx.fillStyle = 'rgba(255, 255, 255, 0.12)';
          ctx.fillRect(gutter - 6, y - 0.5, 6, 1);
          continue;
        }
        const isSa = pc === this.tonic;
        ctx.font = `${isSa ? 'bold ' : ''}${fontPx}px "Inter", sans-serif`;
        ctx.textAlign = 'left';
        ctx.fillStyle = isSa ? '#fbbf24' : 'rgba(255, 255, 255, 0.75)';
        ctx.fillText(this.noteLabel(m), 8, y);
        ctx.textAlign = 'right';
        ctx.fillStyle = isSa ? '#fbbf24' : 'rgba(196, 181, 253, 0.95)';
        ctx.fillText(this.sargam(pc), gutter - 10, y);
      } else {
        const name = this.NOTE_NAMES[pc];
        if (name.includes('#')) continue;
        if (rowH < 9 && !['C', 'E', 'G'].includes(name)) continue;
        ctx.font = `${name === 'C' ? 'bold ' : ''}${fontPx}px "Inter", sans-serif`;
        ctx.textAlign = 'center';
        ctx.fillStyle = name === 'C' ? '#ffffff' : 'rgba(255, 255, 255, 0.45)';
        ctx.fillText(this.noteLabel(m), gutter / 2, y);
      }
    }

    if (top) this.drawChordRibbon(t, nowX, pxPerSec);
  }
}
