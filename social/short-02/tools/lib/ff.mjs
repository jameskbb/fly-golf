// ffmpeg helpers: locate the binary, run it, probe media without ffprobe (the static build ships only ffmpeg).
import { spawnSync, spawn } from "node:child_process";
import { existsSync, readFileSync, createWriteStream, appendFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const TOOLS = join(dirname(fileURLToPath(import.meta.url)), "..");

export function resolveFfmpeg() {
  const cands = [];
  if (process.env.FFMPEG) cands.push(process.env.FFMPEG);
  const pathFile = join(TOOLS, "ffmpeg-path.txt");
  if (existsSync(pathFile)) cands.push(readFileSync(pathFile, "utf8").trim());
  for (const c of cands) if (c && existsSync(c)) return c;
  const which = spawnSync("sh", ["-c", "command -v ffmpeg"], { encoding: "utf8" });
  if (which.status === 0 && which.stdout.trim()) return which.stdout.trim();
  throw new Error("ffmpeg not found: set FFMPEG=/path/to/ffmpeg or write its path to tools/ffmpeg-path.txt");
}

export const FF = resolveFfmpeg();

/** Run ffmpeg synchronously; returns stderr. Throws with the tail of stderr on failure. */
export function ff(args, { log } = {}) {
  const r = spawnSync(FF, ["-hide_banner", ...args], { encoding: "utf8", maxBuffer: 1 << 28 });
  if (log) appendFileSync(log, `$ ffmpeg ${args.map(a => (/[\s;'"]/.test(a) ? JSON.stringify(a) : a)).join(" ")}\n${r.stderr}\n`);
  if (r.status !== 0) {
    const tail = (r.stderr || "").split("\n").slice(-25).join("\n");
    throw new Error(`ffmpeg failed (exit ${r.status}):\n${tail}`);
  }
  return r.stderr || "";
}

/** Run ffmpeg asynchronously, streaming stderr to a log file; resolves with stderr text. */
export function ffAsync(args, logPath) {
  return new Promise((resolve, reject) => {
    const p = spawn(FF, ["-hide_banner", ...args]);
    const out = logPath ? createWriteStream(logPath) : null;
    let err = "";
    p.stderr.on("data", d => { err += d; out?.write(d); if (err.length > 4e6) err = err.slice(-2e6); });
    p.on("close", code => {
      out?.end();
      if (code === 0) resolve(err);
      else reject(new Error(`ffmpeg failed (exit ${code}); see ${logPath}\n${err.split("\n").slice(-25).join("\n")}`));
    });
  });
}

/** Probe a media file via `ffmpeg -i` stderr: duration (s), video w/h/fps, audio presence. */
export function probe(file) {
  const r = spawnSync(FF, ["-hide_banner", "-i", file], { encoding: "utf8" });
  const s = r.stderr || "";
  if (/No such file|Invalid data/.test(s)) throw new Error(`cannot read ${file}: ${s.split("\n").slice(-2).join(" ")}`);
  const d = s.match(/Duration: (\d+):(\d+):(\d+(?:\.\d+)?)/);
  const v = s.match(/Stream #\d+:\d+.*?: Video: ([^,]+).*?, (\d{2,5})x(\d{2,5})/);
  const fps = s.match(/, (\d+(?:\.\d+)?) fps/) || s.match(/, (\d+(?:\.\d+)?) tbr/);
  const info = {
    duration: d ? (+d[1]) * 3600 + (+d[2]) * 60 + parseFloat(d[3]) : NaN,
    vcodec: v?.[1]?.trim(), width: v ? +v[2] : 0, height: v ? +v[3] : 0,
    fps: fps ? parseFloat(fps[1]) : NaN,
    audio: /Stream #\d+:\d+.*?: Audio:/.test(s),
    raw: s,
  };
  if (!Number.isFinite(info.duration)) {
    // Container without a duration header (e.g. some live-recorded webm): decode to find the last timestamp.
    const dec = spawnSync(FF, ["-hide_banner", "-i", file, "-map", "0:v:0", "-f", "null", "-"], { encoding: "utf8" });
    const m = [...(dec.stderr || "").matchAll(/time=(\d+):(\d+):(\d+(?:\.\d+)?)/g)].pop();
    if (m) info.duration = (+m[1]) * 3600 + (+m[2]) * 60 + parseFloat(m[3]);
  }
  return info;
}

/** EBU R128 measurement of a file's audio: integrated LUFS, LRA, true peak dBTP. */
export function loudness(file) {
  const s = ff(["-nostats", "-i", file, "-map", "0:a:0", "-af", "ebur128=peak=true:framelog=quiet", "-f", "null", "-"]);
  const sum = s.slice(s.lastIndexOf("Summary:"));
  const num = re => { const m = sum.match(re); return m ? parseFloat(m[1]) : NaN; };
  return { I: num(/I:\s+(-?[\d.]+|-inf) LUFS/), LRA: num(/LRA:\s+(-?[\d.]+) LU/), TP: num(/Peak:\s+(-?[\d.]+|-inf) dBFS/) };
}
