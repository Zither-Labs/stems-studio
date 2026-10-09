/**
 * Stems Studio - High-Fidelity Procedural Multi-Track Stem Generator
 * Generates 4 synchronized, groovy stems (Vocals, Drums, Bass, Chords)
 * using Web Audio synthesis so the user can test the app immediately!
 */

class DemoStemGenerator {
  /**
   * Generates 4 AudioBuffers: Vocals, Drums, Bass, Other
   * Total length: 16.0 seconds (8 bars at 120 BPM in C Minor / Eb Major)
   */
  static async generateDemoStems(audioCtx) {
    const sampleRate = 44100;
    const duration = 16.0; // 8 bars @ 120 BPM
    const bpm = 120;
    const beatSec = 60 / bpm; // 0.5s per beat, 2.0s per bar

    // Render each stem in its own OfflineAudioContext
    const renderStem = async (generatorFn) => {
      const offlineCtx = new OfflineAudioContext(2, sampleRate * duration, sampleRate);
      generatorFn(offlineCtx, bpm, beatSec, duration);
      return await offlineCtx.startRendering();
    };

    const drumsBuffer = await renderStem(this.generateDrums);
    const bassBuffer = await renderStem(this.generateBass);
    const otherBuffer = await renderStem(this.generateChords);
    const vocalBuffer = await renderStem(this.generateVocals);

    return {
      vocal: vocalBuffer,
      drums: drumsBuffer,
      bass: bassBuffer,
      other: otherBuffer
    };
  }

  /**
   * Drums: Punchy Kick, Snappy Snare, Hi-Hats & Percussion
   */
  static generateDrums(ctx, bpm, beatSec, totalDuration) {
    const totalBars = Math.floor(totalDuration / (beatSec * 4));

    // Synthesize kick drum
    const playKick = (time) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'sine';
      osc.frequency.setValueAtTime(140, time);
      osc.frequency.exponentialRampToValueAtTime(36, time + 0.12);

      gain.gain.setValueAtTime(1.0, time);
      gain.gain.exponentialRampToValueAtTime(0.001, time + 0.32);

      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(time);
      osc.stop(time + 0.35);
    };

    // Synthesize snare drum
    const playSnare = (time) => {
      // Noise burst
      const bufferSize = ctx.sampleRate * 0.2;
      const noiseBuffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
      const output = noiseBuffer.getChannelData(0);
      for (let i = 0; i < bufferSize; i++) {
        output[i] = Math.random() * 2 - 1;
      }
      const whiteNoise = ctx.createBufferSource();
      whiteNoise.buffer = noiseBuffer;

      const filter = ctx.createBiquadFilter();
      filter.type = 'highpass';
      filter.frequency.value = 800;

      const noiseGain = ctx.createGain();
      noiseGain.gain.setValueAtTime(0.65, time);
      noiseGain.gain.exponentialRampToValueAtTime(0.01, time + 0.18);

      whiteNoise.connect(filter);
      filter.connect(noiseGain);
      noiseGain.connect(ctx.destination);
      whiteNoise.start(time);
      whiteNoise.stop(time + 0.2);

      // Body tone
      const osc = ctx.createOscillator();
      const oscGain = ctx.createGain();
      osc.type = 'triangle';
      osc.frequency.setValueAtTime(200, time);
      osc.frequency.exponentialRampToValueAtTime(90, time + 0.1);
      oscGain.gain.setValueAtTime(0.5, time);
      oscGain.gain.exponentialRampToValueAtTime(0.01, time + 0.12);
      osc.connect(oscGain);
      oscGain.connect(ctx.destination);
      osc.start(time);
      osc.stop(time + 0.15);
    };

    // Synthesize Hi-Hat
    const playHat = (time, open = false) => {
      const bufferSize = ctx.sampleRate * (open ? 0.25 : 0.05);
      const noiseBuffer = ctx.createBuffer(1, bufferSize, ctx.sampleRate);
      const output = noiseBuffer.getChannelData(0);
      for (let i = 0; i < bufferSize; i++) output[i] = Math.random() * 2 - 1;

      const noise = ctx.createBufferSource();
      noise.buffer = noiseBuffer;

      const filter = ctx.createBiquadFilter();
      filter.type = 'highpass';
      filter.frequency.value = 6500;

      const gain = ctx.createGain();
      gain.gain.setValueAtTime(open ? 0.35 : 0.2, time);
      gain.gain.exponentialRampToValueAtTime(0.01, time + (open ? 0.22 : 0.04));

      noise.connect(filter);
      filter.connect(gain);
      gain.connect(ctx.destination);
      noise.start(time);
      noise.stop(time + (open ? 0.25 : 0.05));
    };

