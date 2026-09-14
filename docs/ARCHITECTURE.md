# Architecture

Fly Golf has three parts: a Python simulation backend, a TypeScript wire protocol that both sides
check, and one React + three.js web app that can get its data from two places:

- **Live mode** (local development): the app drives the backend, and every shot is simulated on
  the spot.
- **Showcase mode** (GitHub Pages): the app replays shots recorded earlier, from static JSON files.

**Showcase mode replays previously computed experiment results.** It never runs, approximates or
invents a neural decision. Every stroke on https://jameskbb.github.io/fly-golf/ was produced by the
simulator below and written to a shot record before the page was built.

## The two modes

```
                        LIVE MODE                                   SHOWCASE MODE

 3D Golf UI (React / three.js)                          Recorded ShotRecords
     |          ^                                        (apps/web/public/showcase/*.json,
     | REST     | WebSocket state + shot records          written by `fly-golf export-showcase`)
     v          |                                            |
 FastAPI / WebSocket (services/sim/fly_golf/api)             v
     |                                                   StaticShowcaseSource
     v                                                   (apps/web/src/lib/showcaseSource.ts)
 Sensory Encoder              engineered                     |
     |                                                       v
     v                                                   showcase controller: session state
 MaleCNS Connectome           real wiring                before / after each recorded shot
 + Neural Dynamics            modelled (LIF)             (apps/web/src/showcase, lib/showcase.ts)
     |                                                       |
     v                                                       v
 Motor Decoder / Trained Readout   engineered / trained  existing 3D replay system
     |                                                   (store playback, scene/Actors.tsx,
     v                                                    BrainPanel, ShotBar, Scorecard)
 Golf Physics                 engineered, deterministic
     |
     v
 ShotRecord -> runs/<run_id>/shots.jsonl  --- export-showcase --->  (left column)
```

In live mode the controller can be the MOCK heuristic (no neurons), the untrained MaleCNS readout,
or the trained readout. In showcase mode the controller is whatever the recorded run used, and the
header says **RECORDED MALECNS RUN** (or **RECORDED MOCK RUN** / **RECORDED · MIXED BRAINS** when
that is the truth). The word LIVE appears only while a simulation backend is actually connected.

## What each layer is

| Layer | What it is | Status | Code |
| --- | --- | --- | --- |
| Wiring | MaleCNS v1.0: 166,700 neurons and 25,582,938 connections | **measured** anatomy (CC BY 4.0) | `data/`, `fly_golf/data/compiler.py` |
| Neural dynamics | leaky integrate-and-fire, Shiu et al. 2024 constants, `fly-golf-lif-v1` | **modelled** | `fly_golf/brain/malecns/engine.py` |
| Sensory interface | golf state -> 14 bounded channels -> current into chosen sensory populations | **engineered** | `fly_golf/brain/sensory.py`, `brain/malecns/populations.py` |
| Motor interface | descending-neuron rates -> 8 motor channels -> club, aim, power, tempo, strike | **engineered** | `brain/malecns/populations.py`, `brain/motor.py` |
| Trained readout (optional) | linear weights fitted offline on descending-neuron rates | **trained**, outside the connectome | `fly_golf/brain/trained.py`, `fly_golf/training/` |
| Golf physics | putting and full-shot flight, bounce, roll, penalties | **engineered**, deterministic | `fly_golf/golf/` |

The trained readout is not synaptic plasticity: nothing inside the MaleCNS graph changes, and the
neural state resets to rest before every stroke. See [TRAINING.md](TRAINING.md) and
[PROVENANCE.md](PROVENANCE.md).

## Repository layout

```
apps/web                  React + three.js (R3F) app, built twice: live and showcase
  src/lib/source.ts         SOURCE_MODE, assetUrl(), the FlyGolfSource interface
  src/lib/api.ts            live REST client (session control) + liveSource
  src/lib/ws.ts             live WebSocket with the versioned hello
  src/lib/showcaseSource.ts StaticShowcaseSource: static JSON, validated with the protocol schemas
  src/lib/showcase.ts       session state around each recorded shot, rebuilt from the records
  src/showcase/             showcase controller, controls and landing card
  src/scene/                course, fly, ball, camera: shared by both modes
  src/ui/                   header, brain panel, shot bar, scorecard, drawers: shared
  public/showcase/          the exported runs that GitHub Pages serves
packages/protocol         zod schemas: wire protocol, ShotRecord, showcase format; shared fixtures
services/sim              Python backend (FastAPI, NumPy, Numba)
  fly_golf/golf             physics, course, clubs, environments
  fly_golf/brain            controllers, sensory encoder, motor decoder, MaleCNS adapter, trained readout
  fly_golf/experiments      sessions, JSONL recorder, replay, bench, showcase exporter
  fly_golf/training         the trained-readout pipeline
  fly_golf/data             MaleCNS acquisition, verification and compilation (`make data`)
  fly_golf/api              REST + WebSocket server
data/                     the MaleCNS source lock; downloads and the compiled graph are git-ignored
experiments/readouts/     the installed trained readout and archived ones (small linear weights)
```

## Live mode in detail

1. `App` starts the live connection: `GET /api/status`, then `WS /ws/simulation` with a versioned
   hello (protocol v2). A version mismatch stops the app with an explanation.
