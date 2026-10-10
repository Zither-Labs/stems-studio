/**
 * Stems Studio - Vocal Recording Engine
 * Captures microphone input, syncs with playback, enables A/B comparison
 */

class VocalRecorder {
  constructor(audioContext) {
    this.ctx = audioContext;
    this.mediaStream = null;
    this.mediaStreamSource = null;
    this.recordingGain = null;
    this.monitorGain = null;
    this.analyser = null;
    
    this.isRecording = false;
    this.isPaused = false;
    this.hasPermission = false;
    
    this.recordedChunks = [];
    this.recordedBuffer = null;
    this.recordingStartTime = 0;
    this.recordingOffset = 0;
    
    this.workletNode = null;
    this.mediaRecorder = null;
    
    this.pitchDetector = null;
    this.onPitchUpdate = null;
    this.onLevelUpdate = null;
    this.onRecordingComplete = null;
    
    this.monitorEnabled = false;
    this.inputLevel = 1.0;
    
    this.levelAnimationId = null;
  }

  async requestMicrophoneAccess() {
    try {
      this.mediaStream = await navigator.mediaDevices.getUserMedia({
        audio: {
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: false,
          channelCount: 1,
          sampleRate: this.ctx.sampleRate
        }
      });
      
      this.hasPermission = true;
      this.setupAudioGraph();
      return { success: true };
    } catch (err) {
      console.error('Microphone access denied:', err);
      this.hasPermission = false;
      return { success: false, error: err.message };
    }
  }

  setupAudioGraph() {
    if (!this.mediaStream) return;
    
    this.mediaStreamSource = this.ctx.createMediaStreamSource(this.mediaStream);
    
    this.recordingGain = this.ctx.createGain();
    this.recordingGain.gain.value = this.inputLevel;
    
    this.monitorGain = this.ctx.createGain();
    this.monitorGain.gain.value = 0;
    
    this.analyser = this.ctx.createAnalyser();
    this.analyser.fftSize = 2048;
    this.analyser.smoothingTimeConstant = 0.3;
    
    this.mediaStreamSource.connect(this.recordingGain);
    this.recordingGain.connect(this.analyser);
    this.recordingGain.connect(this.monitorGain);
    this.monitorGain.connect(this.ctx.destination);
    
    if (this.onPitchUpdate) {
      this.pitchDetector = new PitchDetector(this.ctx, {
        onPitchDetected: this.onPitchUpdate,
        bufferSize: 2048,
        threshold: 0.12
      });
      this.pitchDetector.init(this.recordingGain);
    }
    
    this.startLevelMonitoring();
  }

  startLevelMonitoring() {
    const dataArray = new Uint8Array(this.analyser.frequencyBinCount);
    
    const updateLevel = () => {
      if (!this.analyser) return;
      
      this.analyser.getByteTimeDomainData(dataArray);
      
      let sum = 0;
      let peak = 0;
      for (let i = 0; i < dataArray.length; i++) {
        const val = (dataArray[i] - 128) / 128;
        const absVal = Math.abs(val);
        sum += val * val;
        if (absVal > peak) peak = absVal;
      }
      const rms = Math.sqrt(sum / dataArray.length);
      
      if (this.onLevelUpdate) {
        this.onLevelUpdate({ rms, peak, clipping: peak > 0.95 });
      }
      
      this.levelAnimationId = requestAnimationFrame(updateLevel);
    };
    
    updateLevel();
  }

  setInputLevel(level) {
    this.inputLevel = Math.max(0, Math.min(2, level));
    if (this.recordingGain) {
      this.recordingGain.gain.setTargetAtTime(this.inputLevel, this.ctx.currentTime, 0.02);
    }
  }

  setMonitorEnabled(enabled) {
    this.monitorEnabled = enabled;
    if (this.monitorGain) {
      this.monitorGain.gain.setTargetAtTime(
        enabled ? 0.7 : 0,
        this.ctx.currentTime,
        0.05
      );
    }
  }

  async startRecording(startOffset = 0) {
    if (!this.hasPermission || this.isRecording) return false;
    
    this.recordedChunks = [];
    this.recordingOffset = startOffset;
    this.recordingStartTime = this.ctx.currentTime;
    
    const dest = this.ctx.createMediaStreamDestination();
    this.recordingGain.connect(dest);
    
    this.mediaRecorder = new MediaRecorder(dest.stream, {
      mimeType: 'audio/webm;codecs=opus'
    });
    
    this.mediaRecorder.ondataavailable = (e) => {
      if (e.data.size > 0) {
        this.recordedChunks.push(e.data);
      }
    };
    
    this.mediaRecorder.onstop = async () => {
      await this.processRecording();
    };
    
    this.mediaRecorder.start(100);
    this.isRecording = true;
    
    if (this.pitchDetector) {
      this.pitchDetector.start();
    }
    
    return true;
  }

  pauseRecording() {
    if (!this.isRecording || this.isPaused) return;
    
    if (this.mediaRecorder && this.mediaRecorder.state === 'recording') {
      this.mediaRecorder.pause();
    }
    this.isPaused = true;
  }

