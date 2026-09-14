/**
 * Data shaping for the "Brain firing" view (ui/BrainFiring.tsx).
 *
 * Everything here comes from a shot's recorded `neural_summary`: the network's spikes per 10 ms
 * bin, each sensory/motor population's spikes in the onset window (0 to readout_start_ms) and the
 * readout window (readout_start_ms to the end), and the named readout neurons' spike counts.
 * Nothing is simulated or interpolated: a population's rate is constant within each window,
 * because that is all a record holds. Which individual neurons fired is not recorded, so nothing
 * here says so.
 *
 * Time: the 400 ms of neural time were simulated before the fly moved. The view replays them,
 * slowed down, from the start of the shot's animation to the start of the backswing (while the fly
 * picks its club, addresses the ball and lines up), then holds the result.
 */
import type { ShotRecord } from "@fly-golf/protocol";
import { timelineFor } from "./playback";
import type { Timeline } from "./swing";

/** Rates map onto brightness on a log scale that reaches full brightness here. */
export const FULL_SCALE_HZ = 100;
export const DEFAULT_READOUT_START_MS = 150;

export interface PopulationActivity {
  name: string;
  role: "sensory" | "motor";
  neurons: number;
  spikes: number; // over the whole simulated window
  onsetHz: number; // mean rate per neuron, 0 .. readoutStartMs
  readoutHz: number; // mean rate per neuron, readoutStartMs .. simMs
  driveMv: number; // injected sensory drive (engineered input), 0 for motor populations
}

export interface NamedActivity {
  id: string; // MaleCNS body id
  type: string;
  side: string;
  spikes: number;
  onsetHz: number;
  readoutHz: number;
}

export interface ShotActivity {
  simMs: number;
  binMs: number;
  readoutStartMs: number;
  bins: number[]; // network spikes per bin
  peakBin: number;
  totalSpikes: number;
  activeNeurons: number;
  neuronCount: number;
  /** False on records without per-window population counts: both windows then show the mean. */
  windowed: boolean;
  populations: PopulationActivity[];
  named: NamedActivity[];
}

const num = (v: unknown): number | undefined => (typeof v === "number" && Number.isFinite(v) ? v : undefined);

/** The recorded activity of a shot, or null when it has none (the Mock controller). */
export function shotActivity(record: ShotRecord | undefined): ShotActivity | null {
  const ns = record?.neural_summary;
  if (!record || !ns) return null;
  const config = (record.controller.config ?? {}) as Record<string, unknown>;
  const bins = ns.bins.map((b) => b.spikes);
  const binMs = num(config.bin_ms) ?? (ns.bins.length > 1 ? ns.bins[1].t_ms - ns.bins[0].t_ms : ns.sim_ms);
  const simMs = ns.sim_ms;
  const readoutStartMs = Math.min(simMs, num(config.readout_start_ms) ?? DEFAULT_READOUT_START_MS);
  const onsetS = readoutStartMs / 1000;
  const readoutS = (simMs - readoutStartMs) / 1000;
  const wholeS = simMs / 1000;

  let windowed = onsetS > 0 && readoutS > 0;
  const populations: PopulationActivity[] = Object.entries(ns.populations).map(([name, p]) => {
    const n = Math.max(1, p.neurons);
    const readoutSpikes = num((p as Record<string, unknown>).readout_spikes);
    if (readoutSpikes === undefined) windowed = false;
    const mean = p.spikes / (n * wholeS);
    return {
      name,
      role: p.role,
      neurons: p.neurons,
      spikes: p.spikes,
      onsetHz: readoutSpikes === undefined || onsetS <= 0 ? mean : (p.spikes - readoutSpikes) / (n * onsetS),
      readoutHz: readoutSpikes === undefined || readoutS <= 0 ? mean : readoutSpikes / (n * readoutS),
      driveMv: Math.max(0, num((p as Record<string, unknown>).drive_mv) ?? 0),
    };
  });
  if (!windowed)
    for (const p of populations) p.onsetHz = p.readoutHz = p.spikes / (Math.max(1, p.neurons) * wholeS);

  const named: NamedActivity[] = ns.readouts.flatMap((r) => {
    const spikes = num(r.spikes);
    const id = r.id;
    if (spikes === undefined || (typeof id !== "string" && typeof id !== "number")) return [];
    const rate = num(r.rate_hz) ?? 0; // readout-window rate of this one neuron
    const readoutSpikes = Math.min(spikes, Math.round(rate * readoutS));
    return [
      {
        id: String(id),
        type: String(r.type ?? "?"),
        side: String(r.side ?? "?"),
        spikes,
        onsetHz: windowed ? (spikes - readoutSpikes) / onsetS : spikes / wholeS,
        readoutHz: windowed ? rate : spikes / wholeS,
      },
    ];
  });

  return {
    simMs,
    binMs,
    readoutStartMs,
    bins,
    peakBin: Math.max(1, ...bins),
    totalSpikes: ns.total_spikes,
    activeNeurons: ns.active_neurons,
    neuronCount: ns.neuron_count,
    windowed,
    populations,
    named,
  };
}

