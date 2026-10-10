/**
 * Stems Studio - High Performance Multi-Track Web Audio Engine
 * Synchronized playback, track-level routing, VU meters, EQ, pitch and speed.
 */

class AudioEngine {
  constructor() {
    this.ctx = null;
    this.masterGain = null;
    this.masterAnalyserL = null;
    this.masterAnalyserR = null;
    this.masterSplitter = null;

    this.tracks = new Map(); // id -> TrackState
    this.isPlaying = false;
    this.playbackRate = 1.0;
    this.pitchSemitones = 0; // -12 to +12

    // Timeline state
    this.currentPosition = 0; // seconds
    this.lastStartAudioTime = 0;
    this.totalDuration = 0;

    // A/B Looping
    this.isLooping = false;
    this.loopStart = 0;
    this.loopEnd = 0;

    // Metronome
    this.metronomeActive = false;
    this.bpm = 120;
    this.nextMetronomeClick = 0;
    this.metronomeIntervalId = null;

    this.listeners = new Set();
  }

  init() {
    if (this.ctx) return;
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    this.ctx = new AudioCtx();

    // Master bus
    this.masterGain = this.ctx.createGain();
    this.masterGain.gain.setValueAtTime(1.0, this.ctx.currentTime);

    // Master Stereo Analysers
    this.masterSplitter = this.ctx.createChannelSplitter(2);
    this.masterAnalyserL = this.ctx.createAnalyser();
    this.masterAnalyserR = this.ctx.createAnalyser();
    this.masterAnalyserL.fftSize = 256;
    this.masterAnalyserR.fftSize = 256;

    this.masterGain.connect(this.masterSplitter);
    this.masterSplitter.connect(this.masterAnalyserL, 0);
    this.masterSplitter.connect(this.masterAnalyserR, 1);
    this.masterGain.connect(this.ctx.destination);
  }

  async resume() {
    this.init();
    if (this.ctx.state === 'suspended') {
      await this.ctx.resume();
    }
  }

  /**
   * Register a new stem track
   */
  addTrack(id, name, stemType, audioBuffer = null) {
    this.init();

    // Track node routing
    const trackGain = this.ctx.createGain();
    const muteSoloGain = this.ctx.createGain();
    const panner = this.ctx.createStereoPanner();

    // 3-Band Equalizer
    const eqLow = this.ctx.createBiquadFilter();
    eqLow.type = 'lowshelf';
    eqLow.frequency.value = 320;
    eqLow.gain.value = 0;

    const eqMid = this.ctx.createBiquadFilter();
    eqMid.type = 'peaking';
    eqMid.frequency.value = 1000;
    eqMid.Q.value = 1.0;
    eqMid.gain.value = 0;

    const eqHigh = this.ctx.createBiquadFilter();
    eqHigh.type = 'highshelf';
    eqHigh.frequency.value = 3200;
    eqHigh.gain.value = 0;

    const analyser = this.ctx.createAnalyser();
    analyser.fftSize = 128;

    // Chain: Source -> EQ Low -> EQ Mid -> EQ High -> Panner -> TrackGain -> MuteSoloGain -> Analyser -> Master
    eqLow.connect(eqMid);
    eqMid.connect(eqHigh);
    eqHigh.connect(panner);
    panner.connect(trackGain);
    trackGain.connect(muteSoloGain);
    muteSoloGain.connect(analyser);
    muteSoloGain.connect(this.masterGain);

    const track = {
      id,
      name,
      stemType, // 'vocal' | 'drums' | 'bass' | 'other' | 'custom'
      buffer: audioBuffer,
      source: null,
      volume: 1.0, // 0 to 2 (1.0 = 0dB)
      pan: 0,      // -1 to 1
      isMuted: false,
      isSoloed: false,
      nodes: {
        eqLow,
        eqMid,
        eqHigh,
        panner,
        trackGain,
        muteSoloGain,
        analyser
      },
      peaks: null
    };

    if (audioBuffer) {
      track.peaks = this.extractPeaks(audioBuffer, 1200);
      this.updateTotalDuration();
    }

    this.tracks.set(id, track);
    this.updateMuteSoloStates();
    return track;
  }

