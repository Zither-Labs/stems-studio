/**
 * Stems Studio - Pitch Visualization Engine
 * Piano roll view, pitch graph, note timeline, and comparison overlays
 * Sangeet Yatra inspired design with glowing gradients
 */

class PitchVisualizer {
  constructor(options = {}) {
    this.canvas = options.canvas;
    this.ctx = this.canvas ? this.canvas.getContext('2d') : null;
    
    this.minMidi = options.minMidi || 48;  // C3
    this.maxMidi = options.maxMidi || 84;  // C6
    this.noteRange = this.maxMidi - this.minMidi;
    
    this.NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B'];
    this.A4_FREQ = 440;
    this.A4_MIDI = 69;
    
    this.originalPitchData = [];
    this.userPitchData = [];
    
    this.duration = 0;
    this.currentTime = 0;
    this.viewStartTime = 0;
    this.viewDuration = 10;
    
    this.animationFrameId = null;
    
    this.colors = {
      background: '#0a0c12',
      gridLine: 'rgba(255, 255, 255, 0.06)',
      gridLineAccent: 'rgba(255, 255, 255, 0.12)',
      noteLabel: 'rgba(255, 255, 255, 0.5)',
      playhead: '#ffffff',
      playheadGlow: 'rgba(99, 102, 241, 0.6)',
      
      originalPitch: {
        fill: 'rgba(255, 77, 109, 0.8)',
        stroke: '#ff4d6d',
        glow: 'rgba(255, 77, 109, 0.4)'
      },
      userPitch: {
        fill: 'rgba(56, 189, 248, 0.8)',
        stroke: '#38bdf8',
        glow: 'rgba(56, 189, 248, 0.4)'
      },
      
      targetNote: {
        fill: 'rgba(16, 185, 129, 0.15)',
        stroke: 'rgba(16, 185, 129, 0.6)'
      },
      
      blackKey: 'rgba(0, 0, 0, 0.3)',
      whiteKey: 'rgba(255, 255, 255, 0.03)'
    };
  }

  setCanvas(canvas) {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d');
    this.resize();
  }

  resize() {
    if (!this.canvas) return;
    
    const dpr = window.devicePixelRatio || 1;
    const rect = this.canvas.getBoundingClientRect();
    
    this.canvas.width = rect.width * dpr;
    this.canvas.height = rect.height * dpr;
    this.ctx.scale(dpr, dpr);
    
    this.width = rect.width;
    this.height = rect.height;
  }

  setOriginalPitchData(data) {
    this.originalPitchData = data;
    if (data.length > 0) {
      const lastPoint = data[data.length - 1];
      this.duration = lastPoint.time + 0.1;
    }
  }

  setUserPitchData(data) {
    this.userPitchData = data;
  }

  addUserPitchPoint(point) {
    this.userPitchData.push(point);
  }

  clearUserPitchData() {
    this.userPitchData = [];
  }

  setCurrentTime(time) {
    this.currentTime = time;
    
    const margin = this.viewDuration * 0.2;
    if (time > this.viewStartTime + this.viewDuration - margin) {
      this.viewStartTime = time - margin;
    } else if (time < this.viewStartTime + margin) {
      this.viewStartTime = Math.max(0, time - margin);
    }
  }

  setViewWindow(startTime, duration) {
    this.viewStartTime = startTime;
    this.viewDuration = duration;
  }

  frequencyToMidi(frequency) {
    if (!frequency || frequency <= 0) return null;
    return 12 * Math.log2(frequency / this.A4_FREQ) + this.A4_MIDI;
  }

  midiToY(midi) {
    const normalizedMidi = (midi - this.minMidi) / this.noteRange;
    return this.height - (normalizedMidi * this.height);
  }

  timeToX(time) {
    return ((time - this.viewStartTime) / this.viewDuration) * this.width;
  }

  render() {
    if (!this.ctx) return;
    
    this.ctx.clearRect(0, 0, this.width, this.height);
    
    this.drawBackground();
    this.drawPianoKeys();
    this.drawGrid();
    this.drawPitchCurve(this.originalPitchData, this.colors.originalPitch);
    this.drawPitchCurve(this.userPitchData, this.colors.userPitch);
    this.drawPlayhead();
    this.drawNoteLabels();
  }

  drawBackground() {
    const gradient = this.ctx.createLinearGradient(0, 0, 0, this.height);
    gradient.addColorStop(0, '#0d1017');
    gradient.addColorStop(0.5, '#090b10');
    gradient.addColorStop(1, '#0d1017');
    
    this.ctx.fillStyle = gradient;
    this.ctx.fillRect(0, 0, this.width, this.height);
  }

  drawPianoKeys() {
    const keyHeight = this.height / this.noteRange;
    
    for (let midi = this.minMidi; midi <= this.maxMidi; midi++) {
      const noteIndex = midi % 12;
      const isBlackKey = [1, 3, 6, 8, 10].includes(noteIndex);
      
      const y = this.midiToY(midi + 0.5);
      
      this.ctx.fillStyle = isBlackKey ? this.colors.blackKey : this.colors.whiteKey;
      this.ctx.fillRect(0, y, this.width, keyHeight);
    }
  }