  resumeRecording() {
    if (!this.isRecording || !this.isPaused) return;
    
    if (this.mediaRecorder && this.mediaRecorder.state === 'paused') {
      this.mediaRecorder.resume();
    }
    this.isPaused = false;
  }

  stopRecording() {
    if (!this.isRecording) return null;
    
    this.isRecording = false;
    this.isPaused = false;
    
    if (this.pitchDetector) {
      this.pitchDetector.stop();
    }
    
    if (this.mediaRecorder && this.mediaRecorder.state !== 'inactive') {
      this.mediaRecorder.stop();
    }
    
    return {
      duration: this.ctx.currentTime - this.recordingStartTime,
      offset: this.recordingOffset
    };
  }

  async processRecording() {
    if (this.recordedChunks.length === 0) return;
    
    const blob = new Blob(this.recordedChunks, { type: 'audio/webm' });
    
    try {
      const arrayBuffer = await blob.arrayBuffer();
      this.recordedBuffer = await this.ctx.decodeAudioData(arrayBuffer);
      
      if (this.onRecordingComplete) {
        this.onRecordingComplete({
          buffer: this.recordedBuffer,
          offset: this.recordingOffset,
          duration: this.recordedBuffer.duration,
          blob: blob
        });
      }
    } catch (err) {
      console.error('Error processing recording:', err);
    }
  }

  getRecordedBuffer() {
    return this.recordedBuffer;
  }

  getRecordingPeaks(targetBins = 1200) {
    if (!this.recordedBuffer) return null;
    
    const buffer = this.recordedBuffer;
    const channelData = buffer.getChannelData(0);
    const length = buffer.length;
    const blockSize = Math.floor(length / targetBins);
    const peaks = new Float32Array(targetBins * 2);
    
    for (let bin = 0; bin < targetBins; bin++) {
      let min = 1.0;
      let max = -1.0;
      const start = bin * blockSize;
      const end = Math.min(start + blockSize, length);
      
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

  clearRecording() {
    this.recordedChunks = [];
    this.recordedBuffer = null;
    this.recordingOffset = 0;
  }

  async downloadRecording(filename = 'my-vocals.wav') {
    if (!this.recordedBuffer) return false;
    
    const wavBlob = this.bufferToWav(this.recordedBuffer);
    const url = URL.createObjectURL(wavBlob);
    const a = document.createElement('a');
    a.href = url;
    a.download = filename;
    a.click();
    URL.revokeObjectURL(url);
    
    return true;
  }

  bufferToWav(buffer) {
    const numChannels = buffer.numberOfChannels;
    const sampleRate = buffer.sampleRate;
    const format = 1;
    const bitDepth = 16;
    const bytesPerSample = bitDepth / 8;
    const blockAlign = numChannels * bytesPerSample;
    const dataLength = buffer.length * blockAlign;
    const bufferLength = 44 + dataLength;
    
    const arrayBuffer = new ArrayBuffer(bufferLength);
    const view = new DataView(arrayBuffer);
    
    const writeString = (offset, str) => {
      for (let i = 0; i < str.length; i++) {
        view.setUint8(offset + i, str.charCodeAt(i));
      }
    };
    
    writeString(0, 'RIFF');
    view.setUint32(4, 36 + dataLength, true);
    writeString(8, 'WAVE');
    writeString(12, 'fmt ');
    view.setUint32(16, 16, true);
    view.setUint16(20, format, true);
    view.setUint16(22, numChannels, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * blockAlign, true);
    view.setUint16(32, blockAlign, true);
    view.setUint16(34, bitDepth, true);
    writeString(36, 'data');
    view.setUint32(40, dataLength, true);
    
    const left = buffer.getChannelData(0);
    const right = numChannels > 1 ? buffer.getChannelData(1) : left;
    
    let offset = 44;
    for (let i = 0; i < buffer.length; i++) {
      let sL = Math.max(-1, Math.min(1, left[i]));
      view.setInt16(offset, sL < 0 ? sL * 0x8000 : sL * 0x7FFF, true);
      offset += 2;
      
      if (numChannels > 1) {
        let sR = Math.max(-1, Math.min(1, right[i]));
        view.setInt16(offset, sR < 0 ? sR * 0x8000 : sR * 0x7FFF, true);
        offset += 2;
      }
    }
    
    return new Blob([view], { type: 'audio/wav' });
  }

  destroy() {
    this.stopRecording();
    
    if (this.levelAnimationId) {
      cancelAnimationFrame(this.levelAnimationId);
    }
    
    if (this.pitchDetector) {
      this.pitchDetector.stop();
    }
    
    if (this.mediaStream) {
      this.mediaStream.getTracks().forEach(track => track.stop());
    }
    
    this.mediaStreamSource = null;
    this.recordingGain = null;
    this.monitorGain = null;
    this.analyser = null;
    this.mediaStream = null;
  }
}

window.VocalRecorder = VocalRecorder;
