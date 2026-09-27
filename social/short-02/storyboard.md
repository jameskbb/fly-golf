# Short 02: "4 feet. 3 putts."

**Runtime:** 25.0 s · **Format:** 1080×1920, 9:16, 30 fps · **Platforms:** TikTok, Reels, Shorts, X

## The moment it is built around

Everything in this short is one real recorded hole: **Pond Hop**, the 164-yard par 3 over water,
from the web demo's featured round (trained readout `20260917T165536Z`, round seed 7, shots 14–17).
Nothing was re-rolled or staged; it is the same hole anyone can replay at
`https://jameskbb.github.io/fly-golf/?run=trained-front-nine-s07&shot=14`.

What the fly actually did:

| Shot | Club | What happened |
| --- | --- | --- |
| 14 | 7-iron | 400 ms of simulated activity (105,314 spikes) → carries the pond, stops **4.7 ft** from the flag |
| 15 | putter | misses the 4-footer, leaves it **14 inches** (0.36 m) |
| 16 | putter | **lips out from 14 inches**, rolls **3.8 ft** past |
| 17 | putter | holes the 3.8-footer coming back. **4 on a par 3.** |

Why this one beats every other moment in the 30 recorded rounds: a genuinely good shot (the best
approach over water in the demo) followed by the most human thing in golf: three-putting from
four feet, including a lip-out from a foot. The fly stops being a science project and becomes a
guy at the club. Runners-up and why they lost are in `shot-list.md`.

## Beats (final; exact times are in `edl.json` / `onscreen-text.md`)

| Time | Beat | Picture | On screen | Sound |
| --- | --- | --- | --- | --- |
| 0.0–2.3 | **Hook** | The fly (tam, argyle vest, plus-fours) at address, straight into its swing and impact. Punched in (1.3–1.42×) so it fills the frame. | **A FRUIT FLY BRAIN IS PLAYING GOLF** | music from frame 1, whoosh, *tock* at impact |
| 2.3–4.6 | **Reveal** | Hard cut to the brain map replaying that decision's 400 ms of recorded activity, the fly underneath. | **166,700 SIMULATED NEURONS** → *and apparently a tee time* | drums drop out, neural shimmer |
| 4.6–7.2 | **The decision** | The fly over the ball, slow push-in. | **164 YARDS. OVER WATER.** | bass and hats only |
| 7.2–8.4 | **Club reveal** | Punch-in on the fly with the 7-iron in its hands and the ball in frame. | **7-IRON.** | click, drums back in |
| 8.4–12.4 | **The shot** | Swing, impact, follow camera over the pond. Flight plays at ~2× (the real flight is 9 s). | *(nothing)* | whoosh, *tock*, full groove |
| 12.4–14.55 | **Landing** | Ball drops on the green, bounces, settles by the cup. The camera pushes from 1.15× to 2.2×, a capture crop, so it stays sharp. | **4.7 FEET.** (once it has stopped, 13.6) | pop |
| 14.55–15.8 | **Reaction** | Hold on ball and cup. | **wait. that's good.** | groove |
| 15.8–17.3 | **The miss** | The 4-footer slides by. | *then the putt…* | gallery *ooh* (16.45) |
| 17.3–18.7 | **The lip-out** | The 14-inch putt, easing into slow motion on the cup. | **14 inches.** | music thins, then **stops at 18.62** |
| 18.7–19.0 | **The gag** | Near-freeze on the ball catching the lip. | **LIPPED OUT.** | *clink* + **vine boom** into silence |
| 19.0–20.9 | **Consequence** | Real speed: the ball rolls 3.8 ft away; the fly walks after it. | none | silence, then the bed sneaks back at 19.8 |
| 20.9–21.4 | **Comeback** | Push into the cup as the 3.8-footer arrives and drops (21.2). | none | *clink*, gallery applause (21.25), groove back to full |
| 21.4–22.6 | **The punchline** | Hold on the fly and the cup. | **3 PUTTS. FROM 4 FEET.** | none |
| 22.6–25.0 | **Open loop** | Slow push-in on the fly and the cup. | **49.3 a nine. Can it break 100?** → **FLY GOLF 🪰⛳** (22.9) | final accent, tail out |

## Edit beats (for music-free cutting)

`0.0` hook on screen from frame 1 · `1.9` impact · `2.3` hard cut to brain · `4.6` back on the tee ·
`7.2` club reveal · `8.4` swing · `12.4` ball on the green · `13.6` 4.7 FEET · `14.55` reaction · `15.8` the putt ·
`17.3` the 14-incher · `18.62` music out · `18.7` lip + boom · `19.8` bed sneaks back · `21.2` it drops ·
`22.6` open loop · `25.0` end.

The bed is written to these times (`tools/make-music.py`), so re-timing the cut means re-running it.

The swing appears twice (hook flash-forward, then in order at 8.4); the post copy says it is one
real recorded shot.

## First frame

The fly in golf clothes at address over the ball, with **A FRUIT FLY BRAIN IS PLAYING GOLF**
already on screen (six words: readable inside the two-second hook). No logo, no title, no fade-in: an insect in plus-fours holding a 7-iron is the
stop-scroll image, and the caption explains it before the swing finishes.

## Honesty rules this cut follows

- Every frame of golf is the recorded replay of a real shot; the camera, clubs and outcomes are the
  simulator's. The capture-time changes are cosmetic: the app's own cinema mode (`?cinema=1`) hides
  every panel so nothing but the course is in frame, the brain card's chrome is hidden, and the
  camera crops to portrait.
- The music, the applause, the boom and every other sound are synthesized from oscillators and
  filtered noise (`tools/make-sfx.sh`, `tools/make-music.py`). No sampled or licensed audio.
- "166,700 simulated neurons" is the MaleCNS v1.0 connectome the simulation runs. The captions do not
  claim the fly *learned* golf or that its wiring is doing the thinking: the readout that turns
  activity into a club was fitted from practice, and a shuffled-wiring control does as well, which
  is why the copy stays on what the fly *did*, not what its brain *understands*.
