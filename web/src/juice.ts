/**
 * Juice kit: synthesized sound effects for rewarding in-game moments.
 *
 * No audio assets - everything is WebAudio oscillators and filtered noise,
 * so there's nothing to download and nothing that can 404. All volumes are
 * kept low and every sound is short; audio must never be the reason a game
 * feels annoying.
 *
 * iOS Safari only allows audio after a user gesture, so call `unlockAudio()`
 * on the first pointerdown (GameTable does this) and every playSound() is a
 * no-op until the context is running.
 */

let ctx: AudioContext | null = null;
let muted = false;
try {
  muted = window.localStorage.getItem('hr_sound_muted') === '1';
} catch {
  muted = false;
}

export function isMuted(): boolean {
  return muted;
}

export function setMuted(m: boolean): void {
  muted = m;
  try {
    window.localStorage.setItem('hr_sound_muted', m ? '1' : '0');
  } catch {
    /* storage unavailable - the toggle just won't persist */
  }
}

function ac(): AudioContext | null {
  if (typeof window === 'undefined') return null;
  if (!ctx) {
    const AC =
      window.AudioContext ??
      (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!AC) return null;
    ctx = new AC();
  }
  if (ctx.state === 'suspended') void ctx.resume();
  return ctx;
}

/** Prime the AudioContext from a user gesture (iOS requirement). */
export function unlockAudio(): void {
  ac();
}

interface ToneOpts {
  freq: number;
  freqEnd?: number;
  at: number;
  dur: number;
  type?: OscillatorType;
  vol?: number;
}

function tone(c: AudioContext, opts: ToneOpts): void {
  const osc = c.createOscillator();
  const gain = c.createGain();
  osc.type = opts.type ?? 'sine';
  const t0 = c.currentTime + opts.at;
  osc.frequency.setValueAtTime(Math.max(1, opts.freq), t0);
  if (opts.freqEnd !== undefined) {
    osc.frequency.exponentialRampToValueAtTime(Math.max(1, opts.freqEnd), t0 + opts.dur);
  }
  gain.gain.setValueAtTime(0.0001, t0);
  gain.gain.exponentialRampToValueAtTime(opts.vol ?? 0.1, t0 + 0.012);
  gain.gain.exponentialRampToValueAtTime(0.0001, t0 + opts.dur);
  osc.connect(gain);
  gain.connect(c.destination);
  osc.start(t0);
  osc.stop(t0 + opts.dur + 0.05);
}

interface NoiseOpts {
  at: number;
  dur: number;
  vol?: number;
  lowpass?: number;
  highpass?: number;
}

function noise(c: AudioContext, opts: NoiseOpts): void {
  const len = Math.max(1, Math.floor(c.sampleRate * opts.dur));
  const buf = c.createBuffer(1, len, c.sampleRate);
  const data = buf.getChannelData(0);
  for (let i = 0; i < len; i++) data[i] = Math.random() * 2 - 1;
  const src = c.createBufferSource();
  src.buffer = buf;
  const gain = c.createGain();
  const t0 = c.currentTime + opts.at;
  gain.gain.setValueAtTime(0.0001, t0);
  gain.gain.exponentialRampToValueAtTime(opts.vol ?? 0.12, t0 + 0.01);
  gain.gain.exponentialRampToValueAtTime(0.0001, t0 + opts.dur);
  let node: AudioNode = src;
  if (opts.lowpass !== undefined) {
    const f = c.createBiquadFilter();
    f.type = 'lowpass';
    f.frequency.value = opts.lowpass;
    node.connect(f);
    node = f;
  }
  if (opts.highpass !== undefined) {
    const f = c.createBiquadFilter();
    f.type = 'highpass';
    f.frequency.value = opts.highpass;
    node.connect(f);
    node = f;
  }
  node.connect(gain);
  gain.connect(c.destination);
  src.start(t0);
  src.stop(t0 + opts.dur + 0.05);
}

export type SoundName =
  | 'ally'
  | 'kill'
  | 'buy'
  | 'bigbuy'
  | 'damage'
  | 'combo'
  | 'win'
  | 'stun'
  | 'turn'
  | 'click';

/**
 * Haptic feedback for rewarding moments. navigator.vibrate exists on
 * Android Chrome and a few others; iOS Safari silently ignores it.
 * Always a safe no-op where unsupported - haptics must never break the game.
 */
export function buzz(pattern: number | number[]): void {
  try {
    if (typeof navigator !== 'undefined' && typeof navigator.vibrate === 'function') {
      navigator.vibrate(pattern);
    }
  } catch {
    /* haptics must never break the game */
  }
}

export function playSound(name: SoundName, opt?: { combo?: number }): void {
  if (muted) return;
  const c = ac();
  if (!c) return;
  try {
    switch (name) {
      case 'ally': // the dopamine zap
        tone(c, { freq: 920, freqEnd: 180, at: 0, dur: 0.14, type: 'square', vol: 0.06 });
        tone(c, { freq: 1380, at: 0.02, dur: 0.1, type: 'sine', vol: 0.07 });
        break;
      case 'kill': // heavy boom for a destroyed champion
        noise(c, { at: 0, dur: 0.35, vol: 0.18, lowpass: 500 });
        tone(c, { freq: 120, freqEnd: 38, at: 0, dur: 0.35, type: 'sine', vol: 0.16 });
        break;
      case 'buy': // small coin
        tone(c, { freq: 1318, at: 0, dur: 0.09, type: 'triangle', vol: 0.09 });
        tone(c, { freq: 1760, at: 0.07, dur: 0.12, type: 'triangle', vol: 0.09 });
        break;
      case 'bigbuy': // rising coin arpeggio for 5+ cost cards
        [523, 659, 784, 1046].forEach((f, i) =>
          tone(c, { freq: f, at: i * 0.08, dur: 0.16, type: 'triangle', vol: 0.1 }),
        );
        break;
      case 'damage': // face hit thud
        tone(c, { freq: 160, freqEnd: 70, at: 0, dur: 0.16, type: 'sine', vol: 0.14 });
        noise(c, { at: 0, dur: 0.08, vol: 0.07, lowpass: 1200 });
        break;
      case 'combo': { // rising arp, taller with the combo count
        const n = Math.min(Math.max(opt?.combo ?? 2, 2), 6);
        for (let i = 0; i < n; i++) {
          tone(c, { freq: 520 * Math.pow(1.25, i), at: i * 0.06, dur: 0.12, type: 'square', vol: 0.05 });
        }
        break;
      }
      case 'stun': // crackle + drop for a stun landing
        noise(c, { at: 0, dur: 0.12, vol: 0.09, highpass: 2500 });
        tone(c, { freq: 700, freqEnd: 140, at: 0, dur: 0.18, type: 'sawtooth', vol: 0.05 });
        break;
      case 'win': // little fanfare
        [523, 659, 784, 1046, 784, 1046].forEach((f, i) =>
          tone(c, { freq: f, at: i * 0.11, dur: 0.2, type: 'triangle', vol: 0.11 }),
        );
        break;
      case 'turn': // soft whoosh when your turn starts
        noise(c, { at: 0, dur: 0.18, vol: 0.035, highpass: 800 });
        tone(c, { freq: 440, freqEnd: 660, at: 0, dur: 0.14, type: 'sine', vol: 0.045 });
        break;
      case 'click':
        tone(c, { freq: 800, at: 0, dur: 0.04, type: 'sine', vol: 0.045 });
        break;
    }
  } catch {
    /* audio must never break the game */
  }
}
