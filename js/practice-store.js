/**
 * Practice that belongs to a song: coach scores and the lyrics timing nudge.
 * They are stored in the song's folder (practice.json), so they travel with the library.
 * The first time a song is opened, anything already saved in this browser is copied across once.
 */
const StemsPractice = {
  songId: null,
  coachHistory: [],
  lyricsOffset: 0,

  async loadSong(songId) {
    const generation = (this.loadGeneration || 0) + 1;
    this.loadGeneration = generation;
    this.songId = songId;
    this.coachHistory = [];
    this.lyricsOffset = 0;
    let stored = false;
    let data = null;
    try {
      const resp = await fetch(`/api/library/${encodeURIComponent(songId)}/practice`);
      if (resp.ok) data = await resp.json();
    } catch (err) { /* the browser copy is still there */ }
    if (this.songId !== songId || this.loadGeneration !== generation) return;
    if (data) {
      this.coachHistory = Array.isArray(data.coach_history) ? data.coach_history : [];
      this.lyricsOffset = Number(data.lyrics_offset) || 0;
      stored = data.stored === true;
    }
    if (stored) return;
    let localHistory = [];
    let localOffset = 0;
    try {
      localHistory = JSON.parse(localStorage.getItem(`stemsStudio.coach.history.${songId}`)) || [];
      localOffset = Number(localStorage.getItem(`stemsStudio.lyricsOffset.${songId}`)) || 0;
    } catch (err) { /* private mode */ }
    if (!localHistory.length && !localOffset) return;
    this.coachHistory = localHistory.slice(-20);
    this.lyricsOffset = localOffset;
    this.save();
  },

  historyFor(songId) {
    return this.songId === songId ? this.coachHistory : null;
  },

  offsetFor(songId) {
    return this.songId === songId ? this.lyricsOffset : null;
  },

  setLyricsOffset(songId, value) {
    if (this.songId !== songId) return;
    this.loadGeneration = (this.loadGeneration || 0) + 1;
    this.lyricsOffset = value;
    this.save();
  },

  remember(songId, entry) {
    if (this.songId !== songId) return false;
    this.loadGeneration = (this.loadGeneration || 0) + 1;
    this.coachHistory = this.coachHistory.concat(entry).slice(-20);
    this.save();
    return true;
  },

  save() {
    const songId = this.songId;
    const body = JSON.stringify({
      coach_history: this.coachHistory,
      lyrics_offset: this.lyricsOffset
    });
    fetch(`/api/library/${encodeURIComponent(songId)}/practice`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body
    }).catch(() => {});
  }
};
