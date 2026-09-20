#!/usr/bin/env node
// Fly Golf short renderer: edl.json + clips -> 1080x1920 30 fps H.264/AAC MP4 with burned-in captions and SFX.
//
//   node tools/render.mjs [path/to/edl.json] [--out render/x.mp4] [--draft] [--debug-captions] [--no-review]
//
// Pipeline (see tools/RENDER.md): validate EDL (ffmpeg-based probe) -> synthesize SFX if missing ->
// captions to PNG via Playwright -> SFX mix + loudness normalisation -> one ffmpeg filter_complex
// (trim/speed, cover-crop, smooth sub-pixel zoom, hard-cut concat, caption overlays with pop-in) ->
// verification (duration, size, fps, audio, loudness) -> poster.png + contact.png.
import { existsSync, mkdirSync, readFileSync, writeFileSync, rmSync } from "node:fs";
import { dirname, join, resolve, basename, isAbsolute, relative } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { spawnSync } from "node:child_process";
import { FF, ff, ffAsync, probe, loudness } from "./lib/ff.mjs";
import { renderCaptions } from "./lib/captions.mjs";

const TOOLS = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(TOOLS, "..");                  // social/short-02
const AUDIO = join(ROOT, "audio");
const PLAYWRIGHT = process.env.PLAYWRIGHT_MODULE ||
  "/home/james/.nvm/versions/node/v24.21.0/lib/node_modules/playwright/index.mjs";

// ---------- args ----------
const argv = process.argv.slice(2);
const flag = f => { const i = argv.indexOf(f); if (i >= 0) { argv.splice(i, 1); return true; } return false; };
const opt = f => { const i = argv.indexOf(f); if (i >= 0) { const v = argv[i + 1]; argv.splice(i, 2); return v; } return undefined; };
const DRAFT = flag("--draft");
const DEBUG_CAPS = flag("--debug-captions");
const NO_REVIEW = flag("--no-review");
const outArg = opt("--out");
const edlPath = resolve(argv[0] || join(ROOT, "edl.json"));
const edlDir = dirname(edlPath);
const stem = basename(edlPath, ".json") === "edl" ? "fly-golf-short-02" : basename(edlPath, ".json");
const OUT = resolve(outArg || join(ROOT, "render", `${stem}${DRAFT ? "-draft" : ""}.mp4`));
const RENDER_DIR = dirname(OUT);
const REVIEW_PREFIX = stem === "fly-golf-short-02" && !DRAFT ? "" : `${basename(OUT, ".mp4")}-`;
const WORK = join(ROOT, "render", "_work", basename(OUT, ".mp4"));
mkdirSync(WORK, { recursive: true });
mkdirSync(RENDER_DIR, { recursive: true });
const LOG = join(WORK, "render.log");
writeFileSync(LOG, `render ${new Date().toISOString()} edl=${edlPath}\nffmpeg=${FF}\n`);

const SFX_DEFAULT_GAIN = { whoosh: -8, impact: -4, click: -10, neural: -9, pop: -16, clink: -6, womp: -9, vineboom: -4, music: -6, cheer: -15, ooh: -15 };
const STYLES = new Set(["hook", "big", "normal", "small", "end"]);
const POSES = new Set(["top", "upper", "middle", "lower"]);
// "@" = segment progress 0..1
const EASES = { linear: "@", inout: "(0.5-0.5*cos(PI*@))", out: "sin(PI/2*@)", in: "(1-cos(PI/2*@))" };

const step = (s) => console.log(`\n== ${s}`);
const fmt = (x, d = 3) => Number(x).toFixed(d);

// ---------- load + validate ----------
step(`EDL ${relative(process.cwd(), edlPath) || edlPath}`);
if (!existsSync(edlPath)) die(`EDL not found: ${edlPath}`);
let edl;
try { edl = JSON.parse(readFileSync(edlPath, "utf8")); } catch (e) { die(`EDL is not valid JSON: ${e.message}`); }
const FPS = edl.fps ?? 30, W = edl.width ?? 1080, H = edl.height ?? 1920, D = edl.duration;
const NF = Math.round(D * FPS);
const fr = t => Math.round(t * FPS);           // seconds -> frame index on the output grid
const clipPath = c => (isAbsolute(c) ? c : resolve(edlDir, c));

