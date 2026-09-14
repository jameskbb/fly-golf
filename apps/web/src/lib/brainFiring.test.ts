import { readFileSync } from "node:fs";
import { ShowcaseRun, type ShotRecord } from "@fly-golf/protocol";
import { describe, expect, it } from "vitest";
import {
  FULL_SCALE_HZ,
  frameAt,
  neuralMsAt,
  neuralReplay,
  parseSomaMap,
  populationAnchors,
  rateLevel,
  replayWindowS,
  shotActivity,
  stageAt,
} from "./brainFiring";
import { timelineFor } from "./playback";

const loadRun = (slug: string) =>
  ShowcaseRun.parse(
    JSON.parse(readFileSync(new URL(`../../public/showcase/runs/${slug}.json`, import.meta.url), "utf8")),
  );
const somaMap = parseSomaMap(
  JSON.parse(
    readFileSync(new URL("../../public/anatomy/malecns-brain-somata.json", import.meta.url), "utf8"),
  ),
);

const trained = loadRun("trained-front-nine");
const mock = loadRun("mock-front-nine");
const neural = (run: ShowcaseRun): ShotRecord[] => run.shots.filter((s) => s.neural_summary);

describe("brain firing: shots without a brain", () => {
  it("gives Mock shots no activity at all", () => {
    expect(mock.shots.length).toBeGreaterThan(0);
    for (const shot of mock.shots) {
      expect(shot.controller.is_mock).toBe(true);
      expect(shotActivity(shot)).toBeNull();
    }
    expect(shotActivity(undefined)).toBeNull();
  });
});

describe("brain firing: a recorded MaleCNS shot", () => {
  const shots = neural(trained);
  const shot = shots[0];
  const a = shotActivity(shot)!;
  const ns = shot.neural_summary!;

  it("keeps the recorded bins and totals exactly", () => {
    expect(a.bins).toEqual(ns.bins.map((b) => b.spikes));
    expect(a.bins.length).toBe(Math.round(a.simMs / a.binMs));
    expect(a.bins.reduce((s, v) => s + v, 0)).toBe(ns.total_spikes);
    expect(a.peakBin).toBe(Math.max(...a.bins));
    expect([a.totalSpikes, a.activeNeurons, a.neuronCount]).toEqual([
      ns.total_spikes,
      ns.active_neurons,
      ns.neuron_count,
    ]);
  });

  it("splits every population into the onset and readout windows without losing a spike", () => {
    expect(a.windowed).toBe(true);
    expect(a.readoutStartMs).toBe(150);
    const onsetS = a.readoutStartMs / 1000;
    const readoutS = (a.simMs - a.readoutStartMs) / 1000;
    for (const p of a.populations) {
      const rec = ns.populations[p.name];
      expect(p.onsetHz).toBeGreaterThanOrEqual(0);
      // the readout rate is the recorded rate_hz, and the two windows add back up to the total
      expect(p.readoutHz).toBeCloseTo(rec.rate_hz, 3);
      expect(p.onsetHz * p.neurons * onsetS + p.readoutHz * p.neurons * readoutS).toBeCloseTo(rec.spikes, 6);
    }
  });

  it("shapes the named readout neurons from their own recorded counts", () => {
    expect(a.named.length).toBe(ns.readouts.length);
    const onsetS = a.readoutStartMs / 1000;
    const readoutS = (a.simMs - a.readoutStartMs) / 1000;
    for (const r of a.named) {
      expect(r.onsetHz).toBeGreaterThanOrEqual(0);
      expect(Math.round(r.onsetHz * onsetS + r.readoutHz * readoutS)).toBe(r.spikes);
    }
  });

  it("reads the frame at a moment of neural time from the recording only", () => {
    const start = frameAt(a, 0);
    expect(start.window).toBe("onset");
    expect(start.bin).toBe(0);
    expect(start.network).toBeCloseTo(a.bins[0] / a.peakBin);
    const peak = a.bins.indexOf(a.peakBin);
    expect(frameAt(a, peak * a.binMs + 1).network).toBe(1);
    const late = frameAt(a, 399.9);
    expect(late.window).toBe("readout");
    expect(late.bin).toBe(a.bins.length - 1);
    expect(frameAt(a, 1e9).bin).toBe(a.bins.length - 1);
    for (const p of a.populations) {
      expect(start.populations[p.name]).toBe(p.onsetHz);
      expect(late.populations[p.name]).toBe(p.readoutHz);
    }
  });

  it("replays the 400 ms slowed down, ending as the backswing starts", () => {
    const tl = timelineFor(shot);
    const replay = neuralReplay(tl, a.simMs);
    expect(replay.endS).toBe(tl.back0);
    expect(replayWindowS(shot)).toBe(tl.back0);
    expect(replay.slowdown).toBeGreaterThan(1);
    expect(neuralMsAt(0, replay, a.simMs)).toBe(0);
    expect(neuralMsAt(replay.endS / 2, replay, a.simMs)).toBeCloseTo(a.simMs / 2);
    expect(neuralMsAt(tl.end, replay, a.simMs)).toBe(a.simMs);
    expect(stageAt(0, tl, replay)).toBe("firing");
    expect(stageAt(replay.endS + 1e-3, tl, replay)).toBe("decided");
    expect(stageAt(tl.impact + 1e-3, tl, replay)).toBe("rest");
  });

  it("maps rates to brightness on a bounded log scale", () => {
    expect(rateLevel(0)).toBe(0);
    expect(rateLevel(Number.NaN)).toBe(0);
    expect(rateLevel(FULL_SCALE_HZ)).toBeCloseTo(1);
    expect(rateLevel(10 * FULL_SCALE_HZ)).toBe(1);
    expect(rateLevel(10)).toBeGreaterThan(rateLevel(1));
  });

  it("falls back to whole-window means for records without per-window counts", () => {
    const old = structuredClone(shot);
    for (const p of Object.values(old.neural_summary!.populations))
      delete (p as Record<string, unknown>).readout_spikes;
    const b = shotActivity(old)!;
    expect(b.windowed).toBe(false);
    for (const p of b.populations) {
      expect(p.onsetHz).toBe(p.readoutHz);
      expect(p.onsetHz).toBeCloseTo(p.spikes / (Math.max(1, p.neurons) * (b.simMs / 1000)));
    }
  });

  it("every MaleCNS shot in every committed round has activity to show", () => {
    for (const slug of ["trained-front-nine", "untrained-front-nine"]) {
      for (const s of loadRun(slug).shots) {
        if (s.controller.is_mock) continue;
        const act = shotActivity(s);
        expect(act).not.toBeNull();
        expect(act!.bins.length).toBeGreaterThan(0);
      }
    }
  });
});

