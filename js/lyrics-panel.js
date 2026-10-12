/**
 * Stems Studio - Karaoke lyrics
 *
 * Shows the lyrics of the open song and follows the music: the line being sung is large and
 * fills with colour as it goes, the lines around it scroll past, and clicking a line jumps
 * to it. Lyrics come from the engine (server.py), which takes them from the song file's own
 * tags or from LRCLIB. If a song has none, "Find lyrics" searches LRCLIB by artist and title.
 *
 * All lyric text is put on the page as plain text (never as HTML).
 */
class LyricsPanel {
  constructor({ engine, panel }) {
    this.engine = engine;
    this.panel = panel;
    this.$ = (id) => panel.querySelector(`#${id}`);
    this.stage = this.$('lyricsStage');
    this.sourceEl = this.$('lyricsSource');
    this.syncBox = this.$('lyricsSyncBox');
    this.offsetLabel = this.$('lyricsOffsetLabel');
    this.findForm = this.$('lyricsFind');
    this.findStatus = this.$('lyricsFindStatus');

    this.songId = null;
    this.songTitle = '';
    this.lyrics = null;        // { synced, lines: [{t, text}], source, ... }
    this.lineEls = [];
    this.offset = 0;           // seconds added to every line time (the sync nudge)
    this.activeIndex = -2;
    this.requestId = 0;
    this.lastProgress = -1;
    this.collapsed = false;

    this.$('lyricsEarlier').addEventListener('click', () => this.nudge(-0.5));
    this.$('lyricsLater').addEventListener('click', () => this.nudge(0.5));
    this.$('lyricsFindToggle').addEventListener('click', () => this.toggleFind());
    this.$('lyricsCollapse').addEventListener('click', () => this.toggleCollapse());
    this.findForm.addEventListener('submit', (e) => { e.preventDefault(); this.search(); });
    this.stage.addEventListener('click', (e) => this.handleClick(e));

    this.loop = this.loop.bind(this);
    requestAnimationFrame(this.loop);
  }

  // --- loading ------------------------------------------------------------------------

  clear() {
    this.requestId++;
    this.songId = null;
    this.lyrics = null;
    this.panel.hidden = true;
  }

  async loadSong(songId, title) {
    const id = ++this.requestId;
    this.songId = songId;
    this.songTitle = title || '';
    this.lyrics = null;
    this.panel.hidden = false;
    this.findForm.hidden = true;
    this.findStatus.textContent = '';
    this.render();
    try {
      const resp = await fetch(`/api/lyrics/${songId}`);
      const data = await resp.json();
      if (id !== this.requestId) return;
      this.applyData(data);
    } catch (err) {
      if (id !== this.requestId) return;
      console.warn('Could not load lyrics', err);
      this.applyData({ found: false, meta: {} });
    }
  }

  applyData(data) {
    this.lyrics = data.found ? data : null;
    const meta = data.meta || {};
    const guess = this.guessArtistTitle();
    this.$('lyricsArtist').value = meta.artist || guess.artist || '';
    this.$('lyricsTitle').value = meta.title || guess.title || '';
    try {
      this.offset = Number(localStorage.getItem(`stemsStudio.lyricsOffset.${this.songId}`)) || 0;
    } catch (err) { this.offset = 0; }
    if (!this.lyrics) this.findForm.hidden = false;      // nothing found: offer the search straight away
    this.render();
  }