function die(msg) { console.error(`\nEDL/RENDER ERROR:\n${msg}\n`); process.exit(1); }

function validate() {
  const errs = [], warns = [];
  const eps = 1e-3;
  if (!(FPS > 0)) errs.push(`fps must be > 0 (got ${edl.fps})`);
  if (!(W > 0 && H > 0 && W % 2 === 0 && H % 2 === 0)) errs.push(`width/height must be positive even numbers (got ${W}x${H})`);
  if (!(D > 0)) errs.push(`duration must be > 0 (got ${edl.duration})`);
  if (Math.abs(D * FPS - NF) > 1e-6) errs.push(`duration ${D}s is not a whole number of frames at ${FPS} fps`);
  const segs = edl.segments;
  if (!Array.isArray(segs) || !segs.length) errs.push("segments: must be a non-empty array");
  const probes = {};
  (segs || []).forEach((s, i) => {
    const tag = `segments[${i}]${s.note ? ` (${s.note})` : ""}`;
    if (!(s.t1 > s.t0)) errs.push(`${tag}: t1 (${s.t1}) must be > t0 (${s.t0})`);
    const prevEnd = i === 0 ? 0 : segs[i - 1].t1;
    if (Math.abs(s.t0 - prevEnd) > eps) errs.push(`${tag}: t0=${s.t0} but ${i === 0 ? "the timeline starts at 0" : `previous segment ends at ${prevEnd}`} (segments must be contiguous, no gaps/overlaps)`);
    if (fr(s.t1) - fr(s.t0) < 1) errs.push(`${tag}: shorter than one frame`);
    if (Math.abs(s.t0 * FPS - fr(s.t0)) > 0.01) warns.push(`${tag}: t0=${s.t0} is not on the ${FPS} fps frame grid; cut snapped to frame ${fr(s.t0)} (${fmt(fr(s.t0) / FPS)}s)`);
    const speed = s.speed ?? 1;
    if (!(speed > 0)) errs.push(`${tag}: speed must be > 0`);
    const z = s.zoom ?? [1, 1];
    if (!Array.isArray(z) || z.length !== 2 || !(z[0] >= 1 && z[1] >= 1)) errs.push(`${tag}: zoom must be [start,end] with values >= 1.0 (got ${JSON.stringify(s.zoom)})`);
    const f = s.focus ?? [0.5, 0.5];
    if (!Array.isArray(f) || f.length !== 2 || f.some(v => !(v >= 0 && v <= 1))) errs.push(`${tag}: focus must be [x,y] in 0..1 (got ${JSON.stringify(s.focus)})`);
    if (s.ease && !EASES[s.ease]) errs.push(`${tag}: ease must be one of ${Object.keys(EASES).join("/")}`);
    if (typeof s.clip !== "string") { errs.push(`${tag}: clip missing`); return; }
    const p = clipPath(s.clip);
    if (!existsSync(p)) { errs.push(`${tag}: clip not found: ${p}`); return; }
    let info;
    try { info = probes[p] ??= probe(p); } catch (e) { errs.push(`${tag}: ${e.message}`); return; }
    if (!info.width) { errs.push(`${tag}: no video stream in ${s.clip}`); return; }
    const inT = s.in ?? 0;
    const need = (fr(s.t1) - fr(s.t0)) / FPS * speed;
    if (!(inT >= 0)) errs.push(`${tag}: in must be >= 0`);
    if (inT + need > info.duration + 0.02)
      errs.push(`${tag}: needs source ${fmt(inT)}..${fmt(inT + need)}s of ${s.clip} but the clip is only ${fmt(info.duration)}s long` +
        ` (over by ${fmt(inT + need - info.duration)}s; lower "in", "speed" or the segment length)`);
    if (!info.warned) {
      info.warned = true;
      if (Math.abs(info.width / info.height - W / H) > 0.01)
        warns.push(`${basename(p)} is ${info.width}x${info.height}, not ${W}:${H} -> cover-cropped around each segment's focus (never letterboxed)`);
      const sc = Math.max(W / info.width, H / info.height);
      if (sc > 1.01) warns.push(`${basename(p)} is upscaled ${fmt(sc, 2)}x to cover ${W}x${H}; expect softness`);
    }
  });
  if (segs?.length && Math.abs(segs[segs.length - 1].t1 - D) > eps) errs.push(`segments end at ${segs[segs.length - 1].t1} but duration is ${D}`);
  (edl.captions || []).forEach((c, i) => {
    const tag = `captions[${i}] ${JSON.stringify(c.text)}`;
    if (typeof c.text !== "string" || !c.text.trim()) errs.push(`captions[${i}]: text missing`);
    if (!STYLES.has(c.style)) errs.push(`${tag}: style must be one of ${[...STYLES].join("/")} (got ${c.style})`);
    if (c.style !== "end" && !POSES.has(c.pos ?? "middle")) errs.push(`${tag}: pos must be one of ${[...POSES].join("/")}`);
    if (!(c.t1 > c.t0) || c.t0 < 0 || c.t1 > D + eps) errs.push(`${tag}: needs 0 <= t0 < t1 <= duration (got ${c.t0}..${c.t1})`);
    if ((c.text.match(/\*/g) || []).length % 2) errs.push(`${tag}: unbalanced *highlight* markers`);
    if (c.title_t0 != null && !(c.title_t0 >= c.t0 && c.title_t0 < c.t1)) errs.push(`${tag}: title_t0 must lie inside the caption`);
  });
  const caps = (edl.captions || []).filter(c => c.style !== "end").sort((a, b) => a.t0 - b.t0);
  for (let i = 1; i < caps.length; i++)
    if (caps[i].t0 < caps[i - 1].t1 - eps && (caps[i].pos ?? "middle") === (caps[i - 1].pos ?? "middle"))
      warns.push(`captions ${JSON.stringify(caps[i - 1].text)} and ${JSON.stringify(caps[i].text)} overlap in time at the same pos (${caps[i].pos ?? "middle"})`);
  (edl.sfx || []).forEach((x, i) => {
    const tag = `sfx[${i}] ${x.name}`;
    if (!/^[\w-]+$/.test(x.name || "")) errs.push(`${tag}: name must be a file stem in audio/ (e.g. whoosh)`);
    if (!(x.t >= 0 && x.t < D)) errs.push(`${tag}: t=${x.t} outside 0..${D}`);
    if (x.gain_db != null && !Number.isFinite(x.gain_db)) errs.push(`${tag}: gain_db must be a number`);
    if (/^[\w-]+$/.test(x.name || "") && !SFX_DEFAULT_GAIN[x.name] && !existsSync(join(AUDIO, `${x.name}.wav`)))
      errs.push(`${tag}: unknown sfx (synthesized: ${Object.keys(SFX_DEFAULT_GAIN).join(" ")}; or add audio/${x.name}.wav)`);
  });
  for (const w of warns) console.log(`  warn: ${w}`);
  if (errs.length) die(errs.map(e => `  - ${e}`).join("\n"));
  console.log(`  ok: ${segs.length} segments, ${(edl.captions || []).length} captions, ${(edl.sfx || []).length} sfx, ${D}s = ${NF} frames @ ${FPS} fps`);
  return probes;
}
const probes = validate();