describe("brain firing: the soma map", () => {
  const shot = neural(trained)[0];

  it("covers every recorded population with the same neuron counts", () => {
    for (const [name, p] of Object.entries(shot.neural_summary!.populations)) {
      const m = somaMap.populations[name];
      expect(m, name).toBeDefined();
      expect(m.neurons).toBe(p.neurons);
      expect(m.brain + m.vnc + m.outside).toBe(m.neurons);
      let placed = 0;
      for (let i = 0; i < m.cells.length; i += 2) {
        expect(m.cells[i]).toBeLessThan(somaMap.cols * somaMap.rows);
        placed += m.cells[i + 1];
      }
      expect(placed).toBe(m.brain);
    }
  });

  it("places the named readout neurons that a shot records", () => {
    const ids = shot.neural_summary!.readouts.map((r) => String(r.id));
    const placed = ids.filter((id) => somaMap.named[id]);
    expect(placed.length).toBe(ids.length);
    for (const id of placed) {
      const [c, r] = somaMap.named[id];
      expect(c).toBeGreaterThanOrEqual(0);
      expect(c).toBeLessThan(somaMap.cols);
      expect(r).toBeGreaterThanOrEqual(0);
      expect(r).toBeLessThan(somaMap.rows);
    }
  });

  it("labels a population in both optic lobes twice and a one-sided one once", () => {
    const lc15 = populationAnchors(somaMap.populations.LC15, somaMap.cols);
    expect(lc15).toHaveLength(2);
    const left = populationAnchors(somaMap.populations.LC10_L, somaMap.cols);
    const right = populationAnchors(somaMap.populations.LC10_R, somaMap.cols);
    expect(left).toHaveLength(1);
    expect(right).toHaveLength(1);
    // seen from behind, the fly's left optic lobe is on the left of the map
    expect(left[0].col).toBeLessThan(somaMap.cols / 2);
    expect(right[0].col).toBeGreaterThan(somaMap.cols / 2);
    expect(populationAnchors(somaMap.populations.leg_bristle, somaMap.cols)).toEqual([]);
  });

  it("rejects a file that is not a soma map", () => {
    expect(() => parseSomaMap({ format: "something-else" })).toThrow();
    expect(() => parseSomaMap({ ...somaMap, counts: [1, 2, 3] })).toThrow();
  });

  it("is small and keeps the CC BY 4.0 attribution", () => {
    expect(somaMap.counts.length).toBe(somaMap.cols * somaMap.rows);
    expect(somaMap.attribution).toMatch(/MaleCNS v1\.0/);
    expect(somaMap.attribution).toMatch(/CC BY 4\.0/);
    const bytes = readFileSync(
      new URL("../../public/anatomy/malecns-brain-somata.json", import.meta.url),
    ).length;
    expect(bytes).toBeLessThan(200_000);
  });
});
