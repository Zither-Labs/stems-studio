/**
 * Stems Studio - Singing Coach
 *
 * Listens to the microphone, draws the singer's own line on the highway next to the notes of the
 * song, and scores it: each note is marked hit (green), off (amber) or missed (red), each phrase
 * gets a score, and a phrase can be looped to try again.
 *
 * How the timing works. The microphone hears the voice some time after it was sung (input
 * latency, plus the window the pitch is measured over), and the singer was singing along to what
 * they heard, which left the speakers some time after the engine played it (output latency).
 * Each pitch reading is therefore placed on the song's timeline at
 *     engine time - (input latency + analysis lag + output latency + your nudge) x playback speed
 * The nudge is the "Mic timing" control, for setups (Bluetooth) where those guesses are far off.
 */

const COACH_LEVELS = {
  beginner: { cents: 50, grace: 0.2 },    // grace: seconds at the start of a note that are not scored
  medium: { cents: 30, grace: 0.12 },
  advanced: { cents: 15, grace: 0.08 }
};

const COACH_SETTINGS_KEY = 'stemsStudio.coach';
const COACH_HISTORY_KEY = 'stemsStudio.coach.history.';
const COACH_PHRASE_GAP = 0.5;        // a silence this long between notes starts a new phrase
const COACH_MAX_PHRASE = 9;          // seconds: a longer run is cut at its longest gap
const COACH_MAX_TRACE = 5000;        // pitch readings kept (about a minute and a half)

class SingingCoach {
  constructor({ highway, engine, root }) {
    this.highway = highway;
    this.engine = engine;
    this.root = root;
    highway.coach = this;

    this.settings = Object.assign(
      { level: 'beginner', anyOctave: true, headphones: 'headphones', guide: false, echo: false, delayMs: 0 },
      this.loadSettings()
    );

    // The microphone and what it heard.
    this.listening = false;
    this.stream = null;
    this.analyser = null;
    this.micBuffer = null;
    this.minHz = 70;
    this.noiseFloor = 0.004;
    this.times = [];            // song time of each reading
    this.midis = [];            // pitch of each reading (0 = no voice), as sung
    this.recent = [];           // the last three readings, for the median
    this.live = null;           // { midi, target, err } for the readout
    this.lastTickTime = null;

    // Scoring. stats: note -> { frames, hit, voiced, silent, sumErr }
    this.stats = new Map();
    this.phraseSource = null;
    this.phrases = [];
    this.lastSummary = 0;
    this.sessionScored = false;

    // Practice tools.
    this.phase = 'normal';      // normal | listen | sing (the "listen, then sing" turns)
    this.mutedBefore = null;
    this.guide = null;          // { osc, gain }

    this.bindUi();
    this.tick = this.tick.bind(this);
    requestAnimationFrame(this.tick);
  }

  loadSettings() {
    try { return JSON.parse(localStorage.getItem(COACH_SETTINGS_KEY)) || {}; } catch (err) { return {}; }
  }

  saveSettings() {
    try { localStorage.setItem(COACH_SETTINGS_KEY, JSON.stringify(this.settings)); } catch (err) { /* private mode */ }
  }

  get level() { return COACH_LEVELS[this.settings.level] || COACH_LEVELS.beginner; }

  // --- the controls --------------------------------------------------------------------