// ---------- SFX ----------
step("SFX");
const needSfx = [...new Set((edl.sfx || []).map(x => x.name))];
if (needSfx.some(n => !existsSync(join(AUDIO, `${n}.wav`)))) {
  const r = spawnSync("bash", [join(TOOLS, "make-sfx.sh")], { stdio: "inherit", env: { ...process.env, FFMPEG: FF } });
  if (r.status !== 0) die("tools/make-sfx.sh failed");
}
const missing = needSfx.filter(n => !existsSync(join(AUDIO, `${n}.wav`)));
if (missing.length) die(`unknown sfx: ${missing.join(", ")} (available: whoosh impact click neural pop clink womp vineboom music cheer ooh, or drop a <name>.wav into audio/)`);

const TARGET_LUFS = edl.audio?.target_lufs ?? -16;
const CEIL_DBTP = edl.audio?.ceiling_dbtp ?? -1.5;
const mixRaw = join(WORK, "sfx-mix-raw.wav"), mix = join(WORK, "sfx-mix.wav");
{
  const args = ["-y"], fc = [];
  const ev = (edl.sfx || []).slice().sort((a, b) => a.t - b.t);
  ev.forEach((x, k) => {
    args.push("-i", join(AUDIO, `${x.name}.wav`));
    const g = x.gain_db ?? SFX_DEFAULT_GAIN[x.name] ?? -8;
    const ms = Math.round(x.t * 1000);
    fc.push(`[${k}:a]aformat=sample_fmts=fltp:sample_rates=48000:channel_layouts=stereo,volume=${g}dB,adelay=${ms}:all=1[a${k}]`);
  });
  if (ev.length) fc.push(`${ev.map((_, k) => `[a${k}]`).join("")}amix=inputs=${ev.length}:normalize=0:duration=longest,apad=whole_dur=${D},atrim=end=${D}[m]`);
  else fc.push(`anullsrc=r=48000:cl=stereo,atrim=end=${D}[m]`);
  ff([...args, "-filter_complex", fc.join(";"), "-map", "[m]", "-c:a", "pcm_f32le", mixRaw], { log: LOG });
  if (ev.length) {
    const m = loudness(mixRaw);
    let gain = TARGET_LUFS - m.I;
    // Sparse SFX gate to their own loudness; if hitting the LUFS target would push peaks past the ceiling,
    // a transparent-ish limiter catches the few transient peaks.
    const needLimit = m.TP + gain > CEIL_DBTP;
    const lim = Math.pow(10, (CEIL_DBTP - 0.3) / 20);
    const chain = `volume=${fmt(gain, 2)}dB${needLimit ? `,alimiter=limit=${fmt(lim, 4)}:attack=0.5:release=40:level=false` : ""}`;
    ff(["-y", "-i", mixRaw, "-af", chain, "-c:a", "pcm_f32le", mix], { log: LOG });
    let m2 = loudness(mix);
    if (Math.abs(m2.I - TARGET_LUFS) > 0.5) {  // limiter ate some loudness: one corrective pass
      gain += TARGET_LUFS - m2.I;
      ff(["-y", "-i", mixRaw, "-af", `volume=${fmt(gain, 2)}dB,alimiter=limit=${fmt(lim, 4)}:attack=0.5:release=40:level=false`, "-c:a", "pcm_f32le", mix], { log: LOG });
      m2 = loudness(mix);
    }
    console.log(`  ${ev.length} events; raw ${fmt(m.I, 1)} LUFS / ${fmt(m.TP, 1)} dBTP -> gain ${fmt(gain, 1)} dB${needLimit ? " + limiter" : ""} -> ${fmt(m2.I, 1)} LUFS / ${fmt(m2.TP, 1)} dBTP`);
  } else {
    ff(["-y", "-i", mixRaw, "-c:a", "pcm_f32le", mix], { log: LOG });
    console.log("  no sfx: silent stereo track");
  }
}

