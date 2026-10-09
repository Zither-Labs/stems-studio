/**
 * Stems Studio - High-DPI Waveform Renderer
 * Renders beautiful gradient peak & RMS waveforms, playheads, and loop overlays.
 */

class WaveformRenderer {
  static STEM_COLORS = {
    vocal: {
      gradientTop: '#ff4d6d',
      gradientBottom: '#a81d37',
      glow: 'rgba(255, 77, 109, 0.4)',
      playedOverlay: 'rgba(255, 77, 109, 0.15)'
    },
    drums: {
      gradientTop: '#fbbf24',
      gradientBottom: '#b45309',
      glow: 'rgba(251, 191, 36, 0.4)',
      playedOverlay: 'rgba(251, 191, 36, 0.15)'
    },
    bass: {
      gradientTop: '#c084fc',
      gradientBottom: '#7e22ce',
      glow: 'rgba(192, 132, 252, 0.4)',
      playedOverlay: 'rgba(192, 132, 252, 0.15)'
    },
    guitar: {
      gradientTop: '#34d399',
      gradientBottom: '#059669',
      glow: 'rgba(52, 211, 153, 0.4)',
      playedOverlay: 'rgba(52, 211, 153, 0.15)'
    },
    piano: {
      gradientTop: '#f472b6',
      gradientBottom: '#db2777',
      glow: 'rgba(244, 114, 182, 0.4)',
      playedOverlay: 'rgba(244, 114, 182, 0.15)'
    },
    other: {
      gradientTop: '#38bdf8',
      gradientBottom: '#0369a1',
      glow: 'rgba(56, 189, 248, 0.4)',
      playedOverlay: 'rgba(56, 189, 248, 0.15)'
    },
    custom: {
      gradientTop: '#818cf8',
      gradientBottom: '#4338ca',
      glow: 'rgba(129, 140, 248, 0.4)',
      playedOverlay: 'rgba(129, 140, 248, 0.15)'
    }
  };

  /**
   * Render peaks data to a canvas
   */
  static renderTrackWaveform(canvas, peaks, stemType = 'custom', progress = 0, loop = null) {
    if (!canvas || !peaks) return;

    const ctx = canvas.getContext('2d');
    const dpr = window.devicePixelRatio || 1;
    const width = canvas.clientWidth;
    const height = canvas.clientHeight;

    // Handle high DPI
    if (canvas.width !== width * dpr || canvas.height !== height * dpr) {
      canvas.width = width * dpr;
      canvas.height = height * dpr;
    }

    ctx.save();
    ctx.scale(dpr, dpr);
    ctx.clearRect(0, 0, width, height);

    const colors = this.STEM_COLORS[stemType] || this.STEM_COLORS.custom;
    const halfH = height / 2;
    const numBins = peaks.length / 2;
    const binWidth = width / numBins;

    // Background subtle grid line
    ctx.strokeStyle = 'rgba(255, 255, 255, 0.04)';
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(0, halfH);
    ctx.lineTo(width, halfH);
    ctx.stroke();

    // Loop region highlight
    if (loop && loop.enabled && loop.end > loop.start) {
      const loopX = loop.start * width;
      const loopW = (loop.end - loop.start) * width;
      ctx.fillStyle = 'rgba(56, 189, 248, 0.08)';
      ctx.fillRect(loopX, 0, loopW, height);

      ctx.strokeStyle = 'rgba(56, 189, 248, 0.4)';
      ctx.setLineDash([4, 4]);
      ctx.strokeRect(loopX, 0, loopW, height);
      ctx.setLineDash([]);
    }

    // Gradient fill for waveform peaks
    const grad = ctx.createLinearGradient(0, 0, 0, height);
    grad.addColorStop(0, colors.gradientTop);
    grad.addColorStop(0.5, '#ffffff');
    grad.addColorStop(1, colors.gradientBottom);

    const playedGrad = ctx.createLinearGradient(0, 0, 0, height);
    playedGrad.addColorStop(0, '#ffffff');
    playedGrad.addColorStop(1, colors.gradientTop);

    const currentX = progress * width;

    // Draw waveform peaks
    for (let i = 0; i < numBins; i++) {
      const x = i * binWidth;
      const min = peaks[i * 2];
      const max = peaks[i * 2 + 1];

      // Dynamic peak height scaling
      const topY = halfH - Math.max(2, Math.abs(max) * (halfH - 4));
      const bottomY = halfH + Math.max(2, Math.abs(min) * (halfH - 4));
      const barH = bottomY - topY;

      ctx.fillStyle = x <= currentX ? playedGrad : grad;
      ctx.fillRect(x, topY, Math.max(1.2, binWidth - 0.5), barH);
    }

    // Played portion glow overlay
    if (currentX > 0) {
      ctx.fillStyle = colors.playedOverlay;
      ctx.fillRect(0, 0, currentX, height);
    }

    // Playhead vertical line
    if (currentX >= 0 && currentX <= width) {
      ctx.strokeStyle = '#ffffff';
      ctx.lineWidth = 2;
      ctx.shadowColor = colors.gradientTop;
      ctx.shadowBlur = 8;
      ctx.beginPath();
      ctx.moveTo(currentX, 0);
      ctx.lineTo(currentX, height);
      ctx.stroke();
    }

    ctx.restore();
  }
}

window.WaveformRenderer = WaveformRenderer;
