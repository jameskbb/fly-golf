#!/usr/bin/env node
// Deterministic frame-stepped capture of a recorded Fly Golf shot from the static showcase.
//
// The page's clock (performance.now, Date.now, requestAnimationFrame) is replaced by a virtual
// clock before any app code runs, so every output frame is exactly 1/fps of playback time apart
// no matter how slowly SwiftShader renders it. Nothing in the app is modified: the page is opened
// in the app's own cinema mode (`&cinema=1`: header, brain panel, HUD, playback controls,
// scorecard and drawers all hidden, the course fills the window). The only capture-only CSS then
// is a transparent caret. `--no-cinema` restores the v1 behaviour (injected layout CSS + a
// re-flowed bottom HUD).
//
// Usage (run with the WSLg display variables unset, or Chromium's GPU process hangs):
//   env -u DISPLAY -u WAYLAND_DISPLAY -u XDG_RUNTIME_DIR node capture.mjs \
//     --run trained-front-nine-s07 --shot 14 --name pondhop-tee [--seconds 30] [--hold 0.7] \
//     [--width 1080 --height 1920] [--dpr 1] [--fps 30] [--also-fps 30] [--brainfire] \
//     [--frame '[[t,cx,cy,zoom],...]'] [--frames <dir>] [--pre 0] [--out ../clips] \
//     [--url http://localhost:4173/] [--no-cinema [--keep-brain-panel] [--no-hud]]
//
// --dpr      deviceScaleFactor; output PNGs are width*dpr x height*dpr (R3F renders the canvas
//            at up to dpr 2, the brain-firing card at up to 2 as well).
// --fps      playback-time frame rate (virtual clock step 1/fps). When fps != 30 the clip is
//            written as <name>-<fps>.mp4/.json/-sheet.png, and --also-fps F additionally writes
//            <name>.mp4/.json/-sheet.png from every (fps/F)-th rendered frame (e.g. 120 -> 30).
//
// --seconds  maximum seconds captured after Space (default 30); capture stops earlier when the
//            playback ends (phase label goes blank) plus --hold seconds.
// --pre      seconds of the still pre-Space view to include before playback starts.
import { chromium } from "/home/james/.nvm/versions/node/v24.21.0/lib/node_modules/playwright/index.mjs";
import { execFileSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
const flag = (k) => argv.includes(`--${k}`);
const opt = (k, d) => {
  const i = argv.indexOf(`--${k}`);
  return i >= 0 && i + 1 < argv.length ? argv[i + 1] : d;
};

const run = opt("run", "trained-front-nine-s07");
const shot = Number(opt("shot", "14"));
const name = opt("name", `${run}-${shot}`);
const fps = Number(opt("fps", "30"));
const maxSeconds = Number(opt("seconds", "30"));
const hold = Number(opt("hold", "0.7"));
const pre = Number(opt("pre", "0"));
const width = Number(opt("width", "1080"));
const height = Number(opt("height", "1920"));
const brainfire = flag("brainfire");
const keepBrain = flag("keep-brain-panel");
const noHud = flag("no-hud");
const cinema = !flag("no-cinema");
const dpr = Number(opt("dpr", "1"));
const alsoFps = opt("also-fps", "") ? Number(opt("also-fps")) : null;
if (alsoFps && (fps % alsoFps !== 0)) throw new Error("--also-fps must divide --fps");
const baseUrl = opt("url", "http://localhost:4173/");
const outDir = path.resolve(opt("out", path.join(here, "..", "clips")));
const ffmpeg =
  opt("ffmpeg", "") ||
  process.env.FFMPEG ||
  "/home/james/.cache/uv/archive-v0/IyyDAcEJEdniCYLm/lib/python3.12/site-packages/imageio_ffmpeg/binaries/ffmpeg-linux-x86_64-v7.0.2";
const every = Number(opt("every", "1")); // preview mode: keep every Nth frame, no encode
// --frame '[[t,cx,cy,zoom],...]': capture-only virtual camera crop. The stage renders the window
// centred at (cx,cy) - normalised coordinates of the app's own view as it would look in a 16:9
// stage of the same height - magnified by zoom (1 = native pixel scale). Keys are eased
// (smoothstep) over playback time t in seconds; a single key is a static crop.
const REF_ASPECT = 16 / 9;
const frameKeys = opt("frame", "") ? JSON.parse(opt("frame")) : null;
const voAt = (t) => {
  if (!frameKeys) return null;
  const k = frameKeys;
  let v;
  if (t <= k[0][0]) v = k[0].slice(1);
  else if (t >= k[k.length - 1][0]) v = k[k.length - 1].slice(1);
  else
    for (let i = 0; i + 1 < k.length; i++)
      if (t >= k[i][0] && t <= k[i + 1][0]) {
        const u = (t - k[i][0]) / (k[i + 1][0] - k[i][0]);
        const e = u * u * (3 - 2 * u);
        v = k[i].slice(1).map((a, j) => a + (k[i + 1][j + 1] - a) * e);
        break;
      }
  return { cx: v[0], cy: v[1], z: v[2], A: REF_ASPECT };
};
const framesDir = path.resolve(opt("frames", path.join(outDir, ".frames", name)));

fs.mkdirSync(outDir, { recursive: true });
fs.rmSync(framesDir, { recursive: true, force: true });
fs.mkdirSync(framesDir, { recursive: true });

const log = (...a) => console.log(`[${name}]`, ...a);

// ---- virtual clock, installed before any page script
const clockScript = `(() => {
  let now = 1000;
  const dateBase = Date.now();
  let queue = new Map();
  let nextId = 0;
  performance.now = () => now;
  Date.now = () => dateBase + now;
  window.requestAnimationFrame = (cb) => { nextId += 1; queue.set(nextId, cb); return nextId; };
  window.cancelAnimationFrame = (id) => { queue.delete(id); };
  window.__advance = (ms) => {
    now += ms;
    const cbs = queue;
    queue = new Map();
    for (const cb of cbs.values()) {
      try { cb(now); } catch (e) { console.error("rAF callback failed", e); }
    }
    return queue.size;
  };
  window.__now = () => now;
  // Capture-only framing: three.js announces each WebGLRenderer on __THREE_DEVTOOLS__. Wrap the
  // stage renderer's render() so the camera draws a sub-window of a larger virtual frame
  // (PerspectiveCamera.setViewOffset) - pixel-identical to cropping a bigger render.
  window.__vo = null; // {cx, cy, z, A}: window centre (normalised), zoom, reference aspect
  const hook = new EventTarget();
  hook.addEventListener("observe", (e) => {
    const o = e.detail;
    if (!o || !o.isWebGLRenderer) return;
    const render = o.render.bind(o);
    o.render = (scene, cam) => {
      const v = window.__vo;
      const el = o.domElement;
      if (v && cam && cam.isPerspectiveCamera && el && el.closest && el.closest(".stage")) {
        const w = el.clientWidth, h = el.clientHeight;
        const fh = h * v.z, fw = fh * v.A;
        cam.aspect = fw / fh;
        cam.setViewOffset(fw, fh, v.cx * fw - w / 2, v.cy * fh - h / 2, w, h);
        window.__camInfo = { w, h, fov: cam.fov };
      }
      return render(scene, cam);
    };
  });
  window.__THREE_DEVTOOLS__ = hook;
})();`;

// ---- capture-only layout: the 3D stage fills the frame
const hudCss = noHud
  ? `.shotbar{display:none!important}`
  : `.shotbar{grid-template-columns:repeat(4,minmax(0,1fr))!important}
     .shotbar .cell{padding:10px 16px!important}
     .shotbar .cell .k{font-size:15px!important}
     .shotbar .cell .v{font-size:34px!important}
     .shotbar .cell .s{font-size:14px!important}`;
const brainAreas = keepBrain ? `"stage" "bar" "brain"` : `"stage" "bar"`;
const brainRows = keepBrain ? `minmax(0,1fr) auto auto` : `minmax(0,1fr) auto`;
const legacyCss = `
  .hdr{display:none!important}
  .showcase-controls{display:none!important}
  .splash,.showcase-splash{display:none!important}
  ${keepBrain ? `.brain{border-left:0!important;border-top:2px solid var(--line)!important;max-height:${Math.round(height * 0.3)}px;overflow:hidden!important}` : `.brain{display:none!important}`}
  .app{grid-template-columns:minmax(0,1fr)!important;grid-template-rows:${brainRows}!important;grid-template-areas:${brainAreas}!important;height:100vh!important}
  ${hudCss}
  ${brainfire ? `.firing{top:14px!important;right:14px!important;left:14px!important;width:auto!important}
                 .firing-card{max-height:none!important}` : `.firing{display:none!important}`}
  *{caret-color:transparent!important}
`;
// Cinema mode hides every panel itself; the brain-firing card (--brainfire) keeps the app's own
// cinema placement (full-width strip at <=1000 px viewports, 336 px top-right card wider).
// --brainfire in cinema mode: stretch the card across the top like the v1 (short-01) framing, so it
// reads on a phone instead of sitting in the corner as a 336 px card.
// Chrome that is unreadable at phone size and reads as a dashboard screenshot on camera: the
// close button, the legend, the mean-rate table and the explanatory footnote. The neuron map,
// the counter and its one-line caption stay.
const firingWideCss = `.firing.open{top:14px!important;right:14px!important;left:14px!important;width:auto!important}
                       .firing-card{max-height:none!important}
                       .firing-close,.firing-legend,.firing-readings,.firing-caption,.attribution{display:none!important}`;
const css = cinema ? `*{caret-color:transparent!important}${brainfire ? firingWideCss : ""}` : legacyCss;

const browser = await chromium.launch({
  headless: true,
  args: ["--enable-unsafe-swiftshader", "--ignore-gpu-blocklist"],
});
const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: dpr });
const page = await context.newPage();
page.on("pageerror", (e) => log("pageerror", e.message));
page.on("console", (m) => {
  if (m.type() === "error") log("console.error", m.text().slice(0, 300));
});
await page.addInitScript(clockScript);