// ---------- captions ----------
step("captions");
const capResults = await renderCaptions(edl.captions || [], join(ROOT, "captions"), { debug: DEBUG_CAPS });
if (!capResults.length) console.log("  (none)");

// ---------- video filtergraph ----------
step("video");
const inputs = [], fc = [];
const addInput = (...a) => { inputs.push(...a); return inputs.filter(x => x === "-i").length - 1; };

edl.segments.forEach((s, i) => {
  const p = clipPath(s.clip), info = probes[p];
  const n = fr(s.t1) - fr(s.t0);
  const speed = s.speed ?? 1, inT = s.in ?? 0;
  const need = n / FPS * speed;
  const idx = addInput("-ss", fmt(inT, 4), "-t", fmt(need + 1.0, 4), "-i", p);
  // Cover-crop in source pixels (never letterbox), centred on focus.
  const [fx, fy] = s.focus ?? [0.5, 0.5];
  const sc = Math.max(W / info.width, H / info.height);
  let cw = Math.min(info.width, Math.round(W / sc)), ch = Math.min(info.height, Math.round(H / sc));
  cw -= cw % 2; ch -= ch % 2;
  const cx = Math.round(Math.min(Math.max(fx * info.width - cw / 2, 0), info.width - cw));
  const cy = Math.round(Math.min(Math.max(fy * info.height - ch / 2, 0), info.height - ch));
  const ffx = (fx * info.width - cx) / cw, ffy = (fy * info.height - cy) / ch;   // focus inside the crop
  const [z0, z1] = s.zoom ?? [1, 1];
  const chain = [
    `setpts=(PTS-STARTPTS)/${speed}`,
    `fps=${FPS}`,
    `tpad=stop_mode=clone:stop_duration=2`,         // guarantees the exact frame count even at clip end
    `trim=end_frame=${n}`,
    `setpts=N/${FPS}/TB`,
    `crop=${cw}:${ch}:${cx}:${cy}`,
  ];
  if (!(z0 === 1 && z1 === 1)) {
    // Smooth sub-pixel zoom: perspective maps a shrinking source window onto the full frame (no integer
    // crop steps, so no zoompan-style jitter). P = progress 0..1 over the segment, eased.
    const P = n > 1 ? `min((in-1)/${n - 1},1)` : "1";   // perspective's "in" counts from 1
    const e = (EASES[s.ease ?? "inout"]).replaceAll("@", `(${P})`);
    const z = z0 === z1 ? `${z0}` : `(${z0}+(${z1 - z0})*${e})`;
    const hw = `(W/2/${z})`, hh = `(H/2/${z})`;
    const cxe = `clip(${ffx}*W,${hw},W-${hw})`, cye = `clip(${ffy}*H,${hh},H-${hh})`;
    const X0 = `${cxe}-${hw}`, X1 = `${cxe}+${hw}`, Y0 = `${cye}-${hh}`, Y1 = `${cye}+${hh}`;
    chain.push(`perspective=x0='${X0}':y0='${Y0}':x1='${X1}':y1='${Y0}':x2='${X0}':y2='${Y1}':x3='${X1}':y3='${Y1}':interpolation=cubic:sense=source:eval=frame`);
  }
  chain.push(`scale=${W}:${H}:flags=lanczos`, "setsar=1", "format=yuv420p");
  fc.push(`[${idx}:v]${chain.join(",")}[s${i}]`);
  console.log(`  seg ${i}: ${fmt(fr(s.t0) / FPS)}-${fmt(fr(s.t1) / FPS)}s  ${n}f  ${basename(p)} @${fmt(inT)}s x${speed}  crop ${cw}x${ch}+${cx}+${cy}  zoom ${z0}->${z1}${s.note ? `  "${s.note}"` : ""}`);
});
fc.push(`${edl.segments.map((_, i) => `[s${i}]`).join("")}concat=n=${edl.segments.length}:v=1:a=0[base0]`);