  setTrackBuffer(id, audioBuffer) {
    const track = this.tracks.get(id);
    if (!track) return;
    track.buffer = audioBuffer;
    track.peaks = this.extractPeaks(audioBuffer, 1200);
    this.updateTotalDuration();

    if (this.isPlaying) {
      // Re-trigger track source at current playhead
      this.startTrackSource(track, this.currentPosition);
    }
  }

  removeTrack(id) {
    const track = this.tracks.get(id);
    if (!track) return;
    if (track.source) {
      try { track.source.stop(); } catch (e) {}
    }
    this.tracks.delete(id);
    this.updateTotalDuration();
    this.updateMuteSoloStates();
  }

  updateTotalDuration() {
    let max = 0;
    for (const track of this.tracks.values()) {
      if (track.buffer && track.buffer.duration > max) {
        max = track.buffer.duration;
      }
    }
    this.totalDuration = max;
    if (this.loopEnd === 0 || this.loopEnd > max) {
      this.loopEnd = max;
    }
    this.emit('durationChanged', this.totalDuration);
  }

  /**
   * Multi-track Playback Control
   */
  async play(fromPosition = null) {
    await this.resume();
    if (this.isPlaying) return;

    if (fromPosition !== null) {
      this.currentPosition = Math.max(0, Math.min(fromPosition, this.totalDuration));
    }

    if (this.currentPosition >= this.totalDuration && this.totalDuration > 0) {
      this.currentPosition = 0;
    }

    this.lastStartAudioTime = this.ctx.currentTime;
    this.isPlaying = true;

    // Start all track buffer sources simultaneously
    for (const track of this.tracks.values()) {
      if (track.buffer) {
        this.startTrackSource(track, this.currentPosition);
      }
    }

    this.emit('playbackStateChanged', true);
  }

  startTrackSource(track, offsetSeconds) {
    if (!this.ctx || !track.buffer) return;
    if (track.source) {
      try { track.source.stop(); } catch (e) {}
      track.source.disconnect();
    }

    const source = this.ctx.createBufferSource();
    source.buffer = track.buffer;

    // Calculate effective playback rate including semitone shift
    const semitoneRatio = Math.pow(2, this.pitchSemitones / 12);
    source.playbackRate.value = this.playbackRate * semitoneRatio;

    source.connect(track.nodes.eqLow);

    // Looping handling
    if (this.isLooping && this.loopEnd > this.loopStart) {
      source.loop = true;
      source.loopStart = this.loopStart;
      source.loopEnd = this.loopEnd;
    } else {
      source.loop = false;
    }

    const duration = track.buffer.duration;
    if (offsetSeconds < duration) {
      source.start(0, offsetSeconds);
    }
    track.source = source;
  }

  pause() {
    if (!this.isPlaying) return;
    this.currentPosition = this.getCurrentTime();
    this.isPlaying = false;

    for (const track of this.tracks.values()) {
      if (track.source) {
        try { track.source.stop(); } catch (e) {}
        track.source = null;
      }
    }

    this.emit('playbackStateChanged', false);
  }

  stop() {
    this.pause();
    this.seek(0);
  }

  seek(seconds) {
    const target = Math.max(0, Math.min(seconds, this.totalDuration));
    this.currentPosition = target;
    this.lastStartAudioTime = this.ctx ? this.ctx.currentTime : 0;

    if (this.isPlaying) {
      for (const track of this.tracks.values()) {
        if (track.buffer) {
          this.startTrackSource(track, target);
        }
      }
    }
    this.emit('seeked', target);
  }