  bindUi() {
    const q = (id) => this.root.querySelector(`#${id}`) || document.getElementById(id);
    this.ui = {
      toggle: q('coachToggle'), level: q('coachLevel'), octave: q('coachOctave'),
      headphones: q('coachHeadphones'), guide: q('coachGuide'), echo: q('coachEcho'),
      minus: q('coachDelayMinus'), plus: q('coachDelayPlus'), delay: q('coachDelayText'),
      status: q('coachStatus'), results: q('coachResults'), summary: q('coachSummary'),
      phrases: q('coachPhrases'), retry: q('coachRetry'), reset: q('coachReset')
    };
    const ui = this.ui;
    ui.level.value = this.settings.level;
    ui.octave.checked = this.settings.anyOctave;
    ui.headphones.value = this.settings.headphones;
    ui.guide.checked = this.settings.guide;
    ui.echo.checked = false;                  // always starts off: it takes over the loop and the mute button
    this.settings.echo = false;
    this.showDelay();

    ui.toggle.addEventListener('click', () => (this.listening ? this.stop() : this.start()));
    ui.level.addEventListener('change', () => {
      this.settings.level = ui.level.value;
      // Each level has its own habit about octaves; the box can still be changed afterwards.
      this.settings.anyOctave = this.settings.level === 'beginner';
      ui.octave.checked = this.settings.anyOctave;
      this.saveSettings();
      this.restartScoring();
    });
    ui.octave.addEventListener('change', () => {
      this.settings.anyOctave = ui.octave.checked;
      this.saveSettings();
      this.restartScoring();
    });
    ui.headphones.addEventListener('change', async () => {
      this.settings.headphones = ui.headphones.value;
      this.saveSettings();
      if (this.listening) { this.stop(true); await this.start(); }   // echo cancelling is chosen when the mic opens
    });
    ui.guide.addEventListener('change', () => { this.settings.guide = ui.guide.checked; this.saveSettings(); });
    ui.echo.addEventListener('change', () => this.setEcho(ui.echo.checked));
    ui.minus.addEventListener('click', () => this.nudge(-20));
    ui.plus.addEventListener('click', () => this.nudge(20));
    ui.retry.addEventListener('click', () => this.retryWeakest());
    ui.reset.addEventListener('click', () => this.finishSession(true));
    this.refreshAvailability();
  }

  nudge(ms) {
    this.settings.delayMs = Math.max(-400, Math.min(600, this.settings.delayMs + ms));
    this.saveSettings();
    this.showDelay();
  }

  showDelay() {
    const ms = this.settings.delayMs;
    this.ui.delay.textContent = `${ms > 0 ? '+' : ''}${ms} ms`;
  }

  setStatus(text, warning = false) {
    this.ui.status.textContent = text;
    this.ui.status.classList.toggle('warn', warning);
  }

  // The coach follows a single melody line, so it is off for the piano-roll views.
  refreshAvailability() {
    const h = this.highway;
    const usable = h.kind === 'melody';
    this.ui.toggle.disabled = !usable;
    this.ui.toggle.title = usable
      ? 'Use your microphone to see your own voice on the highway'
      : 'Pick a stem that plays one note at a time (such as Vocals) to sing along with it';
  }

  sourceChanged() {
    this.refreshAvailability();
    if (this.highway.kind !== 'melody' && this.listening) this.stop();
    this.stats.clear();
    this.times.length = 0;
    this.midis.length = 0;
    this.sessionScored = false;
  }

  // --- the microphone -------------------------------------------------------------------