// Caption layers: looped PNG, shifted to its start time, pop-in (scale about centre via perspective in
// destination sense on the padded transparent canvas) + alpha fade, overlaid only while active.
let cur = "base0", li = 0;
const layerPlan = [];
for (const cr of capResults) {
  const c = cr.caption;
  for (const L of cr.layers) {
    let t0 = c.t0, t1 = c.t1, pop = 0.13, s0 = 0.8, fadeIn = 0.06, fadeOut = 0.07;
    if (c.style === "end") {
      if (L.name === "dim") { pop = 0; fadeIn = 0.3; fadeOut = 0; }
      if (L.name === "question") { pop = 0.16; s0 = 0.9; }
      if (L.name === "title") { t0 = c.title_t0 ?? Math.min(c.t0 + 1.0, c.t1 - 0.5); pop = 0.16; s0 = 0.8; }
    }
    if (c.pop === false) pop = 0;
    if (t0 < 0.5 / FPS) { pop = 0; fadeIn = 0; }   // on screen from frame 1 (the hook/poster frame): no animation
    const T0 = fr(t0) / FPS, T1 = fr(t1) / FPS;
    if (t1 >= D - 1e-6) fadeOut = 0;                 // hold to the last frame
    layerPlan.push({ L, T0, T1, pop, s0, fadeIn, fadeOut });
  }
}
// draw the end-card dim first so other captions sit on top of it
layerPlan.sort((a, b) => (b.L.name === "dim") - (a.L.name === "dim"));
for (const { L, T0, T1, pop, s0, fadeIn, fadeOut } of layerPlan) {
  const dur = T1 - T0;
  const idx = addInput("-loop", "1", "-framerate", String(FPS), "-t", fmt(dur + 1 / FPS, 4), "-i", L.png);
  const ch = [`format=rgba`, `setpts=PTS-STARTPTS+${fmt(T0, 4)}/TB`];
  if (pop > 0) {
    const nPop = Math.max(2, Math.round(pop * FPS));
    // easeOutBack from s0 to 1 (slight overshoot), about the canvas centre
    const p = `min((in-1)/${nPop},1)`;
    const S = `(${s0}+(1-${s0})*(1+2.70158*pow(${p}-1,3)+1.70158*pow(${p}-1,2)))`;
    const x0 = `W/2-W/2*${S}`, x1 = `W/2+W/2*${S}`, y0 = `H/2-H/2*${S}`, y1 = `H/2+H/2*${S}`;
    ch.push(`perspective=x0='${x0}':y0='${y0}':x1='${x1}':y1='${y0}':x2='${x0}':y2='${y1}':x3='${x1}':y3='${y1}':interpolation=cubic:sense=destination:eval=frame:enable='lte(n,${nPop})'`, "format=rgba");
  }
  // fade starts one frame early so the caption's first frame is already ~half visible (fade's own first
  // frame would otherwise be fully transparent and hide the smallest pop-in frame)
  if (fadeIn > 0) ch.push(`fade=t=in:st=${fmt(T0 - 1 / FPS, 4)}:d=${fmt(fadeIn + 1 / FPS, 4)}:alpha=1`);
  if (fadeOut > 0) ch.push(`fade=t=out:st=${fmt(T1 - fadeOut, 4)}:d=${fadeOut}:alpha=1`);
  fc.push(`[${idx}:v]${ch.join(",")}[c${li}]`);
  const next = `v${li}`;
  fc.push(`[${cur}][c${li}]overlay=x=${L.x}:y=${L.y}:eof_action=pass:enable='between(t,${fmt(T0 - 0.001, 4)},${fmt(T1 - 0.001, 4)})'[${next}]`);
  cur = next; li++;
}
fc.push(`[${cur}]scale=out_color_matrix=bt709:out_range=tv,format=yuv420p[vout]`);
const aIdx = addInput("-i", mix);