  getCurrentTime() {
    if (!this.isPlaying || !this.ctx) {
      return this.currentPosition;
    }

    const semitoneRatio = Math.pow(2, this.pitchSemitones / 12);
    const speed = this.playbackRate * semitoneRatio;
    const elapsed = (this.ctx.currentTime - this.lastStartAudioTime) * speed;
    let pos = this.currentPosition + elapsed;

    if (this.isLooping && this.loopEnd > this.loopStart) {
      if (pos >= this.loopEnd) {
        const loopLen = this.loopEnd - this.loopStart;
        pos = this.loopStart + ((pos - this.loopStart) % loopLen);
      }
    } else if (pos >= this.totalDuration && this.totalDuration > 0) {
      this.pause();
      pos = this.totalDuration;
    }

    return pos;
  }

  /**
   * Track Controls: Volume, Pan, Mute, Solo, EQ
   */
  setTrackVolume(id, volume) {
    const track = this.tracks.get(id);
    if (!track) return;
    track.volume = volume;
    track.nodes.trackGain.gain.setValueAtTime(volume, this.ctx.currentTime);
  }

  setTrackPan(id, pan) {
    const track = this.tracks.get(id);
    if (!track) return;
    track.pan = Math.max(-1, Math.min(1, pan));
    track.nodes.panner.pan.setValueAtTime(track.pan, this.ctx.currentTime);
  }

  toggleTrackMute(id) {
    const track = this.tracks.get(id);
    if (!track) return;
    track.isMuted = !track.isMuted;
    this.updateMuteSoloStates();
    return track.isMuted;
  }

  toggleTrackSolo(id) {
    const track = this.tracks.get(id);
    if (!track) return;
    track.isSoloed = !track.isSoloed;
    this.updateMuteSoloStates();
    return track.isSoloed;
  }

  updateMuteSoloStates() {
    const anySolo = Array.from(this.tracks.values()).some(t => t.isSoloed);

    for (const track of this.tracks.values()) {
      let active = true;
      if (anySolo) {
        active = track.isSoloed && !track.isMuted;
      } else {
        active = !track.isMuted;
      }

      const targetGain = active ? 1.0 : 0.0;
      track.nodes.muteSoloGain.gain.setTargetAtTime(targetGain, this.ctx.currentTime, 0.02);
    }
    this.emit('mixStateChanged');
  }

  setTrackEQ(id, band, gainDb) {
    const track = this.tracks.get(id);
    if (!track) return;
    const node = band === 'low' ? track.nodes.eqLow : (band === 'mid' ? track.nodes.eqMid : track.nodes.eqHigh);
    if (node) {
      node.gain.setTargetAtTime(gainDb, this.ctx.currentTime, 0.05);
    }
  }

  setMasterVolume(vol) {
    if (!this.masterGain) return;
    this.masterGain.gain.setTargetAtTime(vol, this.ctx.currentTime, 0.02);
  }

  setPlaybackRate(rate) {
    this.playbackRate = Math.max(0.25, Math.min(2.0, rate));
    if (this.isPlaying) {
      this.seek(this.getCurrentTime());
    }
    this.emit('rateChanged', this.playbackRate);
  }

  setPitchSemitones(semitones) {
    this.pitchSemitones = Math.max(-12, Math.min(12, semitones));
    if (this.isPlaying) {
      this.seek(this.getCurrentTime());
    }
    this.emit('pitchChanged', this.pitchSemitones);
  }

  setLoop(enabled, start = null, end = null) {
    this.isLooping = enabled;
    if (start !== null) this.loopStart = Math.max(0, start);
    if (end !== null) this.loopEnd = Math.max(this.loopStart + 0.1, end);

    if (this.isPlaying) {
      this.seek(this.getCurrentTime());
    }
    this.emit('loopChanged', { enabled: this.isLooping, start: this.loopStart, end: this.loopEnd });
  }

