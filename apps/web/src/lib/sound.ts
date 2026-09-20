/**
 * Club-on-ball sound, synthesized in the browser.
 *
 * The same recipe as the social shorts' `impact` effect (social/short-02/tools/make-sfx.sh): a very
 * short burst of high-passed noise for the click of the strike, plus three decaying sine partials
 * for the body of the "tock". Nothing is sampled or downloaded; a putt is the same shape, lower,
 * softer and shorter, because a putter face is duller than an iron.
 *
 * Browsers only allow audio after a user gesture, and every shot in this app follows one (a click
 * or a key press), so the context is created lazily on the first sound and resumed if suspended.
 */
import { useStore } from "../store";

const KEY = "flygolf.sound";

/** Sound is on unless this browser has been told otherwise. */
export function initialSound(): boolean {
  if (typeof window === "undefined") return false;
  try {
    return window.localStorage.getItem(KEY) !== "off";
  } catch {
    return true; // private mode / blocked storage: default to on, just don't remember it
  }
}

export function setSound(on: boolean) {
  const st = useStore.getState();
  if (st.sound !== on) st.set({ sound: on });
  try {
    window.localStorage.setItem(KEY, on ? "on" : "off");
  } catch {
    // Not remembering the choice is fine; it still applies to this page.
  }
  if (on) void ctx()?.resume();
}

export const toggleSound = () => setSound(!useStore.getState().sound);

/** Handles S for the sound toggle; returns true when it consumed the key. */
export function soundKey(e: KeyboardEvent): boolean {
  if (e.key === "s" || e.key === "S") {
    toggleSound();
    return true;
  }
  return false;
}

type Ctor = typeof AudioContext;
let audio: AudioContext | null = null;
let noise: AudioBuffer | null = null;

function ctx(): AudioContext | null {
  if (audio) return audio;
  if (typeof window === "undefined") return null;
  const C: Ctor | undefined =
    window.AudioContext ?? (window as unknown as { webkitAudioContext?: Ctor }).webkitAudioContext;
  if (!C) return null;
  try {
    audio = new C();
  } catch {
    return null; // no audio device, or the browser refused: stay silent rather than throw
  }
  return audio;
}

/** 30 ms of white noise, made once and reused for every strike. */
function noiseBuffer(ac: AudioContext): AudioBuffer {
  if (noise && noise.sampleRate === ac.sampleRate) return noise;
  const n = Math.floor(ac.sampleRate * 0.03);
  const buf = ac.createBuffer(1, n, ac.sampleRate);
  const d = buf.getChannelData(0);
  for (let i = 0; i < n; i++) d[i] = Math.random() * 2 - 1;
  noise = buf;
  return buf;
}

export interface ImpactOptions {
  /** A putt: duller, quieter, shorter. */
  putter?: boolean;
  /** Decoded swing power 0..1: louder and brighter the harder it is hit. */
  power?: number;
  /** Extra gain multiplier (0..1). */
  gain?: number;
}

/**
 * Play one club-on-ball strike. Silent (and free) when sound is off, when the browser has no audio,
 * or when the tab is hidden.
 */
export function playImpact(opts: ImpactOptions = {}) {
  if (!useStore.getState().sound) return;
  if (typeof document !== "undefined" && document.hidden) return;
  const ac = ctx();
  if (!ac) return;
  if (ac.state === "suspended") void ac.resume();

  const putter = !!opts.putter;
  const power = Math.min(1, Math.max(0, opts.power ?? 0.7));
  const t0 = ac.currentTime + 0.001;
  const level = (putter ? 0.16 : 0.3) * (0.55 + 0.45 * power) * (opts.gain ?? 1);

  const out = ac.createGain();
  out.gain.value = level;
  out.connect(ac.destination);

  // The click: high-passed noise, gone in a few tens of milliseconds.
  const click = ac.createBufferSource();
  click.buffer = noiseBuffer(ac);
  const hp = ac.createBiquadFilter();
  hp.type = "highpass";
  hp.frequency.value = putter ? 1200 : 2500;
  const clickGain = ac.createGain();
  clickGain.gain.setValueAtTime(putter ? 0.5 : 0.9, t0);
  clickGain.gain.exponentialRampToValueAtTime(0.0001, t0 + (putter ? 0.035 : 0.05));
  click.connect(hp).connect(clickGain).connect(out);
  click.start(t0);
  click.stop(t0 + 0.06);

  // The body: three partials, each decaying at its own rate (iron: 1480/2290/620 Hz).
  const partials: [number, number, number][] = putter
    ? // [frequency, level, decay]
      [
        [520, 0.5, 0.085],
        [880, 0.22, 0.05],
        [280, 0.3, 0.1],
      ]
    : [
        [1480 * (0.94 + 0.12 * power), 0.55, 0.11],
        [2290 * (0.94 + 0.12 * power), 0.22, 0.06],
        [620, 0.18, 0.08],
      ];
  for (const [freq, amp, decay] of partials) {
    const osc = ac.createOscillator();
    osc.type = "sine";
    osc.frequency.value = freq;
    const g = ac.createGain();
    g.gain.setValueAtTime(amp, t0);
    g.gain.exponentialRampToValueAtTime(0.0001, t0 + decay);
    osc.connect(g).connect(out);
    osc.start(t0);
    osc.stop(t0 + decay + 0.02);
  }
}

/**
 * Did playback just cross the moment of impact?
 *
 * Called every frame with the previous and current playback times. True exactly once per strike:
 * it fires on the frame that crosses `impact`, and only for a shot that actually made contact
 * (a whiff makes no sound). Scrubbing backwards past impact arms it again, which is what someone
 * dragging the scrubber over the swing expects.
 */
export function crossedImpact(
  prev: number | undefined,
  now: number,
  impact: number,
  contact = true,
): boolean {
  if (!contact || prev === undefined) return false;
  if (now < prev) return false; // jumped backwards: re-arm, don't fire
  return prev < impact && now >= impact;
}