2. The course (`GET /api/course`) is fetched once: every hole's geometry and the bag.
3. Commands go over REST (`lib/api.ts`): start a session, switch brains mid-round, reset, next hole,
   hit. The backend pushes `state`, `shot_phase`, `shot_result` and `controller_status` over the
   WebSocket.
4. **The backend owns time.** A shot is sensed, simulated (400 ms of neural time over the whole
   graph), decoded and flown by deterministic physics before the browser sees anything. The result
   is a `ShotRecord`: controller identity, versions, seeds, sensory channels, neural summary
   (spikes, active neurons, per-population rates, 10 ms bins, named readouts), motor channels,
   decoded stroke, the club chain, a 60 Hz trajectory with events, outcome and score. It is
   appended to `runs/<run_id>/shots.jsonl`.
5. **Playback** (`store.startPlayback`) animates the recorded, decoded stroke: the fly picks the
   club from its bag, addresses, aims, swings (`lib/swing.ts`), and the ball follows the recorded
   trajectory (`scene/Actors.tsx`). The frame rate only changes how smoothly it is shown.

## Showcase mode in detail

1. The build mode is fixed at build time: `vite --mode showcase` (or `VITE_FLY_GOLF_MODE=showcase`).
   It is never guessed from the hostname. Showcase builds use the base path `/fly-golf/`, the
   project path on GitHub Pages; `FLY_GOLF_BASE` overrides it. Every static URL goes through
   `assetUrl()`, which prefixes `import.meta.env.BASE_URL`.
2. `StaticShowcaseSource` loads `showcase/index.json`, `course.json` and one `runs/<id>.json`, and
   validates each against the schemas in `packages/protocol/src/showcase.ts` (a run's shots are
   ordinary `ShotRecord`s).
3. The showcase controller (`src/showcase/controller.ts`) steps through the round. For shot *k* it
   sets the session state from just before the shot, rebuilt from the records
   (`lib/showcase.ts`: ball, lie, strokes, scorecard, totals), and then plays the recorded shot
   through the same `startPlayback` a live shot uses. When the animation ends, the state from just
   after the shot takes over. The rebuilt scorecard is tested against the one the recorder wrote.
4. The scene, fly, club, trajectory, camera modes, scorecard, brain panel (spikes, active neurons,
   rates, populations, motor channels, club chain) and technical drawer are the live app's own
   components. In the showcase the brain panel reveals each shot's recorded 10 ms activity bins,
   slowed down, while the fly addresses the ball. The values are the recorded ones.
5. Shots play one at a time and never advance on their own. Visitors can play, pause, replay, step
   to the previous or next shot, scrub within a shot, jump to any hole or stroke, orbit and zoom,
   and pick a brain. Switching brains loads that brain's recorded round from the first tee. A
   splash screen (reopened from **About this demo**) explains that the page shows pre-generated
   plays and how to run the real simulation locally. The URL keeps `?run=…&shot=…`, so a refresh
   or a shared link returns to the same shot.
6. Not available in the showcase: hitting new shots, switching brains, the practice green and the
   Runs drawer, because they need the backend.

## The data-source seam

```ts
// apps/web/src/lib/source.ts
export interface FlyGolfSource {
  readonly mode: "live" | "showcase";
  getCourse(): Promise<CoursePayload>;
  getRuns(): Promise<RunSummary[]>;
  getRun(id: string): Promise<{ run: Record<string, unknown>; shots: ShotRecord[] }>;
}
```

`liveSource` (`lib/api.ts`) and `StaticShowcaseSource` implement it. `dataSource`
(`lib/dataSource.ts`) is the one this build uses. Session control (create a session, hit, switch
brains, reset, next hole) exists only in live mode and stays on `api`. Rendering and playback read
the store and never know where a record came from.

## Showcase file format

| File | Schema | Contents |
| --- | --- | --- |
| `index.json` | `ShowcaseIndex` | format `fly-golf-showcase` v1, the featured run, one summary per run (controller, shots, strokes, holes, source run id, commit) |
| `course.json` | `CoursePayload` | the course geometry and bag, identical to `GET /api/course` (a test enforces this) |
| `runs/<id>.json` | `ShowcaseRun` | title, description, provenance (source run id, commit, dirty flag, versions), controller, round scorecard, export notes, and every `ShotRecord` |

The format holds any number of runs, so comparisons can be added later: first putt, untrained
versus trained, shuffled-connectome control, lesions, before and after training. How to export and
publish a run is in [GITHUB_PAGES.md](GITHUB_PAGES.md).

## Determinism and provenance

- Physics and the deterministic parts of a run reproduce from commit, configuration, seed and
  initial state. `fly-golf replay <run>` re-simulates every trajectory and checks it is identical.
  `--controller` also re-runs the brain on the recorded sensory frame and compares the motor
  channels.
- Every record names its controller, neural engine, readout, mapping and physics versions, and the
  git commit with a dirty flag that counts untracked files.
- The showcase exporter validates every record, refuses a mock run titled as a connectome run and a
  MaleCNS shot without neural data, removes machine-local paths and rounds trajectory samples to
  0.1 mm for size. It never modifies the source run.

## CI and deployment

- `.github/workflows/ci.yml`: Python lint, tests and a server smoke test; web lint, typecheck,
  tests, the live build and the showcase build. CI never downloads the connectome.
- `.github/workflows/pages.yml`: on every push to `main`, it tests and builds showcase mode and
  deploys `apps/web/dist` with the official GitHub Pages actions. It never runs the simulation.
