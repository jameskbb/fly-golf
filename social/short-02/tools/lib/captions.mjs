// Render EDL captions to transparent PNG layers with Playwright + tools/caption.html.
// Each caption -> one or more layers {png, x, y, w, h} in video-frame coordinates (x/y may be negative:
// PNGs are padded so the stroke, shadow and pop-in overshoot are never clipped).
// Results are cached by content hash in captions/, so re-renders only redo changed captions.
import { createHash } from "node:crypto";
import { existsSync, readFileSync, writeFileSync, mkdirSync, readdirSync, statSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";

const TOOLS = join(dirname(fileURLToPath(import.meta.url)), "..");
const TEMPLATE = join(TOOLS, "caption.html");
const EMOJI_DIR = join(TOOLS, "emoji");
const PLAYWRIGHT = process.env.PLAYWRIGHT_MODULE ||
  "/home/james/.nvm/versions/node/v24.21.0/lib/node_modules/playwright/index.mjs";

function templateHash() {
  const h = createHash("sha1");
  h.update(readFileSync(TEMPLATE));
  for (const dir of ["fonts", "emoji"]) {
    for (const f of readdirSync(join(TOOLS, dir)).sort()) h.update(f + statSync(join(TOOLS, dir, f)).size);
  }
  return h.digest("hex").slice(0, 10);
}

/** Make sure a Twemoji SVG exists locally for every emoji used; download from jsDelivr if missing. */
async function ensureEmoji(texts) {
  const map = {};
  for (const t of texts) {
    for (const m of t.matchAll(/\p{Extended_Pictographic}/gu)) {
      const cp = m[0].codePointAt(0).toString(16);
      const file = join(EMOJI_DIR, `${cp}.svg`);
      if (!existsSync(file)) {
        const url = `https://cdn.jsdelivr.net/gh/jdecked/twemoji@latest/assets/svg/${cp}.svg`;
        const res = await fetch(url);
        if (!res.ok) throw new Error(`emoji U+${cp.toUpperCase()} has no local SVG and ${url} returned ${res.status}`);
        writeFileSync(file, Buffer.from(await res.arrayBuffer()));
        console.log(`  fetched Twemoji ${cp}.svg`);
      }
      map[cp] = pathToFileURL(file).href;
    }
  }
  return map;
}

export async function renderCaptions(captions, outDir, { debug = false } = {}) {
  mkdirSync(outDir, { recursive: true });
  const th = templateHash();
  const jobs = captions.map((c, i) => {
    const spec = { text: c.text, style: c.style, pos: c.pos || "middle", title: c.title, url: c.url };
    const key = createHash("sha1").update(th + JSON.stringify(spec)).digest("hex").slice(0, 12);
    return { i, c, spec, key, meta: join(outDir, `${key}.json`) };
  });
  const todo = jobs.filter(j => !existsSync(j.meta) || debug);
  if (todo.length) {
    const emojiMap = await ensureEmoji(todo.flatMap(j => [j.spec.text, j.spec.title ?? (j.spec.style === "end" ? "FLY GOLF 🪰⛳" : "")]));
    const { chromium } = await import(PLAYWRIGHT);
    const browser = await chromium.launch({ args: ["--disable-gpu", "--font-render-hinting=none"] });
    try {
      const page = await browser.newPage({ viewport: { width: 1480, height: 2320 }, deviceScaleFactor: 1 });
      await page.goto(pathToFileURL(TEMPLATE).href);
      const fontState = await page.evaluate(async () => {
        await Promise.all([...document.fonts].map(f => f.load().catch(() => {})));
        return [...document.fonts].map(f => `${f.family} ${f.weight}: ${f.status}`);
      });
      const bad = fontState.filter(s => !s.endsWith("loaded"));
      if (bad.length) throw new Error(`caption fonts failed to load (tools/fonts): ${bad.join(", ")}`);
      for (const j of todo) {
        const res = await page.evaluate(spec => window.renderCaption(spec), { ...j.spec, emojiMap });
        await page.evaluate(async () => {
          await document.fonts.ready;
          await Promise.all([...document.images].map(im => im.decode().catch(() => {})));
        });
        const layers = [];
        for (const L of res.layers) {
          await page.evaluate(n => window.soloLayer(n), L.name);
          const png = join(outDir, `${j.key}-${L.name}.png`);
          await page.screenshot({ path: png, omitBackground: true, clip: { x: L.rect.x, y: L.rect.y, width: L.rect.w, height: L.rect.h } });
          layers.push({ name: L.name, png, ...L.frame, fontSize: L.fontSize, lines: L.lines });
        }
        if (debug) {
          await page.evaluate(n => window.soloLayer(n), "main");
          await page.evaluate(() => { document.getElementById("stage").classList.add("debug"); window.soloLayer("dim"); });
          await page.evaluate(() => { for (const el of document.querySelectorAll("#stage > *")) el.style.visibility = "visible"; });
          await page.screenshot({ path: join(outDir, `${j.key}-debug.png`), clip: { x: 200, y: 200, width: 1080, height: 1920 } });
        }
        writeFileSync(j.meta, JSON.stringify({ spec: j.spec, layers }, null, 2));
        const warn = layers.find(l => l.lines && ((j.spec.style === "hook" && l.lines > 3)));
        console.log(`  caption ${j.i} [${j.spec.style}/${j.spec.pos}] ${JSON.stringify(j.spec.text)} -> ${layers.map(l => `${l.name} ${l.w}x${l.h}@${l.x},${l.y}${l.fontSize ? ` ${l.fontSize}px/${l.lines}l` : ""}`).join(", ")}${warn ? " (!)" : ""}`);
      }
    } finally {
      await browser.close();
    }
  }
  return jobs.map(j => ({ caption: j.c, key: j.key, ...JSON.parse(readFileSync(j.meta, "utf8")) }));
}
