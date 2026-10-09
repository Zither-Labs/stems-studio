/**
 * Stems Studio - Offline Mixdown & Stem Export Engine
 * High-quality multi-track rendering to WAV files with 1-click download.
 */

class ExportEngine {
  /**
   * Render mixdown to WAV Blob using OfflineAudioContext
   */
  static async renderMix(tracksMap, duration, options = {}) {
    // options: { mode: 'full' | 'karaoke' | 'acapella' | 'single', singleTrackId, loopOnly, loopStart, loopEnd }
    const sampleRate = 44100;
    const isLoopOnly = options.loopOnly && options.loopEnd > options.loopStart;
    const startOffset = isLoopOnly ? options.loopStart : 0;
    const renderDuration = isLoopOnly ? (options.loopEnd - options.loopStart) : duration;

    if (renderDuration <= 0) {
      throw new Error("Invalid render duration");
    }

    const offlineCtx = new OfflineAudioContext(2, Math.ceil(sampleRate * renderDuration), sampleRate);

    // Filter tracks based on export mode
    const tracksToRender = [];
    const anySolo = Array.from(tracksMap.values()).some(t => t.isSoloed);

    for (const track of tracksMap.values()) {
      if (!track.buffer) continue;

      let shouldInclude = true;

      if (options.mode === 'single') {
        shouldInclude = track.id === options.singleTrackId;
      } else if (options.mode === 'karaoke') {
        shouldInclude = track.stemType !== 'vocal' && !track.isMuted;
      } else if (options.mode === 'acapella') {
        shouldInclude = track.stemType === 'vocal';
      } else {
        // Full mix mode follows studio mute/solo states
        if (anySolo) {
          shouldInclude = track.isSoloed && !track.isMuted;
        } else {
          shouldInclude = !track.isMuted;
        }
      }

      if (shouldInclude) {
        tracksToRender.push(track);
      }
    }

    // Set up nodes inside offline context
    for (const track of tracksToRender) {
      const source = offlineCtx.createBufferSource();
      source.buffer = track.buffer;

      const panner = offlineCtx.createStereoPanner();
      panner.pan.value = track.pan;

      const gain = offlineCtx.createGain();
      gain.gain.value = track.volume;

      // 3-Band EQ matching track settings
      const eqLow = offlineCtx.createBiquadFilter();
      eqLow.type = 'lowshelf';
      eqLow.frequency.value = 320;
      eqLow.gain.value = track.nodes.eqLow.gain.value;

      const eqMid = offlineCtx.createBiquadFilter();
      eqMid.type = 'peaking';
      eqMid.frequency.value = 1000;
      eqMid.gain.value = track.nodes.eqMid.gain.value;

      const eqHigh = offlineCtx.createBiquadFilter();
      eqHigh.type = 'highshelf';
      eqHigh.frequency.value = 3200;
      eqHigh.gain.value = track.nodes.eqHigh.gain.value;

      source.connect(eqLow);
      eqLow.connect(eqMid);
      eqMid.connect(eqHigh);
      eqHigh.connect(panner);
      panner.connect(gain);
      gain.connect(offlineCtx.destination);

      source.start(0, startOffset);
    }

    const renderedBuffer = await offlineCtx.startRendering();
    const wavBlob = this.bufferToWavBlob(renderedBuffer);
    return wavBlob;
  }

  /**
   * Convert AudioBuffer to 16-bit Stereo PCM WAV Blob
   */
  static bufferToWavBlob(buffer) {
    const numChannels = buffer.numberOfChannels;
    const sampleRate = buffer.sampleRate;
    const format = 1; // PCM
    const bitDepth = 16;
    const bytesPerSample = bitDepth / 8;
    const blockAlign = numChannels * bytesPerSample;

    const dataLength = buffer.length * blockAlign;
    const bufferLength = 44 + dataLength;

    const arrayBuffer = new ArrayBuffer(bufferLength);
    const view = new DataView(arrayBuffer);

    // RIFF identifier
    this.writeString(view, 0, 'RIFF');
    view.setUint32(4, 36 + dataLength, true);
    this.writeString(view, 8, 'WAVE');

    // fmt sub-chunk
    this.writeString(view, 12, 'fmt ');
    view.setUint32(16, 16, true); // Subchunk1Size (16 for PCM)
    view.setUint16(20, format, true); // AudioFormat
    view.setUint16(22, numChannels, true);
    view.setUint32(24, sampleRate, true);
    view.setUint32(28, sampleRate * blockAlign, true); // ByteRate
    view.setUint16(32, blockAlign, true);
    view.setUint16(34, bitDepth, true);

    // data sub-chunk
    this.writeString(view, 36, 'data');
    view.setUint32(40, dataLength, true);

    // Interleave left and right channels
    const left = buffer.getChannelData(0);
    const right = numChannels > 1 ? buffer.getChannelData(1) : left;

    let offset = 44;
    for (let i = 0; i < buffer.length; i++) {
      // Left channel sample
      let sL = Math.max(-1, Math.min(1, left[i]));
      view.setInt16(offset, sL < 0 ? sL * 0x8000 : sL * 0x7FFF, true);
      offset += 2;

      // Right channel sample
      let sR = Math.max(-1, Math.min(1, right[i]));
      view.setInt16(offset, sR < 0 ? sR * 0x8000 : sR * 0x7FFF, true);
      offset += 2;
    }

    return new Blob([view], { type: 'audio/wav' });
  }

  static writeString(view, offset, string) {
    for (let i = 0; i < string.length; i++) {
      view.setUint8(offset + i, string.charCodeAt(i));
    }
  }

  /**
   * Helper to trigger download in browser
   */
  static triggerDownload(blob, filename) {
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.style.display = 'none';
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    setTimeout(() => {
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    }, 1000);
  }
}

window.ExportEngine = ExportEngine;
