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

class VocalHighway {
  constructor({ canvas, engine }) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.engine = engine;

    this.windowSeconds = 10;   // how much time is visible at once
    this.nowFraction = 0.25;   // where the "now" line sits across the lane
    this.gutter = 46;          // room for the note names on the left

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
    if (!buffer) {
      this.analysisId++;
      this.state = 'idle';
      return;
    }
    this.analyze(buffer);
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

  finishAnalysis({ midi, t0, dt }) {
    const smooth = this.medianSmooth(midi);
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
    this.minMidi = Math.max(24, lo);
    this.maxMidi = Math.min(100, hi);
    this.state = 'ready';
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
    const minRun = 7;   // about 0.16 s: shorter blips are breaths and bleed, not singing
    let i = 0;
    while (i < n) {
      if (!midi[i]) { i++; continue; }
      // A sung phrase: voiced frames, bridging gaps of up to 2 frames.
      let j = i;
      let last = i;
      while (j < n) {
        if (midi[j]) { last = j; j++; }
        else if (j - last <= 2) j++;
        else break;
      }
      if (last - i + 1 >= minRun) this.splitPhrase(midi, i, last, notes, t0, dt);
      i = last + 1;
    }
    return notes;
  }

  splitPhrase(midi, from, to, notes, t0, dt) {
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
      if (frames[f].note === prev.note && frames[f].k - prev.k <= 3) group.push(frames[f]);
      else { groups.push(group); group = [frames[f]]; }
    }
    groups.push(group);
    for (const g of groups) {
      if (g.length < 3 && groups.length > 1) continue;   // too short to be a note
      notes.push({
        start: t0 + g[0].k * dt,
        end: t0 + (g[g.length - 1].k + 1) * dt,
        midi: g[0].note
      });
    }
  }

  // --- drawing --------------------------------------------------------------------

  midiToY(midi) {
    const rows = this.maxMidi - this.minMidi + 1;
    return this.height - ((midi - this.minMidi + 0.5) / rows) * this.height;
  }

  noteLabel(midi) {
    return `${this.NOTE_NAMES[((midi % 12) + 12) % 12]}${Math.floor(midi / 12) - 1}`;
  }

  drawMessage(text) {
    const ctx = this.ctx;
    ctx.fillStyle = 'rgba(255, 255, 255, 0.45)';
    ctx.font = '13px "Inter", sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(text, this.width / 2, this.height / 2);
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
    const rowH = h / rows;
    const gutter = this.gutter;
    const timeToX = (time) => nowX + (time - t) * pxPerSec;

    // Pitch rows: dark bands for the black keys, a brighter line on every C.
    for (let m = this.minMidi; m <= this.maxMidi; m++) {
      const yTop = this.midiToY(m) - rowH / 2;
      if ([1, 3, 6, 8, 10].includes(((m % 12) + 12) % 12)) {
        ctx.fillStyle = 'rgba(255, 255, 255, 0.025)';
        ctx.fillRect(gutter, yTop, plotW, rowH);
      }
      if (m % 12 === 0) {
        ctx.strokeStyle = 'rgba(255, 255, 255, 0.14)';
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(gutter, this.midiToY(m));
        ctx.lineTo(w, this.midiToY(m));
        ctx.stroke();
      }
    }

    // Everything below scrolls and is clipped to the lane.
    ctx.save();
    ctx.beginPath();
    ctx.rect(gutter, 0, plotW, h);
    ctx.clip();

    // One faint line per second.
    const firstSecond = Math.floor(t - this.nowFraction * this.windowSeconds);
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.05)';
    ctx.lineWidth = 1;
    for (let s = firstSecond; s <= t + this.windowSeconds; s++) {
      const x = timeToX(s);
      ctx.beginPath();
      ctx.moveTo(x, 0);
      ctx.lineTo(x, h);
      ctx.stroke();
    }

    // Note bars.
    const barH = Math.max(7, Math.min(rowH * 0.85, 18));
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
    ctx.moveTo(nowX, 0);
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
      ctx.fillStyle = 'rgba(255, 255, 255, 0.85)';
      ctx.font = 'bold 11px "JetBrains Mono", monospace';
      ctx.textAlign = 'left';
      ctx.textBaseline = 'top';
      ctx.fillText(`${this.noteLabel(Math.round(nowMidi))}  ${Math.round(hz)} Hz`, nowX + 10, 6);
    }
    ctx.restore();

    // Note names down the left edge.
    ctx.fillStyle = 'rgba(13, 16, 23, 0.96)';
    ctx.fillRect(0, 0, gutter, h);
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.12)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(gutter, 0);
    ctx.lineTo(gutter, h);
    ctx.stroke();
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    for (let m = this.minMidi; m <= this.maxMidi; m++) {
      const name = this.NOTE_NAMES[((m % 12) + 12) % 12];
      const isC = name === 'C';
      if (name.includes('#')) continue;
      // In a tight lane, name only C, E and G so the labels do not overlap.
      if (rowH < 9 && !['C', 'E', 'G'].includes(name)) continue;
      ctx.fillStyle = isC ? '#ffffff' : 'rgba(255, 255, 255, 0.45)';
      ctx.font = isC ? 'bold 10px "Inter", sans-serif' : '9px "Inter", sans-serif';
      ctx.fillText(this.noteLabel(m), gutter / 2, this.midiToY(m));
    }
  }
}