  async start() {
    if (this.listening) return;
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      this.setStatus('This browser cannot reach the microphone here.', true);
      return;
    }
    try {
      await this.engine.resume();
      const speakers = this.settings.headphones === 'speakers';
      this.stream = await navigator.mediaDevices.getUserMedia({
        audio: { echoCancellation: speakers, noiseSuppression: false, autoGainControl: false, channelCount: 1 }
      });
    } catch (err) {
      const denied = err && (err.name === 'NotAllowedError' || err.name === 'SecurityError');
      this.setStatus(denied ? 'The microphone is blocked. Allow it in the browser address bar and try again.'
        : `Could not open the microphone (${err && err.name ? err.name : 'error'}).`, true);
      return;
    }
    const ctx = this.engine.ctx;
    this.source = ctx.createMediaStreamSource(this.stream);
    this.analyser = ctx.createAnalyser();
    this.analyser.fftSize = 2048;
    this.analyser.smoothingTimeConstant = 0;
    this.source.connect(this.analyser);       // not to the speakers: that would be an echo
    this.micBuffer = new Float32Array(this.analyser.fftSize);
    const track = this.stream.getAudioTracks()[0];
    const settings = track && track.getSettings ? track.getSettings() : {};
    this.inputLatency = typeof settings.latency === 'number' && settings.latency > 0 ? settings.latency : 0.015;
    this.listening = true;
    this.ui.toggle.textContent = 'Stop singing';
    this.ui.toggle.classList.add('on');
    this.ui.results.hidden = false;
    this.setStatus(this.settings.headphones === 'headphones' ? 'Listening. Sing along.' : 'Listening (speakers: echo cancelling is on).');
    this.highway.lastKey = '';
  }

  stop(keepSession = false) {
    if (!this.listening) return;
    this.listening = false;
    if (this.stream) this.stream.getTracks().forEach((t) => t.stop());
    if (this.source) this.source.disconnect();
    this.stream = null;
    this.source = null;
    this.analyser = null;
    this.live = null;
    this.ui.toggle.textContent = 'Sing along';
    this.ui.toggle.classList.remove('on');
    this.setStatus('');
    if (!keepSession) this.finishSession(false);
    this.highway.lastKey = '';
  }

  // YIN pitch detection on the newest samples. Returns { midi, hz } or null when there is no clear pitch.
  detect() {
    const ctx = this.engine.ctx;
    this.analyser.getFloatTimeDomainData(this.micBuffer);
    const factor = Math.max(1, Math.floor(ctx.sampleRate / 24000));      // work at about 24 kHz: 4x cheaper
    const fs = ctx.sampleRate / factor;
    const length = Math.floor(this.micBuffer.length / factor);
    const x = this.decimated && this.decimated.length === length ? this.decimated : (this.decimated = new Float32Array(length));
    for (let i = 0; i < length; i++) {
      let sum = 0;
      for (let k = 0; k < factor; k++) sum += this.micBuffer[i * factor + k];
      x[i] = sum / factor;
    }
    const W = 512;
    const maxTau = Math.floor(fs / this.minHz);
    const minTau = Math.max(2, Math.floor(fs / 1100));
    const base = length - (W + maxTau + 1);
    if (base < 0) return null;

    let energy = 0;
    for (let j = 0; j < W; j++) { const v = x[length - W + j]; energy += v * v; }
    const rms = Math.sqrt(energy / W);
    // A slowly-following estimate of the room's noise, so the gate adapts to the microphone.
    // It creeps up so it can follow a noisier room, but never far enough to gate out a quiet singer.
    this.noiseFloor = rms < this.noiseFloor ? rms : Math.min(0.008, this.noiseFloor * 1.0008 + 1e-7);
    this.frameLag = (length - (base + W / 2)) / fs;
    if (rms < Math.max(0.006, this.noiseFloor * 3)) return null;

    const d = this.yinBuffer && this.yinBuffer.length === maxTau + 1 ? this.yinBuffer : (this.yinBuffer = new Float32Array(maxTau + 1));
    d[0] = 1;
    let running = 0;
    for (let tau = 1; tau <= maxTau; tau++) {
      let sum = 0;
      for (let j = 0; j < W; j++) {
        const delta = x[base + j] - x[base + j + tau];
        sum += delta * delta;
      }
      running += sum;
      d[tau] = running > 0 ? (sum * tau) / running : 1;
    }
    let found = -1;
    for (let tau = minTau; tau < maxTau; tau++) {
      if (d[tau] < 0.15) {
        while (tau + 1 < maxTau && d[tau + 1] < d[tau]) tau++;
        found = tau;
        break;
      }
    }
    if (found < 0) return null;
    let better = found;
    if (found > 1 && found < maxTau) {
      const s0 = d[found - 1], s1 = d[found], s2 = d[found + 1];
      const den = 2 * (2 * s1 - s2 - s0);
      if (den !== 0) better = found + (s2 - s0) / den;
    }
    const hz = fs / better;
    if (hz < this.minHz || hz > 1100) return null;
    return { hz, midi: 69 + 12 * Math.log2(hz / 440) };
  }

  // Seconds the song has moved while the voice travelled from the singer to this reading.
  songLag() {
    const ctx = this.engine.ctx;
    const output = ctx.outputLatency || ctx.baseLatency || 0.02;
    const real = (this.inputLatency || 0.015) + (this.frameLag || 0.025) + output + this.settings.delayMs / 1000;
    const speed = this.engine.playbackRate * Math.pow(2, this.engine.pitchSemitones / 12);
    return real * speed;
  }

  // --- every frame ----------------------------------------------------------------------

  tick() {
    requestAnimationFrame(this.tick);
    const engine = this.engine;
    if (!engine.ctx) return;
    const now = engine.getCurrentTime();

    // The song jumped back: a loop came round, or the singer moved the playhead. Those notes are tried again.
    if (this.lastTickTime !== null && now < this.lastTickTime - 0.3) this.onRewind(now);
    this.lastTickTime = now;

    this.followGuide(now);

    if (this.listening && this.analyser) {
      const hit = this.detect();
      let midi = 0;
      if (hit) {
        this.recent.push(hit.midi);
        if (this.recent.length > 3) this.recent.shift();
        midi = [...this.recent].sort((a, b) => a - b)[this.recent.length >> 1];     // median of three: drops one-frame octave slips
      } else {
        this.recent.length = 0;
      }
      this.ingest(now - this.songLag(), midi, now);
    }

    const stamp = performance.now();
    if (stamp - this.lastSummary > 250) {
      this.lastSummary = stamp;
      if (this.listening || this.stats.size) this.renderResults(now);
    }
  }

  // One pitch reading, placed on the song's timeline.
  ingest(songTime, midi, now) {
    const h = this.highway;
    const target = this.targetAt(songTime, now);
    const note = target ? target.note : null;
    this.live = { midi, target: target ? target.midi : 0, err: target && midi ? this.error(midi, target.midi) : null };
    if (!this.engine.isPlaying) return;

    while (this.times.length && this.times[this.times.length - 1] >= songTime) { this.times.pop(); this.midis.pop(); }
    this.times.push(songTime);
    this.midis.push(midi);
    if (this.times.length > COACH_MAX_TRACE) { this.times.splice(0, 500); this.midis.splice(0, 500); }

    if (!this.scoring || !note || h.state !== 'ready') return;
    const grace = Math.min(this.level.grace, (note.end - note.start) * 0.35);
    if (songTime < note.start + grace) return;
    let st = this.stats.get(note);
    if (!st) { st = { frames: 0, hit: 0, voiced: 0, silent: 0, sumErr: 0 }; this.stats.set(note, st); }
    st.frames++;
    this.sessionScored = true;
    if (!midi) { st.silent++; return; }
    const err = this.error(midi, target.midi);
    st.voiced++;
    st.sumErr += err;
    if (Math.abs(err) <= this.level.cents) st.hit++;
  }

  get scoring() {
    return this.listening && this.engine.isPlaying && (!this.settings.echo || this.phase === 'sing');
  }

  // How far the voice is from the target in cents (+ sharp, - flat). With "any octave" the octave is ignored.
  error(midi, target) {
    let err = (midi - target) * 100;
    if (this.settings.anyOctave) err = ((((err + 600) % 1200) + 1200) % 1200) - 600;
    return err;
  }

  // The note the singer should be on at this song time, and its pitch with the pitch control and the
  // recording's own tuning applied.
  targetAt(time) {
    const h = this.highway;
    if (h.kind !== 'melody' || h.state !== 'ready') return null;
    const notes = h.notes;
    let lo = 0;
    let hi = notes.length - 1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (notes[mid].end < time) lo = mid + 1;
      else if (notes[mid].start > time) hi = mid - 1;
      else return { note: notes[mid], midi: this.noteTarget(notes[mid]) };
    }
    return null;
  }

  noteTarget(note) {
    const cents = Math.abs(this.highway.tuningCents || 0) <= 50 ? this.highway.tuningCents || 0 : 0;
    return note.midi + this.highway.shift + cents / 100;
  }

  onRewind(now) {
    for (const note of this.highway.notes) {
      if (note.end >= now - 0.1) this.stats.delete(note);
    }
    const engine = this.engine;
    if (this.settings.echo && engine.isLooping && Math.abs(now - engine.loopStart) < 0.6) {
      this.setPhase(this.phase === 'sing' ? 'listen' : 'sing');
    }
    this.recent.length = 0;
  }

  needsRedraw() {
    return this.listening || this.phase !== 'normal';
  }

  // --- results ---------------------------------------------------------------------------

  // Result of one note once it has gone by: 'hit', 'off' (sung, but not close enough) or 'miss'.
  noteResult(note, t) {
    const st = this.stats.get(note);
    if (!st || st.frames < 3 || t < note.end + 0.15) return null;
    if (st.hit / st.frames >= 0.5) return 'hit';
    if (st.voiced / st.frames >= 0.4) return 'off';
    return 'miss';
  }

  getPhrases() {
    const notes = this.highway.notes;
    if (this.phraseSource === notes) return this.phrases;
    this.phraseSource = notes;
    // First cut at every real pause...
    const groups = [];
    let group = null;
    for (const note of notes) {
      if (group && note.start - group[group.length - 1].end <= COACH_PHRASE_GAP) group.push(note);
      else { group = [note]; groups.push(group); }
    }
    // ...then cut anything still too long (a verse sung without a breath) at its longest gap, so a
    // phrase is always a short thing to loop and try again.
    const pieces = [];
    const cut = (list) => {
      const length = list[list.length - 1].end - list[0].start;
      if (length <= COACH_MAX_PHRASE || list.length < 2) { pieces.push(list); return; }
      let at = 1;
      let widest = -1;
      for (let i = 1; i < list.length; i++) {
        const gap = list[i].start - list[i - 1].end;
        // Prefer a gap near the middle when several are alike.
        const score = gap - Math.abs(i - list.length / 2) * 0.002;
        if (score > widest) { widest = score; at = i; }
      }
      cut(list.slice(0, at));
      cut(list.slice(at));
    };
    groups.forEach(cut);
    this.phrases = pieces.map((list, index) => ({ index, start: list[0].start, end: list[list.length - 1].end, notes: list }));
    return this.phrases;
  }

  // Score of each phrase that has been sung (at least one note finished), and of the whole try.
  summarise(now) {
    const rows = [];
    let allWeight = 0;
    let allHit = 0;
    for (const phrase of this.getPhrases()) {
      let weight = 0;
      let hitWeight = 0;
      let errSum = 0;
      let errCount = 0;
      const trouble = [];
      let scored = 0;
      for (const note of phrase.notes) {
        const result = this.noteResult(note, now);
        if (!result) continue;
        scored++;
        const length = note.end - note.start;
        weight += length;
        if (result === 'hit') hitWeight += length;
        else trouble.push(note);
        const st = this.stats.get(note);
        errSum += st.sumErr;
        errCount += st.voiced;
      }
      if (!scored) continue;
      allWeight += weight;
      allHit += hitWeight;
      rows.push({
        phrase, scored, notes: phrase.notes.length,
        score: Math.round((100 * hitWeight) / weight),
        avgErr: errCount ? errSum / errCount : null,
        trouble
      });
    }
    return { rows, score: allWeight ? Math.round((100 * allHit) / allWeight) : null };
  }

  describeTendency(avg) {
    if (avg === null) return 'no voice heard';
    const rounded = Math.round(avg);
    if (Math.abs(avg) < 10) return `right on the note (${rounded > 0 ? '+' : ''}${rounded} cents)`;
    const word = Math.abs(avg) < 25 ? 'a little' : 'quite';
    return `${word} ${avg > 0 ? 'sharp' : 'flat'} (${rounded > 0 ? '+' : ''}${rounded} cents)`;
  }

  troubleNames(notes) {
    const h = this.highway;
    const names = [];
    for (const note of notes) {
      const m = note.midi + h.shift;
      const sargam = h.sargam(((m % 12) + 12) % 12);
      const name = sargam ? `${sargam} (${h.noteSpelling(m)})` : h.noteSpelling(m);
      if (!names.includes(name)) names.push(name);
      if (names.length >= 4) break;
    }
    return names.join(', ');
  }

  formatTime(seconds) {
    const s = Math.max(0, Math.round(seconds));
    return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
  }

  renderResults(now) {
    const ui = this.ui;
    const { rows, score } = this.summarise(now);
    const history = this.history();
    const best = history.length ? Math.max(...history.map((e) => e.score)) : null;
    const last = history.length ? history[history.length - 1].score : null;
    let text = score === null
      ? 'Sing a phrase and your score appears here.'
      : `Score ${score}%  \u00B7  within ${this.level.cents} cents${this.settings.anyOctave ? ', any octave' : ''}`;
    if (best !== null) text += `  \u00B7  best ${best}%, last try ${last}%`;
    ui.summary.textContent = text;
    ui.retry.disabled = !rows.length;

    ui.phrases.innerHTML = '';
    rows.slice().reverse().slice(0, 12).forEach((row) => {
      const li = document.createElement('li');
      li.className = row.score >= 70 ? 'good' : row.score >= 40 ? 'fair' : 'poor';
      li.title = 'Click to loop this phrase and try it again';
      const where = `${this.formatTime(row.phrase.start)}\u2013${this.formatTime(row.phrase.end)}`;
      li.innerHTML = '';
      const bar = document.createElement('span');
      bar.className = 'coach-bar-fill';
      bar.style.width = `${row.score}%`;
      const label = document.createElement('span');
      label.className = 'coach-phrase-text';
      const trouble = row.trouble.length ? `  \u00B7  missed: ${this.troubleNames(row.trouble)}` : '';
      label.textContent = `Phrase ${row.phrase.index + 1} (${where})  ${row.score}%  \u00B7  ${this.describeTendency(row.avgErr)}${trouble}`;
      li.append(bar, label);
      li.addEventListener('click', () => this.loopPhrase(row.phrase));
      ui.phrases.appendChild(li);
    });
    this.lastRows = rows;
  }

  // Loop one phrase so it can be tried again.
  loopPhrase(phrase) {
    const engine = this.engine;
    for (const note of phrase.notes) this.stats.delete(note);
    engine.setLoop(true, Math.max(0, phrase.start - 0.4), phrase.end + 0.3);
    engine.seek(engine.loopStart);
    if (!engine.isPlaying) engine.play();
  }

  retryWeakest() {
    const rows = this.lastRows || [];
    if (!rows.length) return;
    const weakest = rows.reduce((a, b) => (b.score < a.score ? b : a));
    this.loopPhrase(weakest.phrase);
  }

  history() {
    const id = this.highway.songInfo ? this.highway.songInfo.songId : 'local';
    try { return JSON.parse(localStorage.getItem(COACH_HISTORY_KEY + id)) || []; } catch (err) { return []; }
  }

  // The try is over (Stop, or Start over): remember its score for this song, then clear it.
  finishSession(restart) {
    const { score, rows } = this.summarise(this.engine.getCurrentTime() + 1);
    const scoredNotes = rows.reduce((n, r) => n + r.scored, 0);
    if (score !== null && scoredNotes >= 8) {
      const id = this.highway.songInfo ? this.highway.songInfo.songId : 'local';
      const list = this.history();
      list.push({ date: Date.now(), score, level: this.settings.level });
      try { localStorage.setItem(COACH_HISTORY_KEY + id, JSON.stringify(list.slice(-20))); } catch (err) { /* private mode */ }
    }
    this.stats.clear();
    this.times.length = 0;
    this.midis.length = 0;
    this.sessionScored = false;
    this.lastRows = [];
    this.renderResults(this.engine.getCurrentTime());
    if (!restart) this.ui.results.hidden = !this.history().length;
    this.highway.lastKey = '';
  }

  restartScoring() {
    this.stats.clear();
    this.highway.lastKey = '';
  }

  // --- practice tools ---------------------------------------------------------------------

  setEcho(on) {
    this.settings.echo = on;
    const engine = this.engine;
    const track = this.highway.active ? engine.tracks.get(this.highway.active.trackId) : null;
    if (on) {
      if (!engine.isLooping || engine.loopEnd <= engine.loopStart) {
        // No A/B loop yet: use the phrase at the playhead (or the next one).
        const now = engine.getCurrentTime();
        const phrases = this.getPhrases();
        const phrase = phrases.find((p) => p.end > now) || phrases[0];
        if (!phrase) { this.ui.echo.checked = false; this.settings.echo = false; this.setStatus('Nothing to loop yet.', true); return; }
        engine.setLoop(true, Math.max(0, phrase.start - 0.4), phrase.end + 0.4);
        engine.seek(engine.loopStart);
      }
      this.mutedBefore = track ? track.isMuted : null;
      this.setPhase('listen');
      if (!engine.isPlaying) engine.play();
      this.ui.echo.checked = true;
    } else {
      this.phase = 'normal';
      this.restoreMute();
      this.setStatus(this.listening ? 'Listening. Sing along.' : '');
    }
    this.highway.lastKey = '';
  }

  setPhase(phase) {
    this.phase = phase;
    const engine = this.engine;
    const track = this.highway.active ? engine.tracks.get(this.highway.active.trackId) : null;
    if (track) {
      const wantMuted = phase === 'sing';
      if (track.isMuted !== wantMuted) engine.toggleTrackMute(this.highway.active.trackId);
    }
    this.setStatus(phase === 'sing' ? 'Your turn: sing it.' : 'Listen to the singer.');
    this.highway.lastKey = '';
  }

  restoreMute() {
    const engine = this.engine;
    const track = this.highway.active ? engine.tracks.get(this.highway.active.trackId) : null;
    if (track && this.mutedBefore !== null && track.isMuted !== this.mutedBefore) {
      engine.toggleTrackMute(this.highway.active.trackId);
    }
    this.mutedBefore = null;
  }

  // A soft tone on the note to sing, as a guide.
  followGuide(now) {
    const want = this.settings.guide && this.engine.isPlaying;
    if (!want && !this.guide) return;
    const ctx = this.engine.ctx;
    if (!this.guide) {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'triangle';
      gain.gain.value = 0;
      osc.connect(gain);
      gain.connect(this.engine.masterGain || ctx.destination);
      osc.start();
      this.guide = { osc, gain };
    }
    const target = want ? this.targetAt(now) : null;
    const { osc, gain } = this.guide;
    if (target) {
      osc.frequency.setTargetAtTime(440 * Math.pow(2, (target.midi - 69) / 12), ctx.currentTime, 0.03);
      gain.gain.setTargetAtTime(0.1, ctx.currentTime, 0.03);
    } else {
      gain.gain.setTargetAtTime(0, ctx.currentTime, 0.04);
    }
    if (!want && gain.gain.value < 0.001) {
      osc.stop();
      osc.disconnect();
      gain.disconnect();
      this.guide = null;
    }
  }

  // --- drawing on the highway --------------------------------------------------------------

  // Called by the highway inside its clipped lane: the singer's own line, and a readout at the now line.
  drawOverlay(ctx, hp) {
    const h = this.highway;
    if (h.kind !== 'melody') return;

    if (this.settings.echo && this.phase !== 'normal') {
      const sing = this.phase === 'sing';
      ctx.save();
      ctx.font = 'bold 13px "Inter", sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'top';
      const text = sing ? 'YOUR TURN' : 'LISTEN';
      const x = hp.gutter + hp.plotW / 2;
      ctx.fillStyle = sing ? 'rgba(52, 211, 153, 0.18)' : 'rgba(99, 102, 241, 0.18)';
      ctx.fillRect(x - 60, hp.top + 4, 120, 22);
      ctx.fillStyle = sing ? '#34d399' : '#a5b4fc';
      ctx.fillText(text, x, hp.top + 9);
      ctx.restore();
    }
    if (!this.listening) return;

    // The singer's line: one coloured piece per reading, green when close enough.
    const { timeToX, midiToY, minMidi, maxMidi, viewStart, viewEnd } = hp;
    const tol = this.level.cents;
    ctx.save();
    ctx.lineWidth = 3;
    ctx.lineCap = 'round';
    let prev = null;
    for (let i = 0; i < this.times.length; i++) {
      const time = this.times[i];
      if (time < viewStart) continue;
      if (time > viewEnd) break;
      const midi = this.midis[i];
      if (!midi) { prev = null; continue; }
      const target = this.targetAt(time);
      const shown = this.foldToTarget(midi, target);
      const err = target ? this.error(midi, target.midi) : null;
      if (shown < minMidi - 0.5 || shown > maxMidi + 0.5) { prev = null; continue; }
      const point = { x: timeToX(time), y: midiToY(shown) };
      if (prev && time - prev.time < 0.1) {
        ctx.strokeStyle = err === null ? 'rgba(255, 255, 255, 0.75)' : Math.abs(err) <= tol ? '#34d399' : Math.abs(err) <= tol * 2 ? '#fbbf24' : '#f87171';
        ctx.beginPath();
        ctx.moveTo(prev.x, prev.y);
        ctx.lineTo(point.x, point.y);
        ctx.stroke();
      }
      prev = { x: point.x, y: point.y, time };
    }
    ctx.restore();

    // Readout: what you are singing right now, and how far it is from the note.
    const live = this.live;
    if (live && live.midi) {
      const shown = this.foldToTarget(live.midi, live.target ? { midi: live.target } : null);
      if (shown >= minMidi - 0.5 && shown <= maxMidi + 0.5) {
        const y = midiToY(shown);
        const ok = live.err !== null && Math.abs(live.err) <= tol;
        const colour = live.err === null ? '#ffffff' : ok ? '#34d399' : '#f87171';
        ctx.save();
        ctx.shadowColor = colour;
        ctx.shadowBlur = 12;
        ctx.fillStyle = colour;
        ctx.beginPath();
        ctx.arc(hp.nowX, y, 6, 0, Math.PI * 2);
        ctx.fill();
        ctx.restore();

        const name = this.highway.noteSpelling(Math.round(live.midi));
        const swara = this.highway.sargam((((Math.round(live.midi)) % 12) + 12) % 12);
        let text = `You: ${name}${swara ? ' ' + swara : ''}`;
        if (live.err !== null) {
          const cents = Math.round(live.err);
          text += ok ? `  ${cents > 0 ? '+' : ''}${cents}c` : `  ${cents > 0 ? '\u2191 sharp' : '\u2193 flat'} ${Math.abs(cents)}c`;
        }
        ctx.font = 'bold 11px "JetBrains Mono", monospace';
        ctx.textAlign = 'right';
        ctx.textBaseline = 'middle';
        ctx.fillStyle = colour;
        ctx.fillText(text, hp.nowX - 12, Math.min(hp.h - 10, Math.max(hp.top + 10, y)));
      }
    }
  }

  // Draws the voice in the octave of the target when "any octave" is on, so it can be compared by eye.
  foldToTarget(midi, target) {
    if (!target || !this.settings.anyOctave) return midi;
    return target.midi + this.error(midi, target.midi) / 100;
  }
}
