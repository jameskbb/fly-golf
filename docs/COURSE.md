# The course: Fly Golf National, clubs and full-shot physics

Everything on this page is **engineered**: hole design, club numbers, flight model and rules
are our choices, documented here and versioned in every shot record (`course`, `clubs`,
`course_physics`, `course_reward`). None of it comes from the connectome.

## Fly Golf National (`golf/course.py`, `eighteen-v1`)

Eighteen hand-authored holes, par 72, 6,831 yards: the parkland **Front Nine** (holes 1-9,
par 36, 3,352 yards) and a dusk-lit back nine, **The Neuropil Nine** (holes 10-18, par 36,
3,479 yards). The totals are computed from the holes' exact lengths, so the rounded yardages in
the tables may not add up to them to the yard. Each hole lives in its own frame: the tee at the origin, the hole playing roughly
north. Every hole in the course payload carries `nine` (`front` or `back`) and `theme`
(`parkland` or `dusk`), and the payload lists both nines under `nines`.

The front nine is unchanged from `front-nine-v2`, bit for bit (a test pins a hash of its
geometry). A round record of holes 1-9 made under `front-nine-v2` still replays exactly, and
`fly-golf replay` reports it as compatible.

**Hole seeds.** Each attempt at a hole gets a seed (address jitter and the per-stroke controller
seeds, `hole_seed * 1000 + stroke`), from `hole_seed(round_seed, hole, attempt)` in
`experiments/runner.py`:

- holes 1-9, unchanged: `round_seed * 10 + hole + attempt * 10,000,000`
- holes 10-18: `10**12 + round_seed * 10 + (hole - 9) + attempt * 10,000,000`

So holes 1-9 of an 18-hole round are the same situations they always were, and the back nine has
a seed space of its own. No two (round, hole, attempt) share a seed for round seeds 0-999,999
and attempts 0-99,999 (a test checks round seeds 0-5,000, every hole, attempts 0-3). Every
controller seed stays below 2^53, so it is exact in JSON and JavaScript.

**Rounds over a range of holes.** A round is all 18 holes unless it is started on a range
(`fly-golf round --first 10 --last 18`, `fly-golf bench --nine back`): its scorecard then holds
just those holes and it is complete when they are played. The round summary lists them as
`holes`. The app's rounds are always 18 holes.

### The Front Nine

Water on **four** holes.

| # | Name | Par | Yards | Features |
| --- | --- | --- | --- | --- |
| 1 | First Flight | 4 | 364 | fairway bunkers pinch the landing area; green bunkers left and right |
| 2 | The Dogleg | 4 | 412 | hard dogleg left around a corner bunker |
| 3 | Pond Hop | 3 | 164 | **all carry over a pond**; the green tilts back toward the water |
| 4 | Long Haul | 5 | 522 | **a creek crosses the fairway** just past driving distance: lay up or carry |
| 5 | Lakeside | 4 | 380 | **a lake runs the whole left side**; the green leans toward it |
| 6 | Little Sting | 3 | 137 | green ringed by four bunkers |
| 7 | Wingspan | 4 | 423 | long dogleg right with an inside-corner bunker |
| 8 | Marsh Run | 5 | 553 | **a marsh pond mid-fairway and water short-right of the green** |
| 9 | Home Stretch | 4 | 396 | a cross bunker splits the fairway; big, fast green |

### The Neuropil Nine

Each back-nine hole is named after a structure of the fly's nervous system or body, and its
**shape echoes that structure**; each also borrows the strategy of a classic "template" hole
from golf architecture, so the nine plays nothing like the front. The front nine is straight
holes and gentle doglegs with one kind of hazard at a time; the back nine adds an island green,
a drivable par 4, a double dogleg, a cape hole, a long par 3, a narrow chute, a wide-open hole
with waste sand and bunker patterns (a hexagonal cluster, church pews, curved bands), and its
greens vary more (radius 10 to 17 m, stimp 9.5 to 12.5, slopes up to 0.02).