/** Brightness 0..1 for a mean rate: log scale, 0 Hz dark, FULL_SCALE_HZ and above full. */
export function rateLevel(hz: number): number {
  if (!(hz > 0)) return 0;
  return Math.min(1, Math.log10(1 + hz) / Math.log10(1 + FULL_SCALE_HZ));
}

export interface Frame {
  ms: number; // neural time shown
  bin: number; // index into bins
  network: number; // this bin's spikes / the shot's peak bin, 0..1
  window: "onset" | "readout";
  populations: Record<string, number>; // name -> rate (Hz) in the current window
  named: Record<string, number>; // body id -> rate (Hz) in the current window
}

/** What the recording says at `ms` of neural time. */
export function frameAt(a: ShotActivity, ms: number): Frame {
  const t = Math.min(a.simMs, Math.max(0, ms));
  const bin = Math.min(a.bins.length - 1, Math.max(0, Math.floor(t / a.binMs)));
  const window = t < a.readoutStartMs ? "onset" : "readout";
  const populations: Record<string, number> = {};
  for (const p of a.populations) populations[p.name] = window === "onset" ? p.onsetHz : p.readoutHz;
  const named: Record<string, number> = {};
  for (const r of a.named) named[r.id] = window === "onset" ? r.onsetHz : r.readoutHz;
  return {
    ms: t,
    bin,
    network: a.bins.length ? (a.bins[bin] ?? 0) / a.peakBin : 0,
    window,
    populations,
    named,
  };
}

export type Stage = "firing" | "decided" | "rest";

export interface NeuralReplay {
  endS: number; // playback seconds at which the replayed neural time reaches simMs
  slowdown: number; // playback seconds per neural second
}

/** The replayed 400 ms run from the start of the animation to the start of the backswing. */
export function neuralReplay(tl: Timeline, simMs: number): NeuralReplay {
  const endS = Math.max(0.2, tl.back0);
  return { endS, slowdown: endS / Math.max(1e-6, simMs / 1000) };
}

/** Neural time (ms) shown at playback second `t`. */
export const neuralMsAt = (t: number, replay: NeuralReplay, simMs: number): number =>
  Math.min(1, Math.max(0, t / replay.endS)) * simMs;

/** firing: replaying the 400 ms; decided: the swing plays out the decoded readout;
 *  rest: the ball is moving and nothing is simulated (the network is reset before every stroke). */
export function stageAt(t: number, tl: Timeline, replay: NeuralReplay): Stage {
  if (t < replay.endS) return "firing";
  if (t < tl.impact) return "decided";
  return "rest";
}

/** Playback seconds over which a shot's neural time is replayed (the brain panel uses it too). */
export const replayWindowS = (record: ShotRecord): number => neuralReplay(timelineFor(record), 1).endS;

// ---------------------------------------------------------------------------------------------
// The soma map (public/anatomy/malecns-brain-somata.json, built by
// services/sim/scripts/build_soma_map.py from MaleCNS v1.0, CC BY 4.0). Anatomy only: it holds
// no activity.

export interface SomaPopulation {
  role: string;
  neurons: number;
  brain: number; // somata in the brain map
  vnc: number; // somata in the ventral nerve cord (not drawn)
  outside: number; // no soma in the imaged CNS (antennae, eyes, legs)
  cells: number[]; // flat cell index, somata in that cell, ...
}

export interface SomaMap {
  format: "fly-golf-soma-map";
  version: number;
  attribution: string;
  view: string;
  cols: number;
  rows: number;
  counts: number[]; // somata per cell, row-major
  somata: { brain: number; vnc: number; none: number };
  populations: Record<string, SomaPopulation>;
  named: Record<string, [number, number]>; // body id -> [col, row] in cell units
}

export function parseSomaMap(raw: unknown): SomaMap {
  const m = raw as Partial<SomaMap> | null;
  if (!m || m.format !== "fly-golf-soma-map" || m.version !== 1)
    throw new Error("not a fly-golf-soma-map v1 file");
  const { cols, rows, counts } = m;
  if (
    !Number.isInteger(cols) ||
    !Number.isInteger(rows) ||
    !Array.isArray(counts) ||
    counts.length !== cols! * rows!
  )
    throw new Error("the soma map grid is malformed");
  if (!m.populations || !m.named || !m.somata || typeof m.attribution !== "string")
    throw new Error("the soma map is missing fields");
  return m as SomaMap;
}

/** Where to label a population: the soma-weighted centre of each half of the brain holding at
 *  least 15 % of its mapped somata (a population in both optic lobes gets two labels). */
export function populationAnchors(pop: SomaPopulation, cols: number): { col: number; row: number }[] {
  const halves = [
    { c: 0, r: 0, n: 0 },
    { c: 0, r: 0, n: 0 },
  ];
  for (let i = 0; i + 1 < pop.cells.length; i += 2) {
    const cell = pop.cells[i];
    const n = pop.cells[i + 1];
    const col = (cell % cols) + 0.5;
    const row = Math.floor(cell / cols) + 0.5;
    const h = halves[col < cols / 2 ? 0 : 1];
    h.c += col * n;
    h.r += row * n;
    h.n += n;
  }
  const total = halves[0].n + halves[1].n;
  return halves
    .filter((h) => total > 0 && h.n / total >= 0.15)
    .map((h) => ({ col: h.c / h.n, row: h.r / h.n }));
}