const url = `${baseUrl}?run=${encodeURIComponent(run)}&shot=${shot}${cinema ? "&cinema=1" : ""}`;
log("open", url);
await page.goto(url, { waitUntil: "load" });
await page.addStyleTag({ content: css });
await page.evaluate((v) => (window.__vo = v), voAt(-1));

const realWait = (ms) => new Promise((r) => setTimeout(r, ms));
const advance = (ms) => page.evaluate((m) => window.__advance(m), ms);
// Let React's scheduler (MessageChannel, real time) commit any state set during the rAF.
const flush = () =>
  page.evaluate(
    () =>
      new Promise((r) => {
        const ch = new MessageChannel();
        ch.port1.onmessage = () => {
          const ch2 = new MessageChannel();
          ch2.port1.onmessage = () => r();
          ch2.port2.postMessage(0);
        };
        ch.port2.postMessage(0);
      }),
  );

const probe = () =>
  page.evaluate(() => {
    const txt = (s) => document.querySelector(s)?.textContent?.trim() ?? null;
    return {
      canvas: !!document.querySelector(".stage canvas"),
      phase: txt(".scrub-phase"),
      club: txt(".shotbar .cell.club .v"),
      toPin: txt(".shotbar .cell:nth-child(2) .v"),
      result: txt(".shotbar .cell.result .v"),
      title: txt(".now-title"),
      card: !!document.querySelector(".scorecard"),
      firing: !!document.querySelector(".firing-card"),
      cinema: !!document.querySelector(".app.cinema"),
    };
  });

