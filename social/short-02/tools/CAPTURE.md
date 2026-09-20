# Capturing gameplay clips (short-02)

`capture.mjs` replays a REAL recorded shot in the static showcase and frame-steps it with a
virtual clock (performance.now / Date.now / requestAnimationFrame replaced before the app loads),
so every frame is exactly 1/30 s of playback time regardless of SwiftShader speed. No app source
is modified; layout changes are capture-only CSS, and framing is a capture-only camera crop.

## Prerequisites

- Showcase served at http://localhost:4173/ (from `apps/web`: `npx vite preview --port 4173 --strictPort`).
- Run node with the WSLg display variables unset (otherwise Chromium's GPU process hangs on WebGL).

## What the script does

1. Opens `/?run=<run>&shot=<n>` at the viewport (default 1080x1920, DPR 1).
2. Injects CSS: hides header, playback panel (`.showcase-controls`), right BRAIN panel (unless
   `--keep-brain-panel`), and the brain-firing card (unless `--brainfire`); re-flows the bottom HUD
   (`.shotbar`) into 4 columns x 2 rows with larger type (or hides it with `--no-hud`).
3. Settles ~6 s of virtual time, presses `c` (close scorecard), `b` if `--brainfire`, then Space.
4. Per frame: advances 1/30 s (two half-steps), screenshots, records `.scrub-phase`,
   HUD CLUB / RESULT / TO PIN text.
5. Stops when playback ends (phase label goes blank - the app then re-frames for the next shot,
   so that frame is dropped) and clones the last playback frame for `--hold` seconds.
6. Encodes H.264 yuv420p CRF 18, 30 fps, no audio; writes `<name>.json` and `<name>-sheet.png`.

### Framing (`--frame`)

The app's camera uses a fixed 40 deg vertical FOV and places the fly off to the right of the line,
so at 9:16 the fly is outside the frame entirely. `--frame '[[t,cx,cy,zoom],...]'` wraps the
stage renderer's `render()` (reached via three.js's `__THREE_DEVTOOLS__` observe hook) and calls
`PerspectiveCamera.setViewOffset` so the stage shows the window centred at (cx, cy) - normalised
coordinates of the view as it would look in a 16:9 stage of the same height - magnified by `zoom`.
This is pixel-equivalent to rendering a wider/larger frame and cropping it (rendered natively, not
upscaled). Keys are eased with smoothstep over playback time. The app's own camera motion
(address view, follow-cam) is untouched.

## Commands run

```bash
cd social/short-02/tools
N="timeout 1800 env -u DISPLAY -u WAYLAND_DISPLAY -u XDG_RUNTIME_DIR node capture.mjs"

# exploration: full 16:9 view to locate the fly/ball/cup (every 10th/15th frame, no encode)
$N --shot 14 --name wide14 --width 3072 --height 1728 --no-hud --every 15 --out <scratch>/wide

# 1. tee shot, Pond Hop (s07 shot 14)
$N --run trained-front-nine-s07 --shot 14 --name pondhop-tee --hold 0.7 \
  --frame '[[3.45,0.77,0.58,1.4],[4.2,0.52,0.5,1.0],[7.5,0.55,0.5,1.0],[9,0.57,0.5,1.15],[10.5,0.56,0.5,1.15],[12.4,0.555,0.5,1.6]]'
# 2. first putt
$N --run trained-front-nine-s07 --shot 15 --name pondhop-putt1 --hold 0.7 --frame '[[0,0.525,0.5,1.25]]'
# 3. lip-out
$N --run trained-front-nine-s07 --shot 16 --name pondhop-lipout --hold 0.7 \
  --frame '[[3.45,0.565,0.47,1.75],[3.75,0.55,0.47,1.6],[4.8,0.495,0.46,1.05]]'
# 4. tap-in
$N --run trained-front-nine-s07 --shot 17 --name pondhop-tapin --hold 0.7 --frame '[[0,0.545,0.5,1.4]]'
# 5. brain fire (6 s), plus the keep-brain-panel comparison
$N --run trained-front-nine-s07 --shot 14 --brainfire --seconds 6 --name brainfire \
  --frame '[[3.45,0.77,0.58,1.4],[4.2,0.52,0.5,1.0]]'
$N --run trained-front-nine-s07 --shot 14 --brainfire --seconds 6 --name brainfire-panel --keep-brain-panel \
  --frame '[[3.45,0.75,0.62,1.4],[4.2,0.52,0.5,1.0]]'
# 6-8. backups
R11="$N --run trained-front-nine-s11 --hold 0.7"
$R11 --shot 36 --name wingspan-approach \
  --frame '[[3.45,0.77,0.58,1.4],[4.2,0.52,0.5,1.0],[8,0.55,0.5,1.0],[10,0.56,0.55,1.0],[12,0.52,0.5,1.15],[14.5,0.49,0.5,1.6]]'
$R11 --shot 37 --name wingspan-birdie --frame '[[0,0.56,0.47,1.4]]'
$R11 --shot 46 --name bomb-putt --frame '[[3.4,0.57,0.66,3.0],[5.0,0.52,0.56,1.7]]'
```

Contact sheets: `<ffmpeg> -framerate 30 -i f%05d.png -vf "select='not(mod(n,STEP))',scale=270:-1,tile=6x2" -frames:v 1 sheet.png`
(the static ffmpeg in use has no drawtext, so sheets carry no timestamps; frame k of the sheet is
t = k*STEP/30 s, STEP = floor(rendered_frames/12)).

Rendered PNG frames are written to `clips/.frames/<name>/` (about 3 GB for all nine clips). They
were moved out of the repo after encoding to keep the working tree small.
