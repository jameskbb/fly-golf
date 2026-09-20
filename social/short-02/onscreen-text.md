# On-screen text

Burned-in captions. The video must read with the sound off. `*word*` = highlighted in the demo's
yellow (#ffc81e). Safe area: inside x 80–1000, y 260–1500 (TikTok/Reels UI covers the rest).

| In | Out | Text | Style | Position |
| --- | --- | --- | --- | --- |
| 0.00 | 2.30 | A FRUIT FLY BRAIN IS PLAYING *GOLF* | hook | upper |
| 2.30 | 3.40 | *166,700* SIMULATED NEURONS | normal | middle |
| 3.40 | 4.80 | and apparently a tee time | small | middle |
| 4.80 | 7.20 | 164 YARDS. *OVER WATER.* | normal | upper |
| 7.20 | 8.40 | *7-IRON.* | big | upper |
| 13.60 | 14.55 | *4.7 FEET.* | big | upper |
| 14.55 | 15.80 | wait. that's *good.* | normal | upper |
| 15.80 | 17.30 | then the putt… | small | upper |
| 17.40 | 18.65 | 14 inches. | normal | upper |
| 18.70 | 19.80 | *LIPPED OUT.* | big | upper |
| 21.35 | 22.60 | *3 PUTTS.* FROM 4 FEET. | big | upper |
| 22.60 | 25.00 | 49.3 a nine. / Can it *break 100?* | end | — |
| 22.90 | 25.00 | FLY GOLF 🪰⛳ | end title | under it |

These are the final times, generated from `edl.json`. Nothing is on screen from 8.40 to 13.40 while
the ball is in the air.

Rules: 3–7 words per caption (the hook is the one exception); never subtitle filler words; nothing
on screen while the ball is in the air.

Post copy (not in the video): *gave a simulated fruit fly brain a golf club. 7-iron over water to
4 feet… then 3 putts, including a lip-out from 14 inches. real recorded round — it averages 49.3
strokes a nine. can it break 100?* — at most #golf #science #ai

Pinned comment, ready for the two questions that will come: *166,700 = the whole male fly CNS
(brain + nerve cord), not just the brain. Club, aim and power are read out of the simulated activity
by weights fitted from practice shots — the wiring itself doesn't learn, and a shuffled-wiring
control plays about as well. github.com/jameskbb/fly-golf*