// ---- settle: load run + course, let R3F initialise, let assets arrive
let st = await probe();
for (let i = 0; i < 400 && !(st.canvas && st.title); i++) {
  await advance(16);
  await realWait(40);
  st = await probe();
}
log("loaded", st);
for (let i = 0; i < 120; i++) {
  await advance(1000 / 30);
  await realWait(25);
}
if (st.card || (await probe()).card) await page.keyboard.press("c");
if (brainfire) await page.keyboard.press("b");
for (let i = 0; i < 60; i++) {
  await advance(1000 / 30);
  await realWait(25);
}
st = await probe();
log("ready", st);
// No-UI check: every visible element other than the stage canvas (and the brain-firing card
// when asked for) is reported. Cinema mode should leave nothing.
const visibleUi = await page.evaluate((allowFiring) => {
  const out = [];
  for (const el of document.querySelectorAll(".app *")) {
    if (el.closest(".stage canvas") || el.matches(".stage, .stage > div:has(canvas), .stage > div:has(canvas) *")) continue;
    if (allowFiring && el.closest(".firing")) continue;
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    if (r.width > 0 && r.height > 0 && cs.visibility !== "hidden" && Number(cs.opacity) > 0 && (el.textContent.trim() || el.tagName === "BUTTON" || el.tagName === "CANVAS"))
      out.push(`${el.tagName.toLowerCase()}.${[...el.classList].join(".")} ${Math.round(r.x)},${Math.round(r.y)} ${Math.round(r.width)}x${Math.round(r.height)}`);
  }
  return out;
}, brainfire);
if (cinema && !st.cinema) throw new Error("cinema mode did not engage");
if (visibleUi.length) log("WARNING visible UI:", visibleUi.slice(0, 20));
else log("no visible UI besides the stage", brainfire ? "(and the brain-firing card)" : "");
if (st.card) throw new Error("scorecard still open");
if (brainfire && !st.firing) log("WARNING: brain-firing card not open");