  /**
   * Metering: RMS and Peak
   */
  getTrackLevels(id) {
    const track = this.tracks.get(id);
    if (!track || !this.isPlaying) return { rms: 0, peak: 0, clip: false };

    const data = new Uint8Array(track.nodes.analyser.frequencyBinCount);
    track.nodes.analyser.getByteTimeDomainData(data);

    let sum = 0;
    let peak = 0;
    for (let i = 0; i < data.length; i++) {
      const v = (data[i] - 128) / 128;
      const absV = Math.abs(v);
      if (absV > peak) peak = absV;
      sum += v * v;
    }
    const rms = Math.sqrt(sum / data.length);
    return { rms, peak, clip: peak >= 0.99 };
  }

  getMasterLevels() {
    if (!this.masterAnalyserL || !this.isPlaying) {
      return { left: 0, right: 0, clip: false };
    }

    const dataL = new Uint8Array(this.masterAnalyserL.frequencyBinCount);
    const dataR = new Uint8Array(this.masterAnalyserR.frequencyBinCount);
    this.masterAnalyserL.getByteTimeDomainData(dataL);
    this.masterAnalyserR.getByteTimeDomainData(dataR);

    let peakL = 0, peakR = 0;
    for (let i = 0; i < dataL.length; i++) {
      const vL = Math.abs((dataL[i] - 128) / 128);
      const vR = Math.abs((dataR[i] - 128) / 128);
      if (vL > peakL) peakL = vL;
      if (vR > peakR) peakR = vR;
    }

    return {
      left: Math.min(1.0, peakL * 1.2),
      right: Math.min(1.0, peakR * 1.2),
      clip: peakL >= 0.99 || peakR >= 0.99
    };
  }

  /**
   * Fast Waveform Peak Extractor
   */
  extractPeaks(buffer, targetBins = 1200) {
    const channels = buffer.numberOfChannels;
    const length = buffer.length;
    const blockSize = Math.floor(length / targetBins);
    const peaks = new Float32Array(targetBins * 2); // [min0, max0, min1, max1, ...]

    const channelData = buffer.getChannelData(0); // Primary channel for visualization

    for (let bin = 0; bin < targetBins; bin++) {
      let min = 1.0;
      let max = -1.0;
      const start = bin * blockSize;
      const end = Math.min(start + blockSize, length);

      // Sample every Nth value for performance
      const step = Math.max(1, Math.floor((end - start) / 40));
      for (let i = start; i < end; i += step) {
        const val = channelData[i];
        if (val < min) min = val;
        if (val > max) max = val;
      }
      peaks[bin * 2] = min;
      peaks[bin * 2 + 1] = max;
    }
    return peaks;
  }

  on(event, fn) {
    this.listeners.add({ event, fn });
  }

  emit(event, data) {
    for (const l of this.listeners) {
      if (l.event === event) l.fn(data);
    }
  }

  // =========================================================================
  // Vocal Training Module - Recording Track & Pitch Analysis
  // =========================================================================

  initVocalTraining() {
    if (this.vocalRecorder) return;
    
    this.vocalRecorder = new VocalRecorder(this.ctx);
    this.pitchVisualizer = null;
    this.originalVocalPitchData = null;
    this.userPitchData = [];
    this.isRecordingVocals = false;
    this.comparisonMode = 'side-by-side'; // 'side-by-side', 'overlay', 'a-b-toggle'
    this.playbackSource = 'original'; // 'original', 'user', 'both'
    
    this.userVocalTrack = null;
  }

  async requestMicrophoneAccess() {
    this.initVocalTraining();
    
    this.vocalRecorder.onPitchUpdate = (pitchInfo) => {
      if (this.isRecordingVocals) {
        const currentTime = this.getCurrentTime();
        this.userPitchData.push({
          time: currentTime,
          ...pitchInfo
        });
      }
      this.emit('pitchDetected', pitchInfo);
    };
    
    this.vocalRecorder.onLevelUpdate = (levels) => {
      this.emit('micLevelUpdate', levels);
    };
    
    this.vocalRecorder.onRecordingComplete = (recording) => {
      this.processUserRecording(recording);
    };
    
    return await this.vocalRecorder.requestMicrophoneAccess();
  }