| # | Name | Par | Yards | Corridor | Green (radius, stimp) | Features | Anatomy | Inspired by |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 10 | Ommatidia | 4 | 408 | 42 m | 12.5 m, 11 | **seven pot bunkers packed in a hexagon** just past the drive | the hexagonally packed facets of the compound eye | the pot bunkers of the Old Course and Royal Lytham |
| 11 | Johnston's Organ | 3 | 220 | 42 m | 16 m, 10.5 | **long par 3**; one long curved bunker across the front-left, green tilted away to the back-left, open to a run-in from the right | the antennal hearing organ and the arista that catches sound | the Redan (15th at North Berwick) |
| 12 | Halteres | 5 | 561 | 42 m | 13.5 m, 11 | **double dogleg**, right then left; **a burn crosses the line of play twice** | the balance organs that beat opposite the wings | the Barry Burn snaking across Carnoustie's 17th and 18th |
| 13 | Protocerebral Bridge | 4 | 274 | 42 m | 10 m, 12.5 | **drivable par 4** on paper: a row of **church-pew bunkers** on the direct line to a small, fast green with water right; the fly is shown the lay-up area on the left | the bridge of glomeruli spanning the brain's midline | Riviera's 10th (drivable par 4); Oakmont's church pews |
| 14 | Mushroom Body | 4 | 425 | 46 m | 12 m, 11.5 | tee in a cup of sand; a narrow stalk of fairway that **splits into two lobes**, one straight to the green, one off to the right | calyx, peduncle, and the vertical and medial lobes | split fairways such as Riviera's 8th |
| 15 | Ellipsoid Body | 3 | 139 | 42 m | 12 m, 11 | **island green** inside a ring of water, reached on foot by a causeway | the ring-shaped neuropil that holds the fly's compass | TPC Sawgrass 17th |
| 16 | Fan-shaped Body | 4 | 418 | **58 m** | 17 m, 9.5 | **the widest hole**: a fan-shaped fairway crossed by curved bands of **waste sand** broken into columns, big waste areas either side | the layered, column-segmented fan of the central complex | Pine Valley's waste areas; Pinehurst No. 2 |
| 17 | Giant Fiber | 5 | 599 | **30 m** | 11 m, 12 | **the longest, straightest hole: a narrow chute through the trees** | the giant fibers, a bilateral pair of descending interneurons: the fast escape pathway from brain to jump muscles | Carnoustie's 6th ("Hogan's Alley") |
| 18 | Descending Neurons | 4 | 436 | 42 m | 14 m, 11.5 | **cape hole**: the tee shot carries as much of the clubhouse lake as you dare; water short-left of the green | the descending neurons that carry the brain's commands to the body | Macdonald's Cape (National Golf Links) |

Water on **four** back-nine holes (12, 13, 15, 18). Johnston's Organ has the steepest green on
the course (slope 0.02, falling away to the back-left, as a Redan does).

A few design notes on how the environment plays these holes:

- **Island green (15).** The ring of water is one curved water polygon with a gap (the
  causeway) at the back right; the island inside it is fairway and rough around the green. With
  the ordinary water rule a tee shot that comes up short drops on the tee side of the ring (there
  is a strip of fairway as a drop zone); a shot over the green, from the tee or from the island,
  drops back on the island.
- **Drivable par 4 (13).** From the tee the pin is 242 m away, beyond the 225 m at which the fly
  looks at the pin, so its target is the lay-up area on the left. Drivable describes the
  geometry, not a choice the fly makes. Only a full-speed, straight driver within about 2
  degrees of the pin line holds the green (-1 to +2 degrees in 0.5 degree steps); at 97 percent
  speed a single one of those headings does.
- **Cape (18).** The lake sits in the inside corner of the dogleg; the routing goes around it,
  but any line further left carries more water and leaves a shorter approach. After a short
  drive the pin comes within 225 m, so the fly's target becomes the pin, across the corner of
  the lake.
- **Mock controller check.** The mock controller (development only, not the connectome) holes
  out every hole on round seeds 7-16 and 100-111 (22 rounds, no pick-ups) and averages 38.0 on
  the back nine and 36.5 on the front (74.5 for 18). Every back-nine hole averages within 0.6
  strokes of par (the hardest is 18, +0.55, then 10, +0.41): every hole is finishable and none is
  unfair to a player that aims where the environment points. A test repeats this check.

### Held out from training

Training (`training/situations.py`) practises only on the front nine. **The trained fly has
never practised a single shot on the back nine**, so its back-nine scores measure how well what
it learnt transfers to holes it has never seen. `fly-golf bench` reports front- and back-nine
splits for this reason.

### Per-hole corridor

The trees (out of bounds) begin at each hole's own corridor half-width, the distance from the
routing line: 42 m on every front-nine hole and most back-nine holes, 30 m on Giant Fiber (17),
46 m on Mushroom Body (14) and 58 m on Fan-shaped Body (16). The course payload reports it as
`corridor_half_width_m` per hole. The disc of 26 m around the green is always in play.

### Surfaces and rules

A point on a hole is, in priority order: **water** (polygons), **out of bounds** (anything
farther from the routing line than the hole's corridor half-width, 42 m unless the hole sets its
own, and not within 26 m of the green: the trees), **green** (a
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
| Putter | 4.2 m/s max | 0° | 0 | n/a | n/a |
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