const filterFile = join(WORK, "filter_complex.txt");
writeFileSync(filterFile, fc.join(";\n"));
const encArgs = [
  "-y", ...inputs,
  "-filter_complex_script", filterFile,
  "-map", "[vout]", "-map", `${aIdx}:a`,
  "-c:v", "libx264", "-preset", DRAFT ? "veryfast" : "slow", "-crf", DRAFT ? "26" : String(edl.crf ?? 18),
  "-profile:v", "high", "-pix_fmt", "yuv420p", "-r", String(FPS), "-frames:v", String(NF),
  "-colorspace", "bt709", "-color_primaries", "bt709", "-color_trc", "bt709", "-color_range", "tv",
  "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2", "-t", fmt(D, 4),
  "-movflags", "+faststart", "-map_metadata", "-1", "-fflags", "+bitexact", "-flags:v", "+bitexact", "-flags:a", "+bitexact",
  OUT,
];
writeFileSync(join(WORK, "ffmpeg-args.json"), JSON.stringify([FF, ...encArgs], null, 1));
const t0 = Date.now();
await ffAsync(encArgs, join(WORK, "encode.log"));
console.log(`  encoded ${relative(ROOT, OUT)} in ${fmt((Date.now() - t0) / 1000, 1)}s`);

// ---------- verify ----------
step("verify");
const info = probe(OUT);
const frames = (() => {
  // one framecrc line per video packet (= frame for H.264 without B-frame reordering issues)
  const r = spawnSync(FF, ["-hide_banner", "-loglevel", "error", "-i", OUT, "-map", "0:v:0", "-c", "copy", "-f", "framecrc", "-"], { encoding: "utf8", maxBuffer: 1 << 26 });
  return r.status === 0 ? r.stdout.split("\n").filter(l => l && !l.startsWith("#")).length : NaN;
})();
const loud = loudness(OUT);
const report = {
  file: OUT, duration: info.duration, width: info.width, height: info.height, fps: info.fps, frames,
  expected_frames: NF, audio: info.audio, loudness_lufs: loud.I, true_peak_dbtp: loud.TP, lra: loud.LRA,
  video: (info.raw.match(/Video: .*/) || [""])[0].trim(), audio_stream: (info.raw.match(/Audio: .*/) || [""])[0].trim(),
};
writeFileSync(join(RENDER_DIR, `${basename(OUT, ".mp4")}.report.json`), JSON.stringify(report, null, 2));
const checks = [
  [`size ${info.width}x${info.height}`, info.width === W && info.height === H],
  [`fps ${info.fps}`, Math.abs(info.fps - FPS) < 0.01],
  [`frames ${frames}/${NF}`, frames === NF],
  [`duration ${fmt(info.duration)}s`, Math.abs(info.duration - D) < 0.05],
  [`audio ${info.audio ? "present" : "MISSING"}`, info.audio],
  [`loudness ${fmt(loud.I, 1)} LUFS (target ${TARGET_LUFS})`, !(edl.sfx || []).length || Math.abs(loud.I - TARGET_LUFS) < 1.0],
  [`true peak ${fmt(loud.TP, 1)} dBTP`, !(loud.TP > -0.5)],
];
for (const [k, ok] of checks) console.log(`  ${ok ? "ok  " : "FAIL"} ${k}`);