  async analyzeVocalStem() {
    const vocalTrack = this.tracks.get('vocal');
    if (!vocalTrack || !vocalTrack.buffer) {
      return null;
    }
    
    this.emit('analysisStarted', { type: 'vocal' });
    
    const pitchData = PitchDetector.analyzeAudioBuffer(
      vocalTrack.buffer,
      this.ctx.sampleRate,
      {
        hopSize: 512,
        frameSize: 2048,
        threshold: 0.12,
        minFreq: 80,
        maxFreq: 1200
      }
    );
    
    this.originalVocalPitchData = pitchData.map(p => ({
      time: p.time,
      frequency: p.frequency,
      confidence: p.confidence,
      isSilent: p.isSilent
    }));
    
    this.emit('analysisComplete', {
      type: 'vocal',
      data: this.originalVocalPitchData
    });
    
    return this.originalVocalPitchData;
  }

  getOriginalVocalPitchData() {
    return this.originalVocalPitchData;
  }

  getUserPitchData() {
    return this.userPitchData;
  }

  async startVocalRecording() {
    if (!this.vocalRecorder || !this.vocalRecorder.hasPermission) {
      const result = await this.requestMicrophoneAccess();
      if (!result.success) return false;
    }
    
    this.userPitchData = [];
    const startOffset = this.getCurrentTime();
    
    const success = await this.vocalRecorder.startRecording(startOffset);
    if (success) {
      this.isRecordingVocals = true;
      this.emit('recordingStateChanged', { recording: true, offset: startOffset });
    }
    
    return success;
  }

  stopVocalRecording() {
    if (!this.vocalRecorder || !this.isRecordingVocals) return null;
    
    const result = this.vocalRecorder.stopRecording();
    this.isRecordingVocals = false;
    this.emit('recordingStateChanged', { recording: false, result });
    
    return result;
  }

  processUserRecording(recording) {
    const { buffer, offset, duration } = recording;
    
    if (!this.userVocalTrack) {
      this.userVocalTrack = {
        id: 'user-vocal',
        name: 'My Recording / मेरो रेकर्डिङ',
        stemType: 'user-vocal',
        buffer: buffer,
        source: null,
        volume: 1.0,
        pan: 0,
        isMuted: false,
        isSoloed: false,
        offset: offset,
        peaks: null,
        nodes: this.createTrackNodes()
      };
    } else {
      this.userVocalTrack.buffer = buffer;
      this.userVocalTrack.offset = offset;
    }
    
    this.userVocalTrack.peaks = this.extractPeaks(buffer, 1200);
    
    this.emit('userRecordingReady', {
      track: this.userVocalTrack,
      pitchData: this.userPitchData
    });
  }

  createTrackNodes() {
    const trackGain = this.ctx.createGain();
    const muteSoloGain = this.ctx.createGain();
    const panner = this.ctx.createStereoPanner();
    
    const eqLow = this.ctx.createBiquadFilter();
    eqLow.type = 'lowshelf';
    eqLow.frequency.value = 320;
    eqLow.gain.value = 0;
    
    const eqMid = this.ctx.createBiquadFilter();
    eqMid.type = 'peaking';
    eqMid.frequency.value = 1000;
    eqMid.Q.value = 1.0;
    eqMid.gain.value = 0;
    
    const eqHigh = this.ctx.createBiquadFilter();
    eqHigh.type = 'highshelf';
    eqHigh.frequency.value = 3200;
    eqHigh.gain.value = 0;
    
    const analyser = this.ctx.createAnalyser();
    analyser.fftSize = 128;
    
    eqLow.connect(eqMid);
    eqMid.connect(eqHigh);
    eqHigh.connect(panner);
    panner.connect(trackGain);
    trackGain.connect(muteSoloGain);
    muteSoloGain.connect(analyser);
    muteSoloGain.connect(this.masterGain);
    
    return { eqLow, eqMid, eqHigh, panner, trackGain, muteSoloGain, analyser };
  }

  getUserVocalTrack() {
    return this.userVocalTrack;
  }

