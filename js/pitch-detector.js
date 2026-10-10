/**
 * Stems Studio - Real-Time Pitch Detection Engine
 * Uses YIN algorithm for accurate fundamental frequency detection
 * Converts detected frequencies to musical note names with cents deviation
 */

class PitchDetector {
  constructor(audioContext, options = {}) {
    this.ctx = audioContext;
    this.sampleRate = audioContext.sampleRate;
    this.bufferSize = options.bufferSize || 2048;
    this.threshold = options.threshold || 0.15;
    this.minFreq = options.minFreq || 60;   // ~B1
    this.maxFreq = options.maxFreq || 1500; // ~F#6
    
    this.analyser = null;
    this.dataArray = null;
    this.isRunning = false;
    
    this.onPitchDetected = options.onPitchDetected || (() => {});
    this.animationFrameId = null;
    
    this.NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
    this.A4_FREQ = 440;
    this.A4_MIDI = 69;
    
    this.pitchHistory = [];
    this.historySize = 5;
    
    this.lastValidPitch = null;
    this.silenceThreshold = 0.01;
  }

  init(sourceNode) {
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = this.bufferSize * 2;
    this.analyser.smoothingTimeConstant = 0;
    
    sourceNode.connect(this.analyser);
    this.dataArray = new Float32Array(this.bufferSize);
  }

  start() {
    if (this.isRunning) return;
    this.isRunning = true;
    this.detectLoop();
  }

  stop() {
    this.isRunning = false;
    if (this.animationFrameId) {
      cancelAnimationFrame(this.animationFrameId);
      this.animationFrameId = null;
    }
  }

  detectLoop() {
    if (!this.isRunning) return;
    
    this.analyser.getFloatTimeDomainData(this.dataArray);
    
    const rms = this.calculateRMS(this.dataArray);
    
    if (rms < this.silenceThreshold) {
      this.onPitchDetected({
        frequency: null,
        note: null,
        octave: null,
        cents: 0,
        confidence: 0,
        rms: rms,
        isSilent: true
      });
    } else {
      const result = this.detectPitchYIN(this.dataArray);
      
      if (result.frequency && result.confidence > 0.85) {
        const smoothedFreq = this.smoothPitch(result.frequency);
        const noteInfo = this.frequencyToNote(smoothedFreq);
        
        this.lastValidPitch = {
          frequency: smoothedFreq,
          ...noteInfo,
          confidence: result.confidence,
          rms: rms,
          isSilent: false
        };
        
        this.onPitchDetected(this.lastValidPitch);
      } else {
        this.onPitchDetected({
          frequency: this.lastValidPitch?.frequency || null,
          note: this.lastValidPitch?.note || null,
          octave: this.lastValidPitch?.octave || null,
          cents: this.lastValidPitch?.cents || 0,
          confidence: result.confidence || 0,
          rms: rms,
          isSilent: false,
          isUncertain: true
        });
      }
    }
    
    this.animationFrameId = requestAnimationFrame(() => this.detectLoop());
  }

  detectPitchYIN(buffer) {
    const yinBuffer = new Float32Array(Math.floor(this.bufferSize / 2));
    const minPeriod = Math.floor(this.sampleRate / this.maxFreq);
    const maxPeriod = Math.floor(this.sampleRate / this.minFreq);
    
    yinBuffer[0] = 1;
    let runningSum = 0;
    
    for (let tau = 1; tau < yinBuffer.length; tau++) {
      yinBuffer[tau] = 0;
      for (let i = 0; i < yinBuffer.length; i++) {
        const delta = buffer[i] - buffer[i + tau];
        yinBuffer[tau] += delta * delta;
      }
      runningSum += yinBuffer[tau];
      yinBuffer[tau] *= tau / runningSum;
    }
    
    let bestTau = -1;
    let bestConfidence = 0;
    
    for (let tau = minPeriod; tau < maxPeriod && tau < yinBuffer.length; tau++) {
      if (yinBuffer[tau] < this.threshold) {
        while (tau + 1 < yinBuffer.length && yinBuffer[tau + 1] < yinBuffer[tau]) {
          tau++;
        }
        
        const confidence = 1 - yinBuffer[tau];
        if (confidence > bestConfidence) {
          bestConfidence = confidence;
          bestTau = tau;
        }
        break;
      }
    }
    
    if (bestTau === -1) {
      return { frequency: null, confidence: 0 };
    }
    
    let betterTau = bestTau;
    if (bestTau > 0 && bestTau < yinBuffer.length - 1) {
      const s0 = yinBuffer[bestTau - 1];
      const s1 = yinBuffer[bestTau];
      const s2 = yinBuffer[bestTau + 1];
      betterTau = bestTau + (s2 - s0) / (2 * (2 * s1 - s2 - s0));
    }
    
    const frequency = this.sampleRate / betterTau;
    
    return {
      frequency: frequency,
      confidence: bestConfidence
    };
  }