// ---------- review images ----------
if (!NO_REVIEW) {
  step("review images");
  const poster = join(RENDER_DIR, `${REVIEW_PREFIX}poster.png`);
  ff(["-y", "-i", OUT, "-frames:v", "1", "-update", "1", poster]);
  const times = Array.from({ length: 12 }, (_, k) => fr((k + 0.5) * D / 12));
  rmSync(join(WORK, "contact"), { recursive: true, force: true });
  mkdirSync(join(WORK, "contact"));
  ff(["-y", "-i", OUT, "-vf", `select='${times.map(n => `eq(n\\,${n})`).join("+")}',scale=360:640:flags=lanczos`,
      "-fps_mode", "passthrough", join(WORK, "contact", "f%02d.png")]);
  const cells = times.map((n, k) => {
    const cap = (edl.captions || []).filter(c => n / FPS >= c.t0 && n / FPS < c.t1).map(c => c.text.replace(/\*/g, "")).join(" / ");
    const seg = edl.segments.find(s => n / FPS >= s.t0 && n / FPS < s.t1);
    return `<figure><img src="${pathToFileURL(join(WORK, "contact", `f${String(k + 1).padStart(2, "0")}.png`)).href}"><figcaption><b>${fmt(n / FPS, 2)}s</b> ${esc(seg?.note || "")}${cap ? `<br><i>${esc(cap)}</i>` : ""}</figcaption></figure>`;
  }).join("");
  const html = `<!doctype html><meta charset=utf-8><style>body{margin:0;background:#111;color:#ddd;font:15px/1.3 "DejaVu Sans",sans-serif;width:${6 * 376 + 16}px;padding:16px 0 8px 16px;box-sizing:border-box}
    h1{font-size:18px;margin:0 0 10px;color:#ffc81e}figure{display:inline-block;vertical-align:top;margin:0 16px 14px 0;width:360px}img{display:block;width:360px;height:640px;border-radius:6px}
    figcaption{margin-top:5px;height:3.9em;overflow:hidden}</style><h1>${esc(basename(OUT))} · ${fmt(info.duration, 2)}s · ${info.width}x${info.height}@${info.fps} · ${fmt(loud.I, 1)} LUFS · ${fmt(loud.TP, 1)} dBTP</h1>${cells}`;
  const htmlPath = join(WORK, "contact.html");
  writeFileSync(htmlPath, html);
  const { chromium } = await import(PLAYWRIGHT);
  const browser = await chromium.launch({ args: ["--disable-gpu"] });
  const page = await browser.newPage({ viewport: { width: 6 * 376 + 16, height: 800 } });
  await page.goto(pathToFileURL(htmlPath).href);
  const contact = join(RENDER_DIR, `${REVIEW_PREFIX}contact.png`);
  await page.screenshot({ path: contact, fullPage: true });
  await browser.close();
  console.log(`  ${relative(ROOT, poster)}, ${relative(ROOT, contact)}`);
}
function esc(s) { return String(s).replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }

const failed = checks.filter(([, ok]) => !ok);
console.log(failed.length ? `\nDONE WITH ${failed.length} FAILED CHECK(S): ${OUT}` : `\nDONE: ${OUT}`);
process.exit(failed.length ? 2 : 0);
