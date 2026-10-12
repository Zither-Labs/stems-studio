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
    this.showChords = true;
    this.analysisUrl = null;   // set by the app: where the engine keeps this song's key and chords
    this.keyRequestId = 0;
    this.tuningCents = 0;
    this.barEls = null;
    this.barRoot = bar || null;

    this.NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];

    this.state = 'idle';       // idle | analyzing | ready | nopitch | error
    this.buffer = null;
    this.midi = null;
    this.t0 = 0;
    this.dt = 0.0213;
    this.notes = [];
    this.minMidi = 48;
    this.maxMidi = 72;
    this.analysisId = 0;
    this.worker = null;
    this.pitchUrl = null;      // set by the app: where the server keeps this song's pitch track
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
    const t = this.engine.getCurrentTime();
    const key = `${t.toFixed(3)}|${this.width}|${this.height}|${this.state}|${this.notes.length}`;
    if (key !== this.lastKey) {
      this.lastKey = key;
      this.draw(t);
    }
    requestAnimationFrame(this.loop);
  }

  checkBuffer() {
    const track = this.engine.tracks.get('vocal');
    const buffer = track && track.buffer ? track.buffer : null;
    if (buffer === this.buffer) return;
    this.buffer = buffer;
    this.notes = [];
    this.midi = null;
    const url = this.pitchUrl;
    this.pitchUrl = null;   // used once: a later song must not reuse it
    if (!buffer) {
      this.analysisId++;
      this.state = 'idle';
      return;
    }
    if (url) this.fetchServerPitch(buffer, url);
    else this.analyze(buffer);
  }

  // --- key, scale and chords ------------------------------------------------------------

  setupBar(bar) {
    const els = {
      text: bar.querySelector('#highwayKeyText'),
      tonic: bar.querySelector('#highwayTonic'),
      mode: bar.querySelector('#highwayMode'),
      reset: bar.querySelector('#highwayKeyReset'),
      chords: bar.querySelector('#highwayShowChords')
    };
    this.barEls = els;
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
    els.chords.addEventListener('change', () => {
      this.showChords = els.chords.checked;
      this.lastKey = '';
    });
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

  // Forget the key and chords (a new song is loading, or the song has none).
  resetKey() {
    this.keyRequestId++;
    this.detected = null;
    this.key = null;
    this.chords = [];
    this.applyKeyRange();
    this.refreshBar();
    this.lastKey = '';
  }

  async fetchAnalysis(url) {
    this.resetKey();
    const id = this.keyRequestId;
    if (this.barEls) this.barEls.text.textContent = 'Key: finding it from the bass, instruments and vocal...';
    try {
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`analysis request failed (${resp.status})`);
      const data = await resp.json();
      if (id !== this.keyRequestId) return;
      this.detected = data.key || null;
      this.chords = Array.isArray(data.chords) ? data.chords : [];
      this.tuningCents = data.tuning_cents || 0;
      if (this.detected) this.setKey(this.detected, false);
      else this.refreshBar();
    } catch (err) {
      console.warn('Key and chords unavailable:', err);
      if (id === this.keyRequestId) {
        this.chords = [];
        this.refreshBar('Key: not available (install the extras to turn this on).');
      }
    }
    this.lastKey = '';
  }

  noteSpelling(pc) {
    const flats = this.key ? this.key.flats : false;
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
    Array.from(els.tonic.options).forEach((option) => { option.textContent = this.noteSpelling(Number(option.value)); });
    els.tonic.value = String(this.key.tonic);
    els.mode.value = this.key.mode;
    const name = `${this.noteSpelling(this.key.tonic)} ${this.key.mode}`;
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
    text += `  \u00B7  Sa = ${this.noteSpelling(this.key.tonic)}`;
    els.text.textContent = text;
    els.reset.hidden = !(this.key.manual && this.detected);
  }

  // Which of the 12 notes belong to the scale in use.
  inScale(pc) {
    if (!this.key) return false;
    const degrees = this.key.mode === 'major' ? MAJOR_DEGREES : MINOR_DEGREES;
    return degrees.includes((((pc - this.key.tonic) % 12) + 12) % 12);
  }

  sargam(pc) {
    if (!this.key) return null;
    return SARGAM_12[(((pc - this.key.tonic) % 12) + 12) % 12];
  }

  chordName(chord) {
    return `${this.noteSpelling(chord.root)}${chord.quality}`;
  }

  // The engine (server.py) finds the pitch with a neural detector and cleans it up. If it is
  // not available, the browser falls back to its own, simpler analysis.
  async fetchServerPitch(buffer, url) {
    this.state = 'analyzing';
    const id = ++this.analysisId;
    try {
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(`pitch request failed (${resp.status})`);
      const data = await resp.json();
      if (id !== this.analysisId) return;
      this.finishAnalysis({ midi: Float32Array.from(data.midi), t0: data.t0, dt: data.dt }, true);
    } catch (err) {
      console.warn('Server pitch unavailable, analysing in the browser instead:', err);
      if (id === this.analysisId && buffer === this.buffer) this.analyze(buffer);
    }
  }

  // --- pitch analysis -------------------------------------------------------------

  analyze(buffer) {
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
        this.finishAnalysis(e.data);
      };
      this.worker.onerror = (err) => {
        console.error('Vocal highway worker failed', err);
        if (id === this.analysisId) this.state = 'error';
      };
      this.worker.postMessage({ id, samples, fs }, [samples.buffer]);
    } catch (err) {
      console.error('Vocal highway could not start', err);
      this.state = 'error';
    }
  }

  finishAnalysis({ midi, t0, dt }, alreadyCleaned = false) {
    // The server's track has had octave errors, breaths and stray blips removed already.
    const smooth = alreadyCleaned ? midi : this.medianSmooth(midi);
    this.midi = smooth;
    this.t0 = t0;
    this.dt = dt;
    this.notes = this.buildNotes(smooth, t0, dt);

    const voiced = [];
    for (let i = 0; i < smooth.length; i++) if (smooth[i]) voiced.push(smooth[i]);
    if (voiced.length < 10 || !this.notes.length) {
      this.state = 'nopitch';
      return;
    }
    voiced.sort((a, b) => a - b);
    const pick = (q) => voiced[Math.min(voiced.length - 1, Math.floor(voiced.length * q))];
    let lo = Math.floor(pick(0.03)) - 2;
    let hi = Math.ceil(pick(0.97)) + 2;
    while (hi - lo < 16) { lo--; hi++; }   // never zoom in tighter than about an octave and a half
    this.baseMin = Math.max(24, lo);
    this.baseMax = Math.min(100, hi);
    this.applyKeyRange();
    this.state = 'ready';
  }

  // With a key, the lane is stretched to start and end on a Sa, so a whole Sa-to-Sa scale
  // (for example C D E F G A B C) is always on screen.
  applyKeyRange() {
    if (this.baseMin === undefined) return;
    let lo = this.baseMin;
    let hi = this.baseMax;
    if (this.key) {
      while ((((lo % 12) + 12) % 12) !== this.key.tonic) lo--;
      while ((((hi % 12) + 12) % 12) !== this.key.tonic) hi++;
    }
    this.minMidi = Math.max(24, lo);
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
    return this.showChords && this.chords.length ? this.chordBarHeight : 0;
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
    for (const chord of this.chords) {
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
    ctx.fillText('Chords', gutter / 2, h / 2 - 5);
    ctx.fillStyle = '#fbbf24';
    ctx.font = 'bold 8px "Inter", sans-serif';
    ctx.fillText('VERY EXPERIMENTAL', gutter / 2, h / 2 + 7, gutter - 6);
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
        idle: 'Vocal highway: open a song with vocals to see the singing pitch here.',
        analyzing: 'Reading the vocal pitch...',
        nopitch: 'No clear singing pitch was found in this vocal.',
        error: 'Could not read the vocal pitch.'
      };
      this.drawMessage(messages[this.state] || '');
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
        if (pc === this.key.tonic) {
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

    // Note bars.
    const barH = Math.max(6, Math.min(rowH * 0.85, 18));
    const viewStart = t - this.nowFraction * this.windowSeconds - 1;
    const viewEnd = t + (1 - this.nowFraction) * this.windowSeconds + 1;
    for (const note of this.notes) {
      if (note.end < viewStart || note.start > viewEnd) continue;
      if (note.midi < this.minMidi || note.midi > this.maxMidi) continue;
      const x1 = timeToX(note.start);
      const x2 = timeToX(note.end);
      const barW = Math.max(4, x2 - x1);
      const y = this.midiToY(note.midi) - barH / 2;
      const active = note.start <= t && note.end >= t;
      const past = note.end < t;

      ctx.save();
      if (active) {
        ctx.shadowColor = 'rgba(244, 114, 182, 0.9)';
        ctx.shadowBlur = 16;
        ctx.fillStyle = '#f9a8d4';
      } else if (past) {
        ctx.fillStyle = 'rgba(139, 92, 246, 0.32)';
      } else {
        const grad = ctx.createLinearGradient(x1, 0, x1 + barW, 0);
        grad.addColorStop(0, '#8b5cf6');
        grad.addColorStop(1, '#ec4899');
        ctx.fillStyle = grad;
      }
      this.roundedBar(x1, y, barW, barH);
      ctx.fill();
      ctx.restore();
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
      const m = this.midi[k];
      // Skip silence and stray detections outside the lane (they would draw wild spikes).
      if (!m || m < this.minMidi - 0.5 || m > this.maxMidi + 0.5) { drawing = false; continue; }
      const x = timeToX(this.t0 + k * this.dt);
      const y = this.midiToY(m);
      if (drawing) ctx.lineTo(x, y);
      else { ctx.moveTo(x, y); drawing = true; }
    }
    ctx.stroke();

    // The "now" line and a dot on the pitch being sung right now.
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

    const here = Math.round((t - this.t0) / this.dt);
    const nowMidi = here >= 0 && here < this.midi.length ? this.midi[here] : 0;
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
        const isSa = pc === this.key.tonic;
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
