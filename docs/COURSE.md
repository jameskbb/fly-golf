# The course: front nine, clubs and full-shot physics

Everything on this page is **engineered**: hole design, club numbers, flight model and rules
are our choices, documented here and versioned in every shot record (`course`, `clubs`,
`course_physics`, `course_reward`). None of it comes from the connectome.

## The front nine (`golf/course.py`, `front-nine-v2`)

Nine hand-authored holes, par 36, 3,352 yards. Each hole lives in its own frame: the tee at the
origin, the hole playing roughly north. Water on **four** holes.

| # | Name | Par | Yards | Features |
| --- | --- | --- | --- | --- |
| 1 | First Flight | 4 | 364 | fairway bunkers pinch the landing area; green bunkers left and right |
| 2 | The Dogleg | 4 | 412 | hard dogleg left around a corner bunker |
| 3 | Pond Hop | 3 | 164 | **all carry over a pond**; the green tilts back toward the water |
| 4 | Long Haul | 5 | 523 | **a creek crosses the fairway** just past driving distance: lay up or carry |
| 5 | Lakeside | 4 | 379 | **a lake runs the whole left side**; the green leans toward it |
| 6 | Little Sting | 3 | 137 | green ringed by four bunkers |
| 7 | Wingspan | 4 | 423 | long dogleg right with an inside-corner bunker |
| 8 | Marsh Run | 5 | 553 | **a marsh pond mid-fairway and water short-right of the green** |
| 9 | Home Stretch | 4 | 396 | a cross bunker splits the fairway; big, fast green |

### Surfaces and rules

A point on a hole is, in priority order: **water** (polygons), **out of bounds** (anything more
than 42 m from the routing line and not within 26 m of the green: the trees), **green** (a
tilted circle), **fringe** (1.5 m collar), **sand** (bunker polygons), **tee**, **fairway**
(polygons), otherwise **rough**.

- **Water:** one penalty stroke. The ball is dropped on the line from the shot's origin, 2 m
  short of where it crossed into the water (a simplified "back on the line" relief).
- **Out of bounds:** one penalty stroke, replay from the previous spot (stroke and distance).
- **Whiff** (no contact): counts as a stroke; the ball does not move.
- **Pick-up:** a hole ends at par + 5 strokes, scored as par + 5.
- **Lie** (applied by the environment; the decoder never sees it): a lofted strike from sand
  keeps 72 % of its ball speed and 50 % of its spin, from rough 90 % and 55 %. Putts are
  unaffected: their roll already feels the surface.

### What the fly perceives as its target

Each hole has a routing line (tee → landing area(s) → pin). The fly's *target* is the pin once
it is within 225 m; otherwise the next routing point ahead of the ball that is at least 60 m
away (so a landing area a wedge away is skipped, never laid up to). This is environment design,
like yardage markers and a caddie pointing down the fairway: it tells the fly where "forward"
is, not which club to hit. At address the fly stands facing its target ±6° off the green, ±10°
on it (seeded), so aim is still a genuine perceptual problem.

## The bag (`golf/clubs.py`, `bag-v1`)

Fourteen clubs, ordered shortest to longest because the `club_reach` motor channel indexes
this order (0 = putter … 1 = driver, evenly spaced slots). Launch numbers are round,
amateur-to-scratch launch-monitor values. The distances are **outputs** of the physics below
(full swing, flat fairway, no wind), recomputed from the code by `nominal_distances()`.

| Club | Ball speed | Launch | Spin | Carry | Total |
| --- | --- | --- | --- | --- | --- |
| Putter | 4.2 m/s max | 0° | 0 | — | — |
| Lob wedge | 29.5 m/s | 33° | 10,500 rpm | 72 yd | 74 yd |
| Sand wedge | 34.0 | 30° | 10,200 | 90 | 93 |
| Gap wedge | 38.5 | 27° | 9,800 | 109 | 113 |
| Pitching wedge | 41.5 | 24.5° | 9,200 | 123 | 127 |
| 9-iron | 44.0 | 22° | 8,500 | 135 | 141 |
| 8-iron | 46.5 | 19.5° | 7,700 | 148 | 155 |
| 7-iron | 49.0 | 17.5° | 6,900 | 161 | 170 |
| 6-iron | 51.5 | 15.5° | 6,100 | 174 | 184 |
| 5-iron | 54.0 | 14° | 5,400 | 187 | 199 |
| 4-hybrid | 57.0 | 13.5° | 4,600 | 202 | 216 |
| 5-wood | 60.0 | 12.5° | 4,200 | 214 | 230 |
| 3-wood | 64.5 | 11.5° | 3,600 | 233 | 251 |
| Driver | 69.0 | 11° | 2,700 | 248 | 269 |

## Full-shot physics (`golf/flight.py`, `course-physics-v2`)

The practice green keeps `physics.py` (`putting-physics-v2`) unchanged, so older records replay
exactly. The course uses a second, deterministic model:

- **Flight.** A point-mass ball with quadratic drag and Magnus lift:
  `a = −g ẑ − k·C_D·|v|·v + k·C_L·|v|²·(ω×v)/|ω×v|`, `k = ρA / 2m`, with
  `C_D = 0.25 + 0.18 S`, `C_L = 0.38 (1 − exp(−S / 0.12))`, spin factor `S = rω/|v|`. Spin decays
  with τ = 25 s. Backspin lifts; sidespin (+ counter-clockwise from above) curves the ball left.
  Round-number fits in the range reported for golf balls (e.g. Bearman & Harvey 1976; Smits &
  Smith 1994), tuned so the bag gives typical carries. No wind, no elevation.
- **Bounce.** On landing, the vertical speed rebounds with a surface restitution (fairway 0.32,
  green 0.26, rough 0.16, sand 0.03). Horizontal speed keeps a surface fraction (0.62, 0.58, 0.40,
  0.08), reduced by 9 % per 1,000 rpm of backspin at landing, so wedges check and drivers
  release. Bouncing ends when the rebound is under 1 m/s.
- **Roll.** Constant rolling deceleration: fairway/tee 1.25 m/s², fringe 1.1, rough 3.4, sand 9,
  and on the green the stimpmeter value plus gravity along the tilted plane, exactly as in the
  putting model. Only the green is tilted and only the green has gravity along its slope. Around
  it, a 5.5 m collar (fringe + 4 m) blends the rim height smoothly down to the flat hole; the
  physics uses it for the ball's height and landing, and the renderer draws exactly the same
  surface. The fringe reports no slope to the fly, because it has none for rolling.
- **Cup.** Rolling capture and lip-outs reuse the putting rule (Holmes 1991 simplification). A
  ball that lands on the cup disc drops (a dunk).
- **Hazards.** A ball that lands in or rolls into water stops there (`water`); a ball that
  reaches the trees stops (`out_of_bounds`). Trees are otherwise decorative: no collisions.
- **Integration.** Fixed dt = 1/240 s, semi-implicit Euler, 60 Hz samples, Python floats in a
  fixed order: bit-identical replays (`fly-golf replay` covers course shots too).

**Not modelled:** wind, elevation, uneven lies, ball deformation, grain, tree collisions,
temperature. These are candidates for later versions and would bump `course-physics`.

## Reward (`course-reward-v1`)

Holed +1; whiff −0.25; otherwise the fraction of the distance to the pin gained, clipped to
[−1, 1], minus 0.5 per penalty stroke. Recorded for analysis only; never fed to a controller
during play (training uses its own practice score, see [TRAINING.md](TRAINING.md)).
