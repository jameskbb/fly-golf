# Short 02 render pipeline

One command (from `social/short-02/`):

```sh
env -u DISPLAY -u WAYLAND_DISPLAY -u XDG_RUNTIME_DIR node tools/render.mjs            # edl.json -> render/fly-golf-short-02.mp4
env -u DISPLAY -u WAYLAND_DISPLAY -u XDG_RUNTIME_DIR node tools/render.mjs edl.example.json   # test EDL (placeholder footage)
```

Flags: `--draft` (veryfast/CRF 26, writes `*-draft.mp4`), `--out path.mp4`, `--no-review` (skip poster/contact),
`--debug-captions` (re-render every caption and write `captions/<key>-debug.png` showing the safe area).
The `env -u …` part keeps WSLg variables away from headless Chromium. Exit code: 0 = all checks passed,
1 = EDL/render error (message says exactly what is wrong), 2 = rendered but a verification check failed.

## Outputs

| Path | What |
| --- | --- |
| `render/fly-golf-short-02.mp4` | 1080x1920, 30 fps, H.264 High yuv420p CRF 18 (bt709 tagged), `+faststart`, AAC 192k 48 kHz stereo |
| `render/poster.png`, `render/contact.png` | first frame; 12-frame contact sheet with timestamps, segment notes and captions |
| `render/fly-golf-short-02.report.json` | measured duration, size, fps, frame count, loudness, true peak |
| `render/_work/<name>/` | `filter_complex.txt`, `ffmpeg-args.json`, `encode.log`, SFX mix wavs (scratch; safe to delete) |
| `captions/<hash>-*.png` + `.json` | caption layers (cache keyed on text/style/pos + template + fonts) |
| `audio/*.wav` | synthesized SFX |

Any EDL other than `edl.json` renders to `render/<edl-name>.mp4` with prefixed review images
(`render/<edl-name>-poster.png`, `-contact.png`).

## Stages

1. **Validate** `edl.json`: fps/size/duration are whole frames; segments contiguous from 0 to `duration`;
   `speed > 0`, `zoom >= 1`, `focus` in 0..1; each clip exists and `in + frames/fps*speed` fits inside its
   duration (probed with `ffmpeg -i`; the static build has no ffprobe); caption style/pos/time range/balanced `*`;
   sfx names known. All problems are listed at once, then it exits 1.
2. **SFX**: `tools/make-sfx.sh` (runs automatically if a wav is missing) synthesizes every effect with lavfi
   only. Each is peak-normalised to -3 dBFS; the EDL `gain_db` (or the defaults in `render.mjs`) sets the mix.
   Events are delayed/summed (`adelay` + `amix normalize=0`), measured with `ebur128`, gained to
   `audio.target_lufs` (default **-16 LUFS integrated**) with an `alimiter` ceiling of `audio.ceiling_dbtp`
   (default -1.5 dBTP) if the peaks need it.
3. **Captions**: `tools/lib/captions.mjs` drives headless Chromium (Playwright) over `tools/caption.html`
   and screenshots each caption as a padded transparent PNG positioned in frame coordinates. Fonts are local
   TTFs in `tools/fonts/` (Anton, Barlow Condensed, JetBrains Mono; OFL, from Google Fonts). Emoji are Twemoji
   SVGs in `tools/emoji/` (CC-BY 4.0; missing ones are fetched from jsDelivr on first use), so 🪰 renders the
   same everywhere. Text that would exceed a style's line budget is shrunk to fit inside x 80–1000.
4. **Video** (one ffmpeg `filter_complex`): per segment `-ss in` → `setpts/speed` → `fps=30` → exact frame
   count (`tpad` + `trim`) → cover-crop in source pixels centred on `focus` (never letterboxed) → zoom via
   `perspective` (sub-pixel, eased, so no zoompan jitter) → lanczos scale to 1080x1920. Segments are
   concatenated with hard cuts on the frame grid. Each caption layer is a looped PNG shifted to `t0`, popped in
   (≈130 ms easeOutBack from 80 % scale about its centre, again via `perspective`) with a short alpha fade,
   faded out over 70 ms and overlaid only while active. A caption starting at t=0 is fully on screen on frame 1.
5. **Verify**: size, fps, frame count (= duration × fps), duration, audio stream, loudness, true peak.
6. **Review**: `poster.png` and `contact.png`.

Renders are deterministic: same EDL + clips + tools → byte-identical MP4 (checked by md5 across two runs).

## EDL reference

```jsonc
{
  "fps": 30, "width": 1080, "height": 1920, "duration": 25.0,
  "audio": { "target_lufs": -16, "ceiling_dbtp": -1.5 },          // optional
  "crf": 18,                                                      // optional
  "segments": [
    { "t0": 0.0, "t1": 2.0, "clip": "clips/pondhop-tee.mp4",      // relative to the EDL file, or absolute
      "in": 3.10, "speed": 1.0,                                   // source time at t0; consumes (t1-t0)*speed s
      "zoom": [1.0, 1.12], "focus": [0.5, 0.62],                  // scale across the segment; normalised source point
      "ease": "inout",                                            // optional: inout (default) | linear | out | in
      "note": "hook: swing" }
  ],
  "captions": [
    { "t0": 0.0, "t1": 2.0, "text": "I GAVE A FRUIT FLY BRAIN A *GOLF CLUB*", "style": "hook", "pos": "upper" },
    { "t0": 21.2, "t1": 25.0, "text": "Should I let it play *all 18?*", "style": "end",
      "title": "FLY GOLF 🪰⛳", "title_t0": 22.2, "url": "github.com/jameskbb/fly-golf" }
  ],
  "sfx": [ { "t": 1.55, "name": "whoosh", "gain_db": -6 } ]
}
```

- Caption text: `*word*` = yellow (#ffc81e) highlight; `|` or `\n` forces a line break; `"pop": false` disables the pop-in.
- Styles: `hook` Anton 112 px caps, ≤3 lines · `big` Anton 140 px · `normal` Barlow Condensed 800, 84 px, as typed ·
  `small` JetBrains Mono 56 px on a dark pill (deadpan aside) · `end` full-frame dim + question (Anton 120) +
  title (Anton, yellow, one line) that pops in at `title_t0` (default t0 + 1 s) + optional tiny `url`.
- `pos`: `top` (top edge y=270), `upper` (centred y=560), `middle` (centred y=900), `lower` (bottom edge y=1490).
  All inside the safe area x 80–1000, y 260–1500.
- SFX available: `whoosh impact click neural pop clink womp` (or drop any `<name>.wav` into `audio/`).
  Default gains (dB): whoosh -8, impact -4, click -10, neural -9, pop -16, clink -6, womp -9.

## Requirements

- ffmpeg with libx264 (path from `$FFMPEG`, else `tools/ffmpeg-path.txt` if you create one, else `$PATH`). The imageio-ffmpeg
  7.0.2 static build works; it has no `drawtext`, which is why all text goes through Chromium.
- Playwright (`$PLAYWRIGHT_MODULE`, default the global nvm install) with its bundled Chromium.