const frames = [];
const dt = 1000 / fps;
let n = 0;
const snap = async (t) => {
  await flush();
  if (every > 1 && n % every !== 0) { frames.push({ i: n, t: Number(t.toFixed(4)), phase: (await probe()).phase ?? "" }); n += 1; return; }
  const file = path.join(framesDir, `f${String(n).padStart(5, "0")}.png`);
  await page.screenshot({ path: file, type: "png" });
  const p = await probe();
  frames.push({ i: n, t: Number(t.toFixed(4)), phase: p.phase ?? "", club: p.club ?? "", result: p.result ?? "", to_pin: p.toPin ?? "" });
  n += 1;
};

// pre-roll (still view before Space)
const preFrames = Math.round(pre * fps);
for (let k = 0; k < preFrames; k++) {
  await snap((k - preFrames) * (1 / fps));
  await advance(dt);
}

await page.keyboard.press("Space");
// Frame 0 is playback t=0: the rAF right after the key press.
await advance(0.001);
let endedAt = null;
let sawPhase = false;
const maxFrames = Math.round(maxSeconds * fps);
const t0 = Date.now();
for (let k = 0; k < maxFrames; k++) {
  const t = k / fps;
  await snap(t);
  const ph = frames[frames.length - 1].phase;
  if (ph) sawPhase = true;
  if (sawPhase && !ph) {
    // Playback over: the app re-frames for the next shot here, so drop this frame and hold the
    // last playback frame instead (tpad clone at encode time).
    endedAt = t;
    const f = frames.pop();
    n -= 1;
    fs.rmSync(path.join(framesDir, `f${String(f.i).padStart(5, "0")}.png`), { force: true });
    break;
  }
  // two sub-steps: state updates in the first, a clean render at the frame time in the second
  if (frameKeys) await page.evaluate((v) => (window.__vo = v), voAt(t + 1 / fps));
  await advance(dt / 2);
  await advance(dt / 2);
  if (k % 30 === 0) log(`frame ${k} t=${t.toFixed(2)} phase=${ph} club=${frames.at(-1).club} (${((Date.now() - t0) / 1000).toFixed(0)}s)`);
}
await browser.close();

// ---- events (from every rendered frame, i.e. at 1/fps resolution)
const events = [];
let last;
for (const f of frames) {
  if (f.phase !== last) {
    events.push({ t: f.t, phase: f.phase || "(playback over)" });
    last = f.phase;
  }
}
const firstWhere = (pred) => frames.find(pred)?.t ?? null;
const clubRevealed = firstWhere((f) => f.t >= 0 && f.club && f.club !== "choosing…" && f.club !== "·" && frames.some((g) => g.t < f.t && g.club === "choosing…"));
const impact = firstWhere((f) => f.t >= 0 && (f.phase === "ball in the air" || f.phase === "ball rolling"));
const resultRevealed = firstWhere((f) => f.t >= 0 && f.result && f.result !== "…" && frames.some((g) => g.t < f.t && g.result === "…"));
// Ball events (lip-out, holed, ...) from the recorded trajectory; ball time 0 = impact.
let trajEvents = [];
let recordInfo = null;
try {
  const rec = (await (await fetch(`${baseUrl}showcase/runs/${run}.json`)).json()).shots[shot - 1];
  recordInfo = { shot_id: rec.shot_id, hole: rec.hole, stroke_number: rec.stroke_number, club: rec.stroke.club?.name, controller: rec.controller?.label, outcome: rec.outcome };
  trajEvents = (rec.trajectory.events ?? []).map((e) => ({ ...e, t_clip: impact !== null ? Number((impact + e.t).toFixed(4)) : null }));
} catch (e) {
  log("could not read run json", e.message);
}