  smoothPitch(frequency) {
    this.pitchHistory.push(frequency);
    if (this.pitchHistory.length > this.historySize) {
      this.pitchHistory.shift();
    }
    
    const sorted = [...this.pitchHistory].sort((a, b) => a - b);
    return sorted[Math.floor(sorted.length / 2)];
  }

  frequencyToNote(frequency) {
    if (!frequency || frequency <= 0) {
      return { note: null, octave: null, cents: 0, midiNumber: null };
    }
    
    const midiNumber = 12 * Math.log2(frequency / this.A4_FREQ) + this.A4_MIDI;
    const roundedMidi = Math.round(midiNumber);
    const cents = Math.round((midiNumber - roundedMidi) * 100);
    
    const noteIndex = ((roundedMidi % 12) + 12) % 12;
    const octave = Math.floor(roundedMidi / 12) - 1;
    
    return {
      note: this.NOTE_NAMES[noteIndex],
      octave: octave,
      cents: cents,
      midiNumber: roundedMidi,
      exactMidi: midiNumber
    };
  }

  noteToFrequency(note, octave) {
    const noteIndex = this.NOTE_NAMES.indexOf(note.toUpperCase());
    if (noteIndex === -1) return null;
    
    const midiNumber = (octave + 1) * 12 + noteIndex;
    return this.A4_FREQ * Math.pow(2, (midiNumber - this.A4_MIDI) / 12);
  }

  midiToFrequency(midiNumber) {
    return this.A4_FREQ * Math.pow(2, (midiNumber - this.A4_MIDI) / 12);
  }

  frequencyToMidi(frequency) {
    return 12 * Math.log2(frequency / this.A4_FREQ) + this.A4_MIDI;
  }

  calculateRMS(buffer) {
    let sum = 0;
    for (let i = 0; i < buffer.length; i++) {
      sum += buffer[i] * buffer[i];
    }
    return Math.sqrt(sum / buffer.length);
  }

  static analyzeAudioBuffer(audioBuffer, sampleRate, options = {}) {
    const hopSize = options.hopSize || 512;
    const frameSize = options.frameSize || 2048;
    const channelData = audioBuffer.getChannelData(0);
    const results = [];
    
    const detector = {
      threshold: options.threshold || 0.15,
      minFreq: options.minFreq || 60,
      maxFreq: options.maxFreq || 1500,
      silenceThreshold: options.silenceThreshold || 0.01
    };
    
    for (let i = 0; i + frameSize < channelData.length; i += hopSize) {
      const frame = channelData.slice(i, i + frameSize);
      const time = i / sampleRate;
      
      let rms = 0;
      for (let j = 0; j < frame.length; j++) {
        rms += frame[j] * frame[j];
      }
      rms = Math.sqrt(rms / frame.length);
      
      if (rms < detector.silenceThreshold) {
        results.push({ time, frequency: null, confidence: 0, rms, isSilent: true });
        continue;
      }
      
      const yinBuffer = new Float32Array(Math.floor(frameSize / 2));
      const minPeriod = Math.floor(sampleRate / detector.maxFreq);
      const maxPeriod = Math.floor(sampleRate / detector.minFreq);
      
      yinBuffer[0] = 1;
      let runningSum = 0;
      
      for (let tau = 1; tau < yinBuffer.length; tau++) {
        yinBuffer[tau] = 0;
        for (let k = 0; k < yinBuffer.length; k++) {
          const delta = frame[k] - frame[k + tau];
          yinBuffer[tau] += delta * delta;
        }
        runningSum += yinBuffer[tau];
        yinBuffer[tau] *= tau / runningSum;
      }
      
      let bestTau = -1;
      let bestConfidence = 0;
      
      for (let tau = minPeriod; tau < maxPeriod && tau < yinBuffer.length; tau++) {
        if (yinBuffer[tau] < detector.threshold) {
          while (tau + 1 < yinBuffer.length && yinBuffer[tau + 1] < yinBuffer[tau]) {
            tau++;
          }
          bestConfidence = 1 - yinBuffer[tau];
          bestTau = tau;
          break;
        }
      }
      
      if (bestTau === -1) {
        results.push({ time, frequency: null, confidence: 0, rms, isSilent: false });
        continue;
      }
      
      let betterTau = bestTau;
      if (bestTau > 0 && bestTau < yinBuffer.length - 1) {
        const s0 = yinBuffer[bestTau - 1];
        const s1 = yinBuffer[bestTau];
        const s2 = yinBuffer[bestTau + 1];
        betterTau = bestTau + (s2 - s0) / (2 * (2 * s1 - s2 - s0));
      }
      
      const frequency = sampleRate / betterTau;
      
      results.push({
        time,
        frequency: bestConfidence > 0.8 ? frequency : null,
        confidence: bestConfidence,
        rms,
        isSilent: false
      });
    }
    
    return results;
  }
}

window.PitchDetector = PitchDetector;