    // Loop beat through total duration
    for (let bar = 0; bar < totalBars; bar++) {
      const barStart = bar * beatSec * 4;
      // Kick on 1 and 3 (and upbeat of 3.5)
      playKick(barStart + beatSec * 0);
      playKick(barStart + beatSec * 2);
      playKick(barStart + beatSec * 2.75);

      // Snare on 2 and 4
      playSnare(barStart + beatSec * 1);
      playSnare(barStart + beatSec * 3);

      // 16th note hi-hat pattern
      for (let s = 0; s < 16; s++) {
        const hatTime = barStart + s * (beatSec / 4);
        const isOpen = s === 6 || s === 14;
        playHat(hatTime, isOpen);
      }
    }
  }

  /**
   * Bass: Punchy Deep Sub Bassline in C Minor (C - G - Ab - Bb)
   */
  static generateBass(ctx, bpm, beatSec, totalDuration) {
    const notes = [
      // Bar 1 & 2: C2
      { freq: 65.41, startBeat: 0, durBeats: 1.5 },
      { freq: 65.41, startBeat: 2, durBeats: 0.75 },
      { freq: 77.78, startBeat: 3, durBeats: 0.75 }, // Eb2
      { freq: 65.41, startBeat: 4, durBeats: 1.5 },
      { freq: 65.41, startBeat: 6, durBeats: 1.0 },
      // Bar 3 & 4: Ab1 -> Bb1
      { freq: 51.91, startBeat: 8, durBeats: 1.5 },  // Ab1
      { freq: 51.91, startBeat: 10, durBeats: 1.0 },
      { freq: 58.27, startBeat: 12, durBeats: 1.5 }, // Bb1
      { freq: 58.27, startBeat: 14, durBeats: 1.0 },
      // Bar 5 & 6: Repeat C2 with variation
      { freq: 65.41, startBeat: 16, durBeats: 1.5 },
      { freq: 65.41, startBeat: 18, durBeats: 0.75 },
      { freq: 98.00, startBeat: 19, durBeats: 0.75 }, // G2
      { freq: 65.41, startBeat: 20, durBeats: 1.5 },
      { freq: 65.41, startBeat: 22, durBeats: 1.0 },
      // Bar 7 & 8: Ab1 -> G1 turnaround
      { freq: 51.91, startBeat: 24, durBeats: 1.5 },
      { freq: 51.91, startBeat: 26, durBeats: 1.0 },
      { freq: 49.00, startBeat: 28, durBeats: 2.0 },  // G1
      { freq: 58.27, startBeat: 30.5, durBeats: 1.0 }
    ];

    notes.forEach(n => {
      const time = n.startBeat * beatSec;
      const dur = n.durBeats * beatSec;
      if (time >= totalDuration) return;

      const osc = ctx.createOscillator();
      const oscSub = ctx.createOscillator();
      const filter = ctx.createBiquadFilter();
      const gain = ctx.createGain();

      osc.type = 'sawtooth';
      oscSub.type = 'sine';
      osc.frequency.setValueAtTime(n.freq, time);
      oscSub.frequency.setValueAtTime(n.freq / 2, time); // Sub-octave

      filter.type = 'lowpass';
      filter.frequency.setValueAtTime(420, time);
      filter.frequency.exponentialRampToValueAtTime(140, time + dur * 0.8);
      filter.Q.value = 3.0;

      gain.gain.setValueAtTime(0.7, time);
      gain.gain.linearRampToValueAtTime(0.6, time + 0.05);
      gain.gain.exponentialRampToValueAtTime(0.001, time + dur);

      osc.connect(filter);
      oscSub.connect(filter);
      filter.connect(gain);
      gain.connect(ctx.destination);

      osc.start(time);
      oscSub.start(time);
      osc.stop(time + dur);
      oscSub.stop(time + dur);
    });
  }

  /**
   * Instruments / Chords: Warm Analog Synth Pads & Arpeggio (Cm - Eb - Ab - Bb)
   */
  static generateChords(ctx, bpm, beatSec, totalDuration) {
    const chordProgressions = [
      // Bar 1 & 2: Cm (C4, Eb4, G4)
      { start: 0, dur: 4 * beatSec, freqs: [261.63, 311.13, 392.00] },
      { start: 4 * beatSec, dur: 4 * beatSec, freqs: [261.63, 311.13, 392.00] },
      // Bar 3 & 4: Ab (Ab3, C4, Eb4) -> Bb (Bb3, D4, F4)
      { start: 8 * beatSec, dur: 4 * beatSec, freqs: [207.65, 261.63, 311.13] },
      { start: 12 * beatSec, dur: 4 * beatSec, freqs: [233.08, 293.66, 349.23] }
    ];

    chordProgressions.forEach(prog => {
      prog.freqs.forEach((freq, idx) => {
        const osc = ctx.createOscillator();
        const filter = ctx.createBiquadFilter();
        const gain = ctx.createGain();

        osc.type = 'sawtooth';
        osc.frequency.setValueAtTime(freq, prog.start);
        // Subtle detune for lush thickness
        osc.detune.setValueAtTime((idx - 1) * 7, prog.start);

        filter.type = 'lowpass';
        filter.frequency.setValueAtTime(1800, prog.start);
        filter.Q.value = 1.0;

        gain.gain.setValueAtTime(0.001, prog.start);
        gain.gain.linearRampToValueAtTime(0.18, prog.start + 0.3);
        gain.gain.exponentialRampToValueAtTime(0.001, prog.start + prog.dur);

        osc.connect(filter);
        filter.connect(gain);
        gain.connect(ctx.destination);

        osc.start(prog.start);
        osc.stop(prog.start + prog.dur);
      });
    });

    // Sparkly high arpeggio
    const arpNotes = [523.25, 622.25, 783.99, 932.33, 1046.50]; // C5, Eb5, G5, Bb5, C6
    const totalArps = Math.floor(totalDuration / (beatSec / 2));
    for (let i = 0; i < totalArps; i++) {
      const time = i * (beatSec / 2);
      const noteFreq = arpNotes[i % arpNotes.length];

      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = 'triangle';
      osc.frequency.setValueAtTime(noteFreq, time);

      gain.gain.setValueAtTime(0.08, time);
      gain.gain.exponentialRampToValueAtTime(0.001, time + 0.22);

      osc.connect(gain);
      gain.connect(ctx.destination);
      osc.start(time);
      osc.stop(time + 0.25);
    }
  }

  /**
   * Vocals / Lead: Expressive melodic lead with human-like vibrato & formant
   */
  static generateVocals(ctx, bpm, beatSec, totalDuration) {
    const melody = [
      // Phrase 1 (Bars 1-2)
      { freq: 392.00, startBeat: 0.5, durBeats: 1.0 }, // G4
      { freq: 466.16, startBeat: 1.5, durBeats: 1.0 }, // Bb4
      { freq: 523.25, startBeat: 2.5, durBeats: 2.0 }, // C5
      { freq: 466.16, startBeat: 5.0, durBeats: 1.0 }, // Bb4
      { freq: 392.00, startBeat: 6.0, durBeats: 1.5 }, // G4
      // Phrase 2 (Bars 3-4)
      { freq: 349.23, startBeat: 8.5, durBeats: 1.0 }, // F4
      { freq: 392.00, startBeat: 9.5, durBeats: 1.0 }, // G4
      { freq: 311.13, startBeat: 10.5, durBeats: 2.5 },// Eb4
      { freq: 349.23, startBeat: 13.5, durBeats: 2.0 },// F4
      // Phrase 3 (Bars 5-6)
      { freq: 523.25, startBeat: 16.5, durBeats: 1.5 },// C5
      { freq: 587.33, startBeat: 18.0, durBeats: 1.0 },// D5
      { freq: 622.25, startBeat: 19.0, durBeats: 2.5 },// Eb5
      { freq: 523.25, startBeat: 22.0, durBeats: 1.5 },// C5
      // Phrase 4 (Bars 7-8)
      { freq: 466.16, startBeat: 24.5, durBeats: 1.5 },// Bb4
      { freq: 392.00, startBeat: 26.0, durBeats: 1.5 },// G4
      { freq: 523.25, startBeat: 28.0, durBeats: 3.5 } // C5
    ];

    melody.forEach(m => {
      const time = m.startBeat * beatSec;
      const dur = m.durBeats * beatSec;
      if (time >= totalDuration) return;

      const osc = ctx.createOscillator();
      const vibrato = ctx.createOscillator();
      const vibratoGain = ctx.createGain();
      const formant1 = ctx.createBiquadFilter();
      const formant2 = ctx.createBiquadFilter();
      const gain = ctx.createGain();

      osc.type = 'sawtooth';
      osc.frequency.setValueAtTime(m.freq, time);

      // Human-like vibrato (5.5 Hz) kicks in slightly after attack
      vibrato.frequency.setValueAtTime(5.5, time);
      vibratoGain.gain.setValueAtTime(0, time);
      vibratoGain.gain.linearRampToValueAtTime(7, time + 0.35); // 7 Hz frequency wobble
      vibrato.connect(osc.frequency);

      // Vocal Formant filters (vocal vowel shape)
      formant1.type = 'bandpass';
      formant1.frequency.value = 850;
      formant1.Q.value = 4.0;

      formant2.type = 'bandpass';
      formant2.frequency.value = 2100;
      formant2.Q.value = 5.0;

      // Envelope
      gain.gain.setValueAtTime(0.001, time);
      gain.gain.linearRampToValueAtTime(0.35, time + 0.08);
      gain.gain.exponentialRampToValueAtTime(0.001, time + dur);

      osc.connect(formant1);
      osc.connect(formant2);
      formant1.connect(gain);
      formant2.connect(gain);
      gain.connect(ctx.destination);

      osc.start(time);
      vibrato.start(time);
      osc.stop(time + dur);
      vibrato.stop(time + dur);
    });
  }
}

window.DemoStemGenerator = DemoStemGenerator;