  // "13 - Would" or "Artist - Title" -> best guess for the search boxes.
  guessArtistTitle() {
    let text = (this.songTitle || '').replace(/\.[A-Za-z0-9]{2,5}$/, '');
    text = text.replace(/^\s*\d{1,3}\s*[-._)]\s+/, '');
    const m = text.split(/\s[-\u2013\u2014]\s/);
    if (m.length >= 2) return { artist: m[0].trim(), title: m.slice(1).join(' - ').trim() };
    return { artist: '', title: text.trim() };
  }

  async search() {
    const artist = this.$('lyricsArtist').value.trim();
    const title = this.$('lyricsTitle').value.trim();
    if (!title) { this.findStatus.textContent = 'Type the song title first.'; return; }
    const go = this.$('lyricsFindGo');
    go.disabled = true;
    this.findStatus.textContent = 'Searching LRCLIB...';
    const id = this.requestId;
    try {
      const url = `/api/lyrics/${this.songId}/find?artist=${encodeURIComponent(artist)}&title=${encodeURIComponent(title)}`;
      const resp = await fetch(url);
      const data = await resp.json();
      if (id !== this.requestId) return;
      if (!resp.ok) throw new Error(data.error || `Search failed (${resp.status})`);
      if (!data.found) {
        this.findStatus.textContent = 'No lyrics found for that. Try the artist and title as written on the album.';
      } else {
        this.findStatus.textContent = '';
        this.findForm.hidden = true;
        this.applyData(data);
      }
    } catch (err) {
      this.findStatus.textContent = err.message || 'Search failed.';
    } finally {
      go.disabled = false;
    }
  }

  // --- panel controls ------------------------------------------------------------------

  toggleFind() { this.findForm.hidden = !this.findForm.hidden; }

  toggleCollapse() {
    this.collapsed = !this.collapsed;
    this.stage.hidden = this.collapsed;
    this.$('lyricsCollapse').textContent = this.collapsed ? 'Show' : 'Hide';
  }

  nudge(delta) {
    this.offset = Math.round((this.offset + delta) * 10) / 10;
    try { localStorage.setItem(`stemsStudio.lyricsOffset.${this.songId}`, String(this.offset)); } catch (err) { /* ignore */ }
    this.activeIndex = -2;
    this.updateOffsetLabel();
  }

  updateOffsetLabel() {
    const sign = this.offset > 0 ? '+' : '';
    this.offsetLabel.textContent = `sync ${sign}${this.offset.toFixed(1)}s`;
  }

  handleClick(e) {
    if (!this.lyrics || !this.lyrics.synced) return;
    const el = e.target.closest('.lyric-line');
    if (!el) return;
    const line = this.lyrics.lines[Number(el.dataset.index)];
    if (line && line.t !== null) this.engine.seek(Math.max(0, line.t + this.offset));
  }

  // --- drawing -----------------------------------------------------------------------------

  render() {
    this.stage.textContent = '';
    this.lineEls = [];
    this.activeIndex = -2;
    this.lastProgress = -1;
    this.stage.classList.toggle('synced', Boolean(this.lyrics && this.lyrics.synced));

    if (!this.lyrics) {
      this.sourceEl.textContent = '';
      this.syncBox.hidden = true;
      const note = document.createElement('div');
      note.className = 'lyrics-empty';
      note.textContent = this.songId === null
        ? ''
        : 'No lyrics found for this song yet. Use "Find lyrics" to search by artist and title.';
      this.stage.appendChild(note);
      return;
    }

    const lyrics = this.lyrics;
    const where = lyrics.source === 'embedded' ? 'from the song file' : 'from LRCLIB';
    const matched = lyrics.matched && lyrics.matched.title
      ? ` (${lyrics.matched.artist ? lyrics.matched.artist + ' - ' : ''}${lyrics.matched.title})` : '';
    this.sourceEl.textContent = lyrics.synced
      ? `${where}${matched}. Click a line to jump to it.`
      : `${where}${matched}. These lyrics have no timing, so they do not follow the music.`;
    this.syncBox.hidden = !lyrics.synced;
    this.updateOffsetLabel();

    const inner = document.createElement('div');
    inner.className = 'lyrics-lines';
    lyrics.lines.forEach((line, index) => {
      const el = document.createElement('div');
      el.className = 'lyric-line';
      el.dataset.index = String(index);
      const text = line.text && line.text.trim() ? line.text : '\u266A';
      el.textContent = text;
      if (!line.text || !line.text.trim()) el.classList.add('lyric-gap');
      inner.appendChild(el);
      this.lineEls.push(el);
    });
    this.stage.appendChild(inner);
    this.inner = inner;
    this.stage.scrollTop = 0;
    inner.style.transform = '';
    this.centerOn(-1);
  }

  currentIndex(time) {
    const lines = this.lyrics.lines;
    let lo = 0;
    let hi = lines.length - 1;
    let found = -1;
    while (lo <= hi) {
      const mid = (lo + hi) >> 1;
      if (lines[mid].t + this.offset <= time) { found = mid; lo = mid + 1; } else hi = mid - 1;
    }
    return found;
  }

  // Scrolls the list so the current line sits in the middle of the stage.
  centerOn(index) {
    if (!this.inner) return;
    if (!this.lyrics.synced) return;
    const target = this.lineEls[Math.max(0, index)];
    if (!target) return;
    const stageH = this.stage.clientHeight;
    const shift = target.offsetTop + target.offsetHeight / 2 - stageH / 2;
    this.inner.style.transform = `translateY(${-Math.max(0, shift)}px)`;
  }

  loop() {
    if (this.lyrics && this.lyrics.synced && !this.panel.hidden && !this.collapsed) {
      const time = this.engine.getCurrentTime();
      const index = this.currentIndex(time);
      if (index !== this.activeIndex) {
        this.activeIndex = index;
        this.lineEls.forEach((el, i) => {
          el.classList.toggle('current', i === index);
          el.classList.toggle('past', i < index);
          el.style.removeProperty('--fill');
        });
        this.centerOn(index);
        this.lastProgress = -1;
      }
      if (index >= 0) {
        // The line fills with colour from its start to the start of the next line (at most 8 s).
        const lines = this.lyrics.lines;
        const start = lines[index].t + this.offset;
        const nextStart = index + 1 < lines.length ? lines[index + 1].t + this.offset : start + 6;
        const span = Math.max(0.5, Math.min(nextStart - start, 8));
        const progress = Math.max(0, Math.min(1, (time - start) / span));
        const rounded = Math.round(progress * 200) / 2;           // steps of 0.5 %
        if (rounded !== this.lastProgress) {
          this.lastProgress = rounded;
          this.lineEls[index].style.setProperty('--fill', `${rounded}%`);
        }
      }
    }
    requestAnimationFrame(this.loop);
  }
}