  drawGrid() {
    const keyHeight = this.height / this.noteRange;
    
    for (let midi = this.minMidi; midi <= this.maxMidi; midi++) {
      const noteIndex = midi % 12;
      const isC = noteIndex === 0;
      
      const y = this.midiToY(midi);
      
      this.ctx.strokeStyle = isC ? this.colors.gridLineAccent : this.colors.gridLine;
      this.ctx.lineWidth = isC ? 1.5 : 0.5;
      this.ctx.beginPath();
      this.ctx.moveTo(0, y);
      this.ctx.lineTo(this.width, y);
      this.ctx.stroke();
    }
    
    const secondsPerLine = this.viewDuration > 20 ? 5 : (this.viewDuration > 10 ? 2 : 1);
    const startSecond = Math.floor(this.viewStartTime / secondsPerLine) * secondsPerLine;
    
    for (let t = startSecond; t <= this.viewStartTime + this.viewDuration; t += secondsPerLine) {
      const x = this.timeToX(t);
      
      this.ctx.strokeStyle = this.colors.gridLine;
      this.ctx.lineWidth = 0.5;
      this.ctx.beginPath();
      this.ctx.moveTo(x, 0);
      this.ctx.lineTo(x, this.height);
      this.ctx.stroke();
      
      this.ctx.fillStyle = this.colors.noteLabel;
      this.ctx.font = '10px "JetBrains Mono", monospace';
      this.ctx.textAlign = 'center';
      this.ctx.fillText(`${t.toFixed(1)}s`, x, this.height - 4);
    }
  }

  drawPitchCurve(pitchData, colors) {
    if (!pitchData || pitchData.length < 2) return;
    
    const validPoints = pitchData.filter(p => {
      if (!p.frequency) return false;
      const midi = this.frequencyToMidi(p.frequency);
      return midi >= this.minMidi && midi <= this.maxMidi;
    });
    
    if (validPoints.length < 2) return;
    
    this.ctx.save();
    this.ctx.shadowColor = colors.glow;
    this.ctx.shadowBlur = 12;
    
    this.ctx.strokeStyle = colors.stroke;
    this.ctx.lineWidth = 3;
    this.ctx.lineCap = 'round';
    this.ctx.lineJoin = 'round';
    
    this.ctx.beginPath();
    let started = false;
    let lastX = 0;
    let lastY = 0;
    
    for (let i = 0; i < validPoints.length; i++) {
      const point = validPoints[i];
      const x = this.timeToX(point.time);
      const midi = this.frequencyToMidi(point.frequency);
      const y = this.midiToY(midi);
      
      if (x < -50 || x > this.width + 50) continue;
      
      if (!started) {
        this.ctx.moveTo(x, y);
        started = true;
      } else {
        if (Math.abs(x - lastX) > 50) {
          this.ctx.moveTo(x, y);
        } else {
          this.ctx.lineTo(x, y);
        }
      }
      
      lastX = x;
      lastY = y;
    }
    
    this.ctx.stroke();
    this.ctx.restore();
    
    const noteRadius = 4;
    for (let i = 0; i < validPoints.length; i += 3) {
      const point = validPoints[i];
      const x = this.timeToX(point.time);
      const midi = this.frequencyToMidi(point.frequency);
      const y = this.midiToY(midi);
      
      if (x < 0 || x > this.width) continue;
      
      this.ctx.beginPath();
      this.ctx.arc(x, y, noteRadius, 0, Math.PI * 2);
      this.ctx.fillStyle = colors.fill;
      this.ctx.fill();
    }
  }

  drawPlayhead() {
    const x = this.timeToX(this.currentTime);
    
    if (x < 0 || x > this.width) return;
    
    this.ctx.save();
    this.ctx.shadowColor = this.colors.playheadGlow;
    this.ctx.shadowBlur = 15;
    
    this.ctx.strokeStyle = this.colors.playhead;
    this.ctx.lineWidth = 2;
    this.ctx.beginPath();
    this.ctx.moveTo(x, 0);
    this.ctx.lineTo(x, this.height);
    this.ctx.stroke();
    
    this.ctx.fillStyle = this.colors.playhead;
    this.ctx.beginPath();
    this.ctx.moveTo(x, 0);
    this.ctx.lineTo(x - 6, -10);
    this.ctx.lineTo(x + 6, -10);
    this.ctx.closePath();
    this.ctx.fill();
    
    this.ctx.restore();
  }

