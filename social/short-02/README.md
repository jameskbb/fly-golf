# Fly Golf, Short 02: "4 feet. 3 putts." (clean re-shoot + vine boom)

A re-record of the first cut of this short (kept locally, not published here): the same 25-second vertical short (1080×1920, 9:16, 30 fps), with the same
cut, captions and timing, frame for frame. It changes two things:

1. **No UI in the shot.** Every clip was re-captured in the web demo's new cinema mode
   (`?cinema=1`, the same view as the ⛶ Fullscreen button or the **F** key). The header, the bottom
   HUD bar, the panels and the scorecard are all hidden, so only the course is on screen. The capture
   tool checks this before it records. The one exception is the "Brain firing" card, which is the
   subject of the 2.3–4.6 s beat. It is stretched across the top of the frame.
2. **A vine boom on the lip-out.** When the 14-inch putt lips out (18.7 s, on "LIPPED OUT."), a vine
   boom replaces the first cut's "womp". Like every other effect here it is synthesized from scratch in
   `tools/make-sfx.sh` (`vineboom`: a sub thud falling in pitch, soft-clipped, with an echo tail). No
   copyrighted sample is used.

3. **The tee framing is fixed.** In the first cut the punch-ins on the tee were centred at 40 % of the
   frame height, while the fly stands in the lower third, so the "7-IRON." beat (and the shots
   either side of it) cut off its legs, the club head and the ball. Those three segments are now
   framed on the fly itself (`edl.json` segments 0, 2 and 3), so the whole fly, the club head at
   the ball and the caption above its head all fit. Nothing else about the cut changed.

4. **Sound: a funky bed and a gallery.** `tools/make-music.py` synthesizes a 125 BPM bass-and-clav
   groove arranged to this exact cut (drums drop for the brain card, full groove carries the ball
   flight, **hard silence from 18.62 s so the lip-out lands on nothing**, sneaking back under the
   tap-in, everything back when the putt drops), plus a quiet golf-gallery clap at 21.25 s (mixed 15 dB down: a small gallery, not a crowd) and a small
   "ooh" at 16.45 s when the first putt slides by. Like the other effects these are oscillators and
   filtered noise, not samples: nothing copyrighted, and the render stays reproducible.
5. **Cut and framing revised after an adversarial review** (see "What the review changed" below).

**The finished video:** `fly-golf-short-02.mp4` (also `render/fly-golf-short-02.mp4`). It is
mixed to −16 LUFS with a −1.6 dBTP peak, and all render checks passed.

Everything else is unchanged: the source shots (`trained-front-nine-s07` shots 14–17, since re-recorded as `trained-eighteen-s07`,
Pond Hop), the storyboard, the captions, the voiceover and the post copy. See `storyboard.md`,
`shot-list.md`, `onscreen-text.md` and `voiceover.txt`. To see how the pipeline works, read
`tools/CAPTURE.md` and `tools/RENDER.md`.

## Rebuild

Playwright (with its Chromium) and ffmpeg must be installed where this runs; see `tools/CAPTURE.md`.

```bash
FLY_GOLF_BASE=/ pnpm --filter @fly-golf/web build:showcase
(cd apps/web && npx vite preview --port 4173 --strictPort &)
cd social/short-02/tools
N="env -u DISPLAY -u WAYLAND_DISPLAY -u XDG_RUNTIME_DIR node capture.mjs --out ../clips --run trained-eighteen-s07 --hold 0.7"
$N --shot 14 --name pondhop-tee --frame '[[3.45,0.77,0.58,1.4],[4.2,0.52,0.5,1.0],[7.5,0.55,0.5,1.0],[9,0.57,0.5,1.15],[10.5,0.56,0.5,1.15],[12.4,0.555,0.5,1.6]]'
$N --shot 15 --name pondhop-putt1 --frame '[[0,0.525,0.5,1.25]]'
$N --shot 16 --name pondhop-lipout --frame '[[3.45,0.565,0.47,1.75],[3.75,0.55,0.47,1.6],[4.8,0.495,0.46,1.05]]'
$N --shot 17 --name pondhop-tapin --frame '[[0,0.545,0.5,1.4]]'
$N --shot 14 --brainfire --seconds 6 --name brainfire --frame '[[3.45,0.77,0.58,1.4],[4.2,0.52,0.5,1.0]]'
cd .. && bash tools/make-sfx.sh && env -u DISPLAY -u WAYLAND_DISPLAY -u XDG_RUNTIME_DIR node tools/render.mjs
```

Cinema mode is now the capture default (`--no-cinema` gives the old injected-CSS layout). The event
times in each `clips/<name>.json` match the first cut's exactly.

## What the review changed

A reviewer went through the first cut frame by frame against TikTok retention. The changes it drove:

| Problem | Fix |
| --- | --- |
| The ball was invisible for the best shot of the round (8.4–15.8 s): a 12 px dot on a wide green | The tee clip was re-captured with the virtual camera pushing from 1.15× to 2.2× over the landing, so the ball, its bounces and the cup are rendered large and natively. The flight also cuts on a settled follow-cam (src 4.0), not mid-tilt |
| Two seconds of silence at the start reads as broken audio | The music bed starts at 0.00 s at full level |
| The lip-out, the whole joke, crawled at ¼ speed for 0.9 s | Re-timed: less crawl (17.3–18.4 s at 0.545×), the lip still at 18.70 s, then a near-freeze 18.7–19.0 s under the boom, then real speed |
| The payoff putt dropped at the edge of a wide frame, and the caption announced it three frames early | The tap-in splits at 20.9 s and pushes into the cup as the ball arrives; the caption now lands at 21.35 s |
| "4 on a par 3." means nothing to non-golfers | "*3 PUTTS.* FROM 4 FEET.": the joke in four words |
| The end card asked a question with an obvious answer | "49.3 a nine. Can it *break 100?*": a real open question (the trained fly averages 49.3 strokes per nine, range 42–54, so 18 holes is genuinely borderline) |
| The hook was a small figure in an empty green field | The opening pushes in to 1.3–1.42× on the fly |
| The brain card looked like a dashboard screenshot (close button, legend, mean-rate table) | The capture now hides that chrome: the neuron map, the counter and one line of caption remain |
| "4.7 FEET." popped while the ball was still bouncing | Moved to 13.6 s, when it has stopped |
| "14 inches." was set in the least legible style | Set in `normal` instead of the mono pill |

*Update, 2026-09-27:* the end card's question has since been played out on 18 real holes. The
trained fly broke 100 in 13 of 46 rounds: the ten web-demo rounds average 99.6 (5 of 10 under
100) and 36 bench rounds on fresh seeds average 102.6 (8 of 36). See the main README.

Not taken: a flash-forward to the pond during "164 YARDS. OVER WATER." (it would show the shot's
outcome before the swing). The yellow ball-tracer lines on the green are simulator output and would
need a capture-time change to remove; they are noted for the next short.

## Posting it on TikTok

1. Upload `fly-golf-short-02.mp4` as-is: 1080×1920, 9:16, 30 fps, captions burned in, −16.3 LUFS,
   −0.9 dBTP, 25.0 s.
2. Use `render/cover.png` as the cover (the 7-iron frame), or pick your own from `render/contact.png`.
3. Post copy, hashtags and a pinned comment that answers "166k neurons? a fly has 140k" and
   "did it learn?" are in `onscreen-text.md`.
4. Don't add a platform sound over it: the bed is cut to the edit, and its silence at 18.7 s is the joke.
