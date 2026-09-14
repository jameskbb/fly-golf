import { useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import type { ShotRecord } from "@fly-golf/protocol";
import {
  frameAt,
  neuralMsAt,
  neuralReplay,
  parseSomaMap,
  populationAnchors,
  rateLevel,
  shotActivity,
  stageAt,
  type Frame,
  type ShotActivity,
  type SomaMap,
} from "../lib/brainFiring";
import { timelineFor } from "../lib/playback";
import { IS_SHOWCASE, assetUrl } from "../lib/source";
import { useFrameClock } from "../lib/useFrameClock";
import { playbackTime, selectLastRecord, useStore } from "../store";
import { brainById } from "./brains";
import { fmt, fmtInt } from "./widgets";
import "./brainFiring.css";

/**
 * "Brain firing": a shot's recorded neural activity, drawn on the real positions of the MaleCNS
 * brain's cell bodies. What is anatomy, what is recorded and what is stylised is spelled out in
 * the view's own legend and caption, and in lib/brainFiring.ts.
 */

type Tone = "live" | "trained" | "mock";
const HEX = {
  live: "#39e08a",
  trained: "#c38bff",
  mock: "#ff8a3d",
  sense: "#6cc7ff",
  rest: "#2c4238",
  net: "#dce8e1",
};

/** DN_all is DN_L + DN_R (drawn once, per side), and the steering populations are the named
 *  DNa01/DNa02 neurons, which are drawn as their own rings. */
const SKIP_ON_MAP = new Set(["DN_all", "steer_L", "steer_R"]);
const MAP_LABEL: Record<string, string> = {
  LC10_L: "LC10",
  LC10_R: "LC10",
  LC15: "LC15",
  DN_all: "DNs",
};

/** The rates listed under the map: the populations drawn on it, and the senses whose cell bodies
 *  are outside the imaged brain. A reading over two populations is their neuron-weighted mean. */
const READINGS: { label: string; pops: string[]; outside?: boolean; what: string }[] = [
  { label: "LC10 L", pops: ["LC10_L"], what: "LC10 visual neurons, left optic lobe" },
  { label: "LC10 R", pops: ["LC10_R"], what: "LC10 visual neurons, right optic lobe" },
  { label: "LC15", pops: ["LC15"], what: "LC15 visual neurons, both optic lobes" },
  {
    label: "Antenna L",
    pops: ["JO-C_L", "JO-E_L"],
    outside: true,
    what: "Johnston's organ JO-C and JO-E, left antenna",
  },
  {
    label: "Antenna R",
    pops: ["JO-C_R", "JO-E_R"],
    outside: true,
    what: "Johnston's organ JO-C and JO-E, right antenna",
  },
  { label: "Eye rims", pops: ["R7d_R8d"], outside: true, what: "dorsal-rim R7d/R8d photoreceptors" },
  { label: "Legs", pops: ["leg_bristle"], outside: true, what: "leg bristle mechanosensory neurons" },
  { label: "DN L", pops: ["DN_L"], what: "descending neurons, left" },
  { label: "DN R", pops: ["DN_R"], what: "descending neurons, right" },
];

export function toggleFiring() {
  const st = useStore.getState();
  st.set(
    st.firingOpen
      ? { firingOpen: false }
      : { firingOpen: true, techOpen: false, modesOpen: false, runsOpen: false },
  );
}

// ---------------------------------------------------------------------------------------------
// data hooks

let somaMapPromise: Promise<SomaMap> | null = null;
function loadSomaMap(): Promise<SomaMap> {
  somaMapPromise ??= fetch(assetUrl("anatomy/malecns-brain-somata.json"))
    .then((r) => {
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return r.json();
    })
    .then(parseSomaMap)
    .catch((e: unknown) => {
      somaMapPromise = null;
      throw e;
    });
  return somaMapPromise;
}

function useSomaMap(): { map?: SomaMap; error?: string } {
  const [state, setState] = useState<{ map?: SomaMap; error?: string }>({});
  useEffect(() => {
    let live = true;
    loadSomaMap().then(
      (map) => live && setState({ map }),
      (e: unknown) => live && setState({ error: e instanceof Error ? e.message : String(e) }),
    );
    return () => {
      live = false;
    };
  }, []);
  return state;
}

function useReducedMotion(): boolean {
  const query = "(prefers-reduced-motion: reduce)";
  const [reduced, setReduced] = useState(() => typeof matchMedia === "function" && matchMedia(query).matches);
  useEffect(() => {
    if (typeof matchMedia !== "function") return;
    const m = matchMedia(query);
    const on = () => setReduced(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  return reduced;
}

// ---------------------------------------------------------------------------------------------
// the map

interface Layers {
  w: number;
  h: number;
  pitch: number;
  base: HTMLCanvasElement;
  network: HTMLCanvasElement;
  pops: { name: string; canvas: HTMLCanvasElement }[];
}

function layer(w: number, h: number): [HTMLCanvasElement, CanvasRenderingContext2D] {
  const c = document.createElement("canvas");
  c.width = w;
  c.height = h;
  return [c, c.getContext("2d")!];
}

/** Pre-render the halftone: one dot per map cell, sized by how many somata it holds. Each frame
 *  then only composites these layers at the recorded brightness. */
function buildLayers(map: SomaMap, cssWidth: number, dpr: number, tone: string): Layers {
  const w = Math.max(1, Math.round(cssWidth * dpr));
  const pitch = w / map.cols;
  const h = Math.max(1, Math.round(pitch * map.rows));
  const max = Math.max(1, ...map.counts);
  const [base, b] = layer(w, h);
  const [network, n] = layer(w, h);
  b.fillStyle = HEX.rest;
  n.fillStyle = HEX.net;
  for (let i = 0; i < map.counts.length; i++) {
    const c = map.counts[i];
    if (!c) continue;
    const x = ((i % map.cols) + 0.5) * pitch;
    const y = (Math.floor(i / map.cols) + 0.5) * pitch;
    const r = pitch * (0.14 + 0.34 * Math.sqrt(c / max));
    for (const ctx of [b, n]) {
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fill();
    }
  }
  const pops = Object.entries(map.populations)
    .filter(([name, p]) => p.brain > 0 && !SKIP_ON_MAP.has(name))
    .sort(([, a], [, z]) => (a.role === z.role ? 0 : a.role === "sensory" ? -1 : 1))
    .map(([name, p]) => {
      const [canvas, ctx] = layer(w, h);
      const color = p.role === "sensory" ? HEX.sense : tone;
      ctx.fillStyle = color;
      ctx.shadowColor = color;
      ctx.shadowBlur = pitch * 2.4;
      for (let i = 0; i + 1 < p.cells.length; i += 2) {
        const cell = p.cells[i];
        const x = ((cell % map.cols) + 0.5) * pitch;
        const y = (Math.floor(cell / map.cols) + 0.5) * pitch;
        ctx.beginPath();
        ctx.arc(x, y, pitch * (0.42 + 0.16 * Math.min(1, (p.cells[i + 1] - 1) / 3)), 0, Math.PI * 2);
        ctx.fill();
      }
      return { name, canvas };
    });
  return { w, h, pitch, base, network, pops };
}

type Light = "firing" | "held" | "rest";

/** Opacity for a brightness level: anything that fired stays visible, and it rises with the
 *  (log) rate. Zero stays dark. */
const glow = (level: number) => (level > 0 ? 0.22 + 0.78 * level : 0);

function drawMap(
  canvas: HTMLCanvasElement,
  L: Layers,
  map: SomaMap,
  a: ShotActivity | null,
  frame: Frame | null,
  light: Light,
  tone: string,
) {
  if (canvas.width !== L.w || canvas.height !== L.h) {
    canvas.width = L.w;
    canvas.height = L.h;
  }
  const ctx = canvas.getContext("2d");
  if (!ctx) return;
  ctx.globalCompositeOperation = "source-over";
  ctx.globalAlpha = 1;
  ctx.clearRect(0, 0, L.w, L.h);
  ctx.drawImage(L.base, 0, 0);
  const lit = light !== "rest" && a && frame;
  if (lit) {
    ctx.globalCompositeOperation = "lighter";
    // the whole network's spikes in this 10 ms bin: every cell together (not per neuron)
    ctx.globalAlpha = Math.min(1, 0.05 + 0.5 * frame.network);
    ctx.drawImage(L.network, 0, 0);
    for (const p of L.pops) {
      const level = rateLevel(frame.populations[p.name] ?? 0);
      if (level < 0.01) continue;
      ctx.globalAlpha = glow(level);
      ctx.drawImage(p.canvas, 0, 0);
    }
  }
  // named readout neurons: a ring where each cell body is, filled at its own recorded rate
  ctx.globalCompositeOperation = "source-over";
  const ring = L.pitch * 1.05;
  for (const r of a?.named ?? []) {
    const pos = map.named[r.id];
    if (!pos) continue;
    const x = pos[0] * L.pitch;
    const y = pos[1] * L.pitch;
    const level = lit ? rateLevel(frame.named[r.id] ?? 0) : 0;
    if (level > 0.01) {
      ctx.globalAlpha = glow(level);
      ctx.fillStyle = "#ffffff";
      ctx.shadowColor = tone;
      ctx.shadowBlur = L.pitch * 3;
      ctx.beginPath();
      ctx.arc(x, y, ring * 0.8, 0, Math.PI * 2);
      ctx.fill();
      ctx.shadowBlur = 0;
    }
    ctx.globalAlpha = lit ? 0.7 : 0.35;
    ctx.strokeStyle = "#ffffff";
    ctx.lineWidth = Math.max(1, L.pitch * 0.28);
    ctx.beginPath();
    ctx.arc(x, y, ring, 0, Math.PI * 2);
    ctx.stroke();
  }
  ctx.globalAlpha = 1;
}

function SomaCanvas({
  map,
  activity,
  frame,
  light,
  tone,
  label,
}: {
  map: SomaMap;
  activity: ShotActivity | null;
  frame: Frame | null;
  light: Light;
  tone: string;
  label: string;
}) {
  const wrap = useRef<HTMLDivElement>(null);
  const canvas = useRef<HTMLCanvasElement>(null);
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const el = wrap.current;
    if (!el) return;
    const ro = new ResizeObserver(([e]) => setWidth(Math.round(e.contentRect.width)));
    ro.observe(el);
    return () => ro.disconnect();
  }, []);
  const dpr = Math.min(2, typeof window === "undefined" ? 1 : window.devicePixelRatio || 1);
  const layers = useMemo(
    () => (width > 0 ? buildLayers(map, width, dpr, tone) : null),
    [map, width, dpr, tone],
  );
  useEffect(() => {
    if (canvas.current && layers) drawMap(canvas.current, layers, map, activity, frame, light, tone);
  });
  const anchors = useMemo(
    () =>
      Object.entries(map.populations)
        .filter(([name]) => MAP_LABEL[name])
        .flatMap(([name, p]) => {
          const at = populationAnchors(p, map.cols);
          // the descending neurons are one cluster across the midline: one label at its centre
          const pts =
            name === "DN_all" && at.length > 1
              ? [{ col: (at[0].col + at[1].col) / 2, row: (at[0].row + at[1].row) / 2 }]
              : at;
          return pts.map((pt, i) => ({ name, key: `${name}-${i}`, ...pt }));
        }),
    [map],
  );
  return (
    <div
      className="firing-map"
      ref={wrap}
      style={{ aspectRatio: `${map.cols} / ${map.rows}` } as CSSProperties}
    >
      <canvas ref={canvas} role="img" aria-label={label} />
      {anchors.map((an) => {
        const role = map.populations[an.name].role;
        const hz = light !== "rest" && frame ? (frame.populations[an.name] ?? 0) : 0;
        return (
          <span
            key={an.key}
            className={`map-label ${role}`}
            style={{
              left: `${(an.col / map.cols) * 100}%`,
              top: `${(an.row / map.rows) * 100}%`,
              opacity: 0.55 + 0.45 * rateLevel(hz),
            }}
            aria-hidden
          >
            {MAP_LABEL[an.name]}
          </span>
        );
      })}
      <span className="map-side left" title="The fly's left">
        L
      </span>
      <span className="map-side right" title="The fly's right">
        R
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// the 40 recorded bins

function BinStrip({ a, frame, light }: { a: ShotActivity; frame: Frame | null; light: Light | "ghost" }) {
  const top = 30;
  return (
    <div className="firing-strip">
      <svg
        viewBox={`0 0 ${a.simMs} 34`}
        preserveAspectRatio="none"
        role="img"
        aria-label={`Network spikes per ${a.binMs} ms, recorded`}
      >
        {a.bins.map((v, i) => {
          const h = Math.max(0.8, (top * v) / a.peakBin);
          const state =
            light === "ghost" || light === "rest"
              ? "future"
              : light === "held" || !frame
                ? "past"
                : i < frame.bin
                  ? "past"
                  : i === frame.bin
                    ? "now"
                    : "future";
          return (
            <rect
              key={i}
              className={`bar ${state}`}
              x={i * a.binMs + a.binMs * 0.14}
              width={a.binMs * 0.72}
              y={top + 2 - h}
              height={h}
            />
          );
        })}
        <line className="divider" x1={a.readoutStartMs} x2={a.readoutStartMs} y1={0} y2={34} />
      </svg>
      <div
        className="firing-windows"
        style={{ gridTemplateColumns: `${a.readoutStartMs}fr ${a.simMs - a.readoutStartMs}fr` }}
      >
        <span className={frame?.window === "onset" && light === "firing" ? "on" : ""}>
          0–{fmt(a.readoutStartMs, 0)} ms onset
        </span>
        <span className={frame?.window === "readout" && light !== "rest" && light !== "ghost" ? "on" : ""}>
          {fmt(a.readoutStartMs, 0)}–{fmt(a.simMs, 0)} ms readout
        </span>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------------------------
// the card

type View =
  | { kind: "none" }
  | { kind: "mock" }
  | { kind: "computing" }
  | { kind: "ready"; a: ShotActivity }
  | { kind: "after"; a: ShotActivity }
  | { kind: "playing"; a: ShotActivity; light: Light; frame: Frame; ms: number; slowdown: number };

function FiringCard() {
  const playback = useStore((s) => s.playback);
  const last = useStore(selectLastRecord);
  const upcoming = useStore((s) =>
    IS_SHOWCASE && s.showcase?.run && s.showcase.stage === "before"
      ? s.showcase.run.shots[s.showcase.cursor]
      : undefined,
  );
  const session = useStore((s) => s.session);
  const busy = useStore((s) => s.busy);
  useStore((s) => s.playPhase); // re-render at each beat of the animation (the stage boundaries)
  const reduced = useReducedMotion();
  const soma = useSomaMap();

  const record: ShotRecord | undefined = playback?.record ?? upcoming ?? last;
  const controller = record?.controller ?? session?.controller;
  const tone: Tone = controller?.is_mock ? "mock" : (brainById(controller?.id)?.tone ?? "live");
  const activity = useMemo(() => shotActivity(record), [record]);
  const tl = useMemo(() => (record ? timelineFor(record) : null), [record]);
  const replay = useMemo(() => (tl && activity ? neuralReplay(tl, activity.simMs) : null), [tl, activity]);
  const t = playback ? playbackTime(playback) : 0;
  const stage = playback && tl && replay ? stageAt(t, tl, replay) : null;
  useFrameClock(!!playback && playback.pausedAt === undefined && stage === "firing" && !reduced);

  let view: View;
  if (controller?.is_mock && !(busy && !playback)) view = { kind: "mock" };
  else if (busy && !playback) view = controller?.is_mock ? { kind: "mock" } : { kind: "computing" };
  else if (!activity) view = record ? { kind: "mock" } : { kind: "none" };
  else if (playback && stage && replay) {
    const light: Light =
      stage === "firing" ? (reduced ? "held" : "firing") : stage === "decided" ? "held" : "rest";
    const ms = light === "firing" ? neuralMsAt(t, replay, activity.simMs) : activity.simMs;
    view = {
      kind: "playing",
      a: activity,
      light,
      ms,
      frame: frameAt(activity, ms),
      slowdown: replay.slowdown,
    };
  } else view = upcoming ? { kind: "ready", a: activity } : { kind: "after", a: activity };

  const brainName = controller ? (brainById(controller.id)?.name ?? controller.label) : "";
  const toneHex = HEX[tone];

  return (
    <div className="firing-card" style={{ "--tone": toneHex } as CSSProperties}>
      <header className="firing-head">
        <h2 className="firing-title">Brain firing</h2>
        {brainName && <span className="firing-who">{brainName}</span>}
        <button
          className="firing-close"
          onClick={toggleFiring}
          aria-label="Hide the brain firing view"
          title="Hide (B)"
        >
          ×
        </button>
      </header>
      {view.kind === "mock" ? (
        <div className="firing-none">
          <p className="firing-none-lede">The wind-up has no brain.</p>
          <p>
            Mock shots come from hand-written golf rules. No neurons are simulated, so there is no activity to
            show. Pick MaleCNS or Trained to watch the connectome.
          </p>
        </div>
      ) : (
        <FiringBody
          view={view}
          soma={soma}
          toneHex={toneHex}
          reduced={reduced}
          neurons={controller?.neuron_count}
        />
      )}
    </div>
  );
}

function FiringBody({
  view,
  soma,
  toneHex,
  reduced,
  neurons,
}: {
  view: Exclude<View, { kind: "mock" }>;
  soma: { map?: SomaMap; error?: string };
  toneHex: string;
  reduced: boolean;
  neurons?: number | null;
}) {
  const a = "a" in view ? view.a : null;
  const playing = view.kind === "playing" ? view : null;
  const light: Light = playing?.light ?? "rest";
  const frame = playing ? playing.frame : a ? frameAt(a, a.simMs) : null;

  let big = "";
  let unit = "";
  let sub = "";
  if (view.kind === "none") {
    big = "Ready";
    sub = IS_SHOWCASE
      ? "Play a shot to replay its recorded neural activity here."
      : "Hit a shot (Space). Its 400 ms of simulated activity replays here.";
  } else if (view.kind === "computing") {
    big = "Simulating";
    sub = `400 ms across ${fmtInt(neurons ?? 166700)} neurons. The activity appears here once the shot is recorded.`;
  } else if (view.kind === "ready" && a) {
    big = "Ready";
    sub = `Play the shot to replay its ${fmt(a.simMs, 0)} ms of recorded activity, slowed down.`;
  } else if (view.kind === "after" && a) {
    big = "At rest";
    sub = `Last shot: ${fmtInt(a.totalSpikes)} spikes in ${fmt(a.simMs, 0)} ms; ${fmtInt(a.activeNeurons)} of ${fmtInt(
      a.neuronCount,
    )} neurons fired at least once. Replay (R) to watch it again.`;
  } else if (playing && a) {
    if (playing.light === "firing") {
      big = fmt(Math.floor(playing.ms), 0);
      unit = "ms";
      sub = `of ${fmt(a.simMs, 0)} ms of neural time, replayed ${fmt(playing.slowdown, 1)}× slower. In the simulation it all happened before the fly moved.`;
    } else if (playing.light === "held") {
      big = fmt(a.simMs, 0);
      unit = "ms";
      sub = reduced
        ? "Reduced motion: the whole recorded window at once. The swing plays out the decoded readout."
        : "Decision made. The swing plays out what was read from the descending neurons.";
    } else {
      big = "At rest";
      sub = "Nothing is simulated while the ball moves. The network is reset to rest before every stroke.";
    }
  }

  const mapLabel = soma.map
    ? `Map of ${fmtInt(soma.map.somata.brain)} cell bodies in the MaleCNS v1.0 brain, seen from behind, lit by this shot's recorded activity.`
    : "";

  return (
    <>
      <div className="firing-time">
        <span className="firing-big">
          {big}
          {unit && <span className="firing-unit">{unit}</span>}
        </span>
        <p className="firing-sub" aria-live="polite">
          {sub}
        </p>
      </div>

      {soma.map ? (
        <SomaCanvas map={soma.map} activity={a} frame={frame} light={light} tone={toneHex} label={mapLabel} />
      ) : (
        <p className="firing-map-empty">
          {soma.error ? `The brain map could not be loaded (${soma.error}).` : "Loading the brain map…"}
        </p>
      )}

      {a && <BinStrip a={a} frame={frame} light={view.kind === "playing" ? light : "ghost"} />}

      {a && frame && (
        <ul className="firing-readings" aria-label="Recorded mean firing rates">
          <li className="firing-readings-title" aria-hidden>
            Mean rate per neuron,{" "}
            {frame.window === "onset"
              ? `0–${fmt(a.readoutStartMs, 0)} ms`
              : `${fmt(a.readoutStartMs, 0)}–${fmt(a.simMs, 0)} ms`}{" "}
            (Hz)
          </li>
          {READINGS.map((r) => {
            const pops = a.populations.filter((p) => r.pops.includes(p.name));
            if (!pops.length) return null;
            const n = pops.reduce((s, p) => s + p.neurons, 0);
            const hz =
              pops.reduce((s, p) => s + (frame.populations[p.name] ?? 0) * p.neurons, 0) / Math.max(1, n);
            const detail = pops
              .map((p) => `${p.name} ${fmt(frame.populations[p.name] ?? 0, 1)} Hz`)
              .join(", ");
            return (
              <li
                className="reading"
                key={r.label}
                title={`${r.what}${r.outside ? " (cell bodies outside the imaged brain)" : ""}: ${detail}`}
                aria-label={`${r.label}: ${fmt(hz, 1)} hertz`}
              >
                <i
                  className={`rd-sw ${pops[0].role}${r.outside ? " outside" : ""}`}
                  style={{ opacity: light === "rest" ? 0.2 : Math.max(0.2, glow(rateLevel(hz))) }}
                  aria-hidden
                />
                <span className="reading-name">{r.label}</span>
                <span className="reading-hz">{fmt(hz, hz >= 10 ? 0 : 1)}</span>
              </li>
            );
          })}
        </ul>
      )}

      <ul className="firing-legend">
        <li>
          <i className="sw sense" /> Golf input
        </li>
        <li>
          <i className="sw square" /> Outside the brain
        </li>
        <li>
          <i className="sw tone" /> Descending neurons (output)
        </li>
        <li>
          <i className="sw ring" /> {a ? a.named.length : 18} named DNs
        </li>
        <li>
          <i className="sw rest" /> Whole network
        </li>
        <li className="scale" aria-label="Brightness scale: 0 to 100 hertz, logarithmic">
          <span>0</span>
          <b />
          <span>100 Hz, log</span>
        </li>
      </ul>

      <details className="firing-caption">
        <summary>Dots are real cell bodies; the light is this shot&apos;s recorded activity.</summary>
        <p>
          <b>Anatomy:</b> each dot is a cell of a map of MaleCNS v1.0 soma positions: the brain seen from
          behind, binned, dot size by how many cell bodies it holds. The nerve cord is not drawn.{" "}
          <b>Recorded:</b> each population glows at its mean rate over 0–150 ms, then 150–400 ms; each named
          descending neuron (DN) at its own rate; all other dots brighten together with the whole
          network&apos;s spikes per 10 ms. Which individual neurons fired was not recorded, so no single
          neuron is shown firing on its own. <b>Engineered:</b> the golf input into the sensory neurons and
          the readout of the stroke from the DNs. The antenna, eye-rim and leg neurons have their cell bodies
          outside the imaged brain, so they are squares, not dots.
        </p>
        <p className="attribution">{soma.map?.attribution ?? "MaleCNS v1.0, CC BY 4.0."}</p>
      </details>
    </>
  );
}

function DotGlyph() {
  return (
    <svg className="dot-glyph" viewBox="0 0 12 12" aria-hidden>
      {[0, 1, 2].flatMap((r) =>
        [0, 1, 2].map((c) => (
          <circle key={`${r}${c}`} cx={2 + c * 4} cy={2 + r * 4} r={r === 1 && c === 1 ? 1.7 : 1.1} />
        )),
      )}
    </svg>
  );
}

/** The toggle, and the view when it is on. Desktop: over the top right of the course.
 *  Narrow screens: in the page, between the shot bar and the brain panel. */
export function BrainFiring() {
  const open = useStore((s) => s.firingOpen);
  const drawer = useStore((s) => s.techOpen || s.modesOpen || s.runsOpen);
  const ready = useStore((s) => !IS_SHOWCASE || !!s.showcase?.started);
  if (!ready) return null;
  return (
    <section
      className={`firing${open ? " open" : ""}${drawer ? " under-drawer" : ""}`}
      aria-label="Brain firing"
    >
      {open ? (
        <FiringCard />
      ) : (
        <button
          className="firing-toggle"
          onClick={toggleFiring}
          aria-expanded={false}
          title="Show the brain firing (B)"
        >
          <DotGlyph />
          <span>Watch the brain fire</span>
          <kbd>B</kbd>
        </button>
      )}
    </section>
  );
}