  setComparisonMode(mode) {
    this.comparisonMode = mode;
    this.updateComparisonPlayback();
    this.emit('comparisonModeChanged', mode);
  }

  setPlaybackSource(source) {
    this.playbackSource = source;
    this.updateComparisonPlayback();
    this.emit('playbackSourceChanged', source);
  }

  updateComparisonPlayback() {
    const vocalTrack = this.tracks.get('vocal');
    
    if (this.playbackSource === 'original') {
      if (vocalTrack) vocalTrack.isMuted = false;
      if (this.userVocalTrack) this.userVocalTrack.isMuted = true;
    } else if (this.playbackSource === 'user') {
      if (vocalTrack) vocalTrack.isMuted = true;
      if (this.userVocalTrack) this.userVocalTrack.isMuted = false;
    } else {
      if (vocalTrack) vocalTrack.isMuted = false;
      if (this.userVocalTrack) this.userVocalTrack.isMuted = false;
    }
    
    this.updateMuteSoloStates();
  }

  playUserVocalTrack(offset = 0) {
    if (!this.userVocalTrack || !this.userVocalTrack.buffer) return;
    
    if (this.userVocalTrack.source) {
      try { this.userVocalTrack.source.stop(); } catch (e) {}
    }
    
    const source = this.ctx.createBufferSource();
    source.buffer = this.userVocalTrack.buffer;
    source.connect(this.userVocalTrack.nodes.eqLow);
    
    const trackOffset = this.userVocalTrack.offset || 0;
    const playOffset = Math.max(0, offset - trackOffset);
    
    if (playOffset < this.userVocalTrack.buffer.duration) {
      source.start(0, playOffset);
    }
    
    this.userVocalTrack.source = source;
  }

  stopUserVocalTrack() {
    if (this.userVocalTrack && this.userVocalTrack.source) {
      try { this.userVocalTrack.source.stop(); } catch (e) {}
      this.userVocalTrack.source = null;
    }
  }

  setMicMonitorEnabled(enabled) {
    if (this.vocalRecorder) {
      this.vocalRecorder.setMonitorEnabled(enabled);
    }
  }

  setMicInputLevel(level) {
    if (this.vocalRecorder) {
      this.vocalRecorder.setInputLevel(level);
    }
  }

  clearUserRecording() {
    if (this.vocalRecorder) {
      this.vocalRecorder.clearRecording();
    }
    this.userPitchData = [];
    this.userVocalTrack = null;
    this.emit('userRecordingCleared');
  }

  async downloadUserRecording(filename) {
    if (this.vocalRecorder) {
      return await this.vocalRecorder.downloadRecording(filename);
    }
    return false;
  }

  calculatePitchAccuracy() {
    if (!this.originalVocalPitchData || !this.userPitchData) {
      return null;
    }
    
    let matchedCount = 0;
    let totalCount = 0;
    let totalCentsOff = 0;
    
    const tolerance = 50;
    const timeTolerance = 0.1;
    
    for (const userPoint of this.userPitchData) {
      if (!userPoint.frequency) continue;
      
      const nearestOriginal = this.originalVocalPitchData.find(p => 
        Math.abs(p.time - userPoint.time) < timeTolerance && p.frequency
      );
      
      if (nearestOriginal) {
        totalCount++;
        
        const userMidi = 12 * Math.log2(userPoint.frequency / 440) + 69;
        const originalMidi = 12 * Math.log2(nearestOriginal.frequency / 440) + 69;
        const centsDiff = Math.abs((userMidi - originalMidi) * 100);
        
        totalCentsOff += centsDiff;
        
        if (centsDiff <= tolerance) {
          matchedCount++;
        }
      }
    }
    
    if (totalCount === 0) return null;
    
    return {
      accuracy: (matchedCount / totalCount) * 100,
      averageCentsOff: totalCentsOff / totalCount,
      totalNotes: totalCount,
      matchedNotes: matchedCount
    };
  }
}

window.AudioEngine = AudioEngine;