  drawNoteLabels() {
    const labelWidth = 40;
    
    this.ctx.fillStyle = 'rgba(13, 16, 23, 0.9)';
    this.ctx.fillRect(0, 0, labelWidth, this.height);
    
    this.ctx.strokeStyle = this.colors.gridLineAccent;
    this.ctx.lineWidth = 1;
    this.ctx.beginPath();
    this.ctx.moveTo(labelWidth, 0);
    this.ctx.lineTo(labelWidth, this.height);
    this.ctx.stroke();
    
    for (let midi = this.minMidi; midi <= this.maxMidi; midi++) {
      const noteIndex = midi % 12;
      const octave = Math.floor(midi / 12) - 1;
      const noteName = this.NOTE_NAMES[noteIndex];
      const isC = noteIndex === 0;
      
      const y = this.midiToY(midi);
      
      this.ctx.fillStyle = isC ? '#ffffff' : this.colors.noteLabel;
      this.ctx.font = isC ? 'bold 11px "Inter", sans-serif' : '10px "Inter", sans-serif';
      this.ctx.textAlign = 'center';
      this.ctx.textBaseline = 'middle';
      
      const label = noteName.includes('#') ? noteName : `${noteName}${octave}`;
      this.ctx.fillText(label, labelWidth / 2, y);
    }
  }

  startAnimation(getTimeCallback) {
    const animate = () => {
      const currentTime = getTimeCallback();
      this.setCurrentTime(currentTime);
      this.render();
      this.animationFrameId = requestAnimationFrame(animate);
    };
    
    animate();
  }

  stopAnimation() {
    if (this.animationFrameId) {
      cancelAnimationFrame(this.animationFrameId);
      this.animationFrameId = null;
    }
  }

  static renderNoteDisplay(canvas, noteInfo, options = {}) {
    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;
    
    if (canvas.width !== width * dpr || canvas.height !== height * dpr) {
      canvas.width = width * dpr;
      canvas.height = height * dpr;
    }
    
    ctx.save();
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, height);
    
    const gradient = ctx.createRadialGradient(
      width / 2, height / 2, 0,
      width / 2, height / 2, width / 2
    );
    gradient.addColorStop(0, 'rgba(99, 102, 241, 0.15)');
    gradient.addColorStop(1, 'rgba(9, 11, 16, 0.95)');
    ctx.fillStyle = gradient;
    ctx.fillRect(0, 0, width, height);
    
    if (!noteInfo || noteInfo.isSilent || !noteInfo.note) {
      ctx.fillStyle = 'rgba(255, 255, 255, 0.3)';
      ctx.font = 'bold 48px "Outfit", sans-serif';
      ctx.textAlign = 'center';
      ctx.textBaseline = 'middle';
      ctx.fillText('—', width / 2, height / 2 - 10);
      
      ctx.fillStyle = 'rgba(255, 255, 255, 0.4)';
      ctx.font = '14px "Inter", sans-serif';
      ctx.fillText('Waiting for voice...', width / 2, height / 2 + 35);
      
      ctx.restore();
      return;
    }
    
    const { note, octave, cents, frequency, confidence } = noteInfo;
    
    let noteColor = '#10b981';
    if (Math.abs(cents) > 30) {
      noteColor = '#ef4444';
    } else if (Math.abs(cents) > 15) {
      noteColor = '#f59e0b';
    }
    
    ctx.save();
    ctx.shadowColor = noteColor;
    ctx.shadowBlur = 20;
    
    ctx.fillStyle = noteColor;
    ctx.font = 'bold 64px "Outfit", sans-serif';
    ctx.textAlign = 'center';
    ctx.textBaseline = 'middle';
    ctx.fillText(note, width / 2 - 20, height / 2 - 5);
    
    ctx.fillStyle = 'rgba(255, 255, 255, 0.7)';
    ctx.font = 'bold 28px "Outfit", sans-serif';
    ctx.textAlign = 'left';
    ctx.fillText(octave, width / 2 + 25, height / 2 - 15);
    
    ctx.restore();
    
    const centsText = cents >= 0 ? `+${cents}` : `${cents}`;
    ctx.fillStyle = noteColor;
    ctx.font = '600 18px "JetBrains Mono", monospace';
    ctx.textAlign = 'center';
    ctx.fillText(`${centsText}¢`, width / 2, height / 2 + 40);
    
    if (frequency) {
      ctx.fillStyle = 'rgba(255, 255, 255, 0.4)';
      ctx.font = '12px "JetBrains Mono", monospace';
      ctx.fillText(`${frequency.toFixed(1)} Hz`, width / 2, height / 2 + 60);
    }
    
    const meterWidth = 120;
    const meterHeight = 8;
    const meterX = (width - meterWidth) / 2;
    const meterY = height - 30;
    
    ctx.fillStyle = 'rgba(255, 255, 255, 0.1)';
    ctx.fillRect(meterX, meterY, meterWidth, meterHeight);
    
    ctx.fillStyle = 'rgba(255, 255, 255, 0.3)';
    ctx.fillRect(meterX + meterWidth / 2 - 1, meterY - 2, 2, meterHeight + 4);
    
    const centsOffset = Math.max(-50, Math.min(50, cents));
    const indicatorX = meterX + meterWidth / 2 + (centsOffset / 50) * (meterWidth / 2);
    
    ctx.fillStyle = noteColor;
    ctx.beginPath();
    ctx.arc(indicatorX, meterY + meterHeight / 2, 5, 0, Math.PI * 2);
    ctx.fill();
    
    ctx.restore();
  }
}

window.PitchVisualizer = PitchVisualizer;