// Writes one clip (json + mp4 + sheet) at outFps from every (fps/outFps)-th rendered frame.
const emit = (base, outFps) => {
  const decim = fps / outFps;
  const sel = frames.filter((f) => f.i % decim === 0);
  const holdFrames = endedAt !== null ? Math.round(hold * outFps) : 0;
  const meta = {
    run,
    shot,
    name: base,
    fps: outFps,
    capture_fps: fps,
    frames: sel.length + holdFrames,
    rendered_frames: sel.length,
    hold_frames_cloned: holdFrames,
    width: width * dpr,
    height: height * dpr,
    viewport: { width, height, device_scale_factor: dpr },
    duration_s: Number(((sel.length + holdFrames) / outFps).toFixed(3)),
    flags: { cinema, brainfire, keep_brain_panel: keepBrain, no_hud: noHud, pre_s: pre, hold_s: hold },
    note: "t is seconds from clip start; t=0 is the frame at which Space was pressed (playback time 0; with --pre, pre-roll frames have negative t and the mp4 starts at the first of them). After playback_end_t the last playback frame is held (cloned) for hold_frames_cloned frames, because the app re-frames to the next shot when playback ends." +
      (decim > 1 ? ` This clip keeps every ${decim}th frame of a ${fps} fps capture (same timeline); event times are at 1/${fps} s resolution.` : ""),
    events,
    club_revealed_t: clubRevealed,
    impact_t: impact,
    playback_end_t: endedAt,
    ball_events: trajEvents,
    ball_events_note: `t_clip = impact_t + trajectory event time (impact_t is the first ${fps} fps frame at/after impact, so +-1/${fps} s)`,
    record: recordInfo,
    result_revealed_t: resultRevealed,
    result_text: frames.at(-1)?.result ?? null,
    per_frame: sel.map((f, j) => ({ ...f, i: j })),
  };
  meta.framing = frameKeys
    ? { keys_t_cx_cy_zoom: frameKeys, reference_aspect: "16:9", method: "capture-only PerspectiveCamera.setViewOffset window of a virtual 16:9 frame (equivalent to cropping a larger render); app camera logic untouched" }
    : { method: "native app camera at this viewport" };
  fs.writeFileSync(path.join(outDir, `${base}.json`), JSON.stringify(meta, null, 1));
  // every rendered frame is f%05d.png at `fps`; a lower-rate clip keeps every decim-th one
  const input = ["-framerate", String(fps), "-i", path.join(framesDir, "f%05d.png")];
  const pick = decim > 1 ? `select='not(mod(n\\,${decim}))',setpts=N/${outFps}/TB,` : "";
  const mp4 = path.join(outDir, `${base}.mp4`);
  execFileSync(ffmpeg, [
    "-y", "-loglevel", "error", ...input,
    "-vf", `${pick}fps=${outFps}${holdFrames ? `,tpad=stop_mode=clone:stop=${holdFrames}` : ""}`,
    "-c:v", "libx264", "-preset", "slow", "-crf", String(outFps > 30 ? 16 : 18), "-pix_fmt", "yuv420p", "-r", String(outFps), "-an", "-movflags", "+faststart", mp4,
  ]);
  // contact sheet: 12 evenly spaced frames, 6x2, each scaled to 270 wide
  const step = Math.max(1, Math.floor(sel.length / 12));
  execFileSync(ffmpeg, [
    "-y", "-loglevel", "error", ...input,
    "-vf", `${pick}select='not(mod(n\\,${step}))',scale=270:-1,tile=6x2:padding=4:color=black`,
    "-frames:v", "1", "-update", "1", path.join(outDir, `${base}-sheet.png`),
  ]);
  log("wrote", mp4, `${sel.length}+${holdFrames} frames @${outFps}`);
};

if (every > 1) {
  fs.writeFileSync(path.join(outDir, `${name}.preview.json`), JSON.stringify({ events, impact, trajEvents, per_frame: frames }, null, 1));
  log("preview done", events);
  process.exit(0);
}
emit(fps === 30 ? name : `${name}-${fps}`, fps);
if (alsoFps && alsoFps !== fps) emit(alsoFps === 30 ? name : `${name}-${alsoFps}`, alsoFps);
log("done", events, { clubRevealed, impact, endedAt, resultRevealed, trajEvents });
