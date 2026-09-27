# Shot list

All footage is the web demo replaying recorded shots (`apps/web/public/showcase/runs/`), captured
frame by frame in portrait by `tools/capture.mjs`. Run ids and shot numbers are the demo's own, so
every clip can be re-captured and every shot re-simulated (`fly-golf replay`).

## Used in the cut

| # | Clip | Source (run · shot) | Used at | Source in-point | Speed | What it shows |
| --- | --- | --- | --- | --- | --- | --- |
| 1 | `pondhop-tee.mp4` | trained-front-nine-s07 · 14 | 0.00–2.30 | 1.250 | 1.0× | hook: address -> swing, cut on impact (src 3.533) |
| 2 | `brainfire.mp4` | s07 · 14, brain-fire view | 2.30–4.60 | 0.000 | 1.1× | brain card replays the 400 ms decision (counter 0-400 ms by src 2.5) |
| 3 | `pondhop-tee.mp4` | trained-front-nine-s07 · 14 | 4.60–7.20 | 0.000 | 0.415× | back on the tee, HUD 'choosing...' (slowed: nothing moves) |
| 4 | `pondhop-tee.mp4` | trained-front-nine-s07 · 14 | 7.20–8.40 | 1.090 | 1.0× | club reveal at src 1.1: 7-iron (punch-in framed on the fly, club head and ball kept in) |
| 5 | `pondhop-tee.mp4` | trained-front-nine-s07 · 14 | 8.40–9.60 | 2.290 | 1.05× | swing, impact at t~9.58 |
| 6 | `pondhop-tee.mp4` | trained-front-nine-s07 · 14 | 9.60–12.40 | 4.000 | 1.94× | flight over the pond at ~2x, cut after the follow-cam settles (src 4.0) |
| 7 | `pondhop-tee.mp4` | trained-front-nine-s07 · 14 | 12.40–15.80 | 9.436 | 1.0× | lands on the green (src 9.425), bounces, stops 4.7 ft short; the push-in is the capture crop (1.15x -> 2.2x) |
| 8 | `pondhop-putt1.mp4` | s07 · 15 | 15.80–17.30 | 3.100 | 1.7× | the 4-footer slides by (impact src 3.40) |
| 9 | `pondhop-lipout.mp4` | s07 · 16 | 17.30–18.40 | 3.050 | 0.545× | the 14-inch putt, easing into slow motion (impact src 3.40 -> t 17.94) |
| 10 | `pondhop-lipout.mp4` | s07 · 16 | 18.40–18.70 | 3.650 | 0.25× | slow-mo 1/4x into the cup: lip at src 3.725 (t 18.70) |
| 11 | `pondhop-lipout.mp4` | s07 · 16 | 18.70–19.00 | 3.725 | 0.05× | freeze on the lip under the boom |
| 12 | `pondhop-lipout.mp4` | s07 · 16 | 19.00–19.80 | 3.740 | 1.0× | pull back as the ball rolls 3.8 ft away, real speed |
| 13 | `pondhop-tapin.mp4` | s07 · 17 | 19.80–20.90 | 3.050 | 1.0× | the 3.8-footer coming back |
| 14 | `pondhop-tapin.mp4` | s07 · 17 | 20.90–21.40 | 4.150 | 1.0× | push into the cup as it drops (holed src 4.45 -> t 21.2) |
| 15 | `pondhop-tapin.mp4` | s07 · 17 | 21.40–25.00 | 4.650 | 0.69× | hold on the fly and the cup |

Every row is generated from `edl.json`, so it cannot drift from the cut. Speed changes exist only
to fit 25 s; no shot outcome is altered, and nothing is sped up to look better than it was. The
push-ins are of two kinds: a *capture* crop (the virtual camera renders a tighter window natively,
used for the landing, 12.4–15.8 s) and a *render* zoom (`zoom` in the table's segments).

## Captured as backups (not in this cut)

| Clip | Source | Why it lost |
| --- | --- | --- |
| `wingspan-approach` | s11 · 36: 5-iron from 196 yd to 1.4 ft | The best iron shot in the demo, but a tap-in birdie is a happy ending with no turn. Perfect for a future short ("it made a birdie"). |
| `wingspan-birdie` | s11 · 37 | See above. |
| `bomb-putt` | s11 · 46: 34-ft putt holed | Great ball-drop payoff, but a putt is a weak hook. Short 03 ending. |

## Moments found but not captured

- **Untrained fly, round 7, hole 1:** from a bunker 11 m from the pin it takes a **6-iron**, out of
  bounds, then does it again. The untrained readout hits a 6-iron from almost everywhere (372 of its
  557 shots). Funny, but it is a different brain setting and would need a whole short to explain
  honestly. Strong candidate for a "before lessons" episode.
- **Driver off the fairway into OB** (trained s10 · 23): funny, but a single bad shot with no payoff.
