# Experiments

Experiment **definitions** and analysis notes live here. Raw run **records** are written to the
git-ignored `runs/` directory (override with `FLY_GOLF_RUNS_DIR`):

```
runs/<run_id>/run.json        run metadata: controller, git commit, versions
runs/<run_id>/shots.jsonl     one JSON record per stroke (schema in docs/PROVENANCE.md)
runs/<run_id>/traces/*.json   optional per-bin population traces (--traces)
```

## Recorded so far

| Date | Run | Controller | What | Result |
| --- | --- | --- | --- | --- |
| 2026-09-13 | `20260913T153252Z-a05678` | MaleCNS (v0.1 mappings, physics v2, commit `b61c1f9`) | First connectome-driven putt with clean provenance, seed 7, 4.5 ft | 6 strokes, picked up. Overhits everything under 20 ft; aim offset left-biased (see docs/MOTOR_MAPPING.md) |
| 2026-09-13 | `20260913T145440Z-1133d9` | MaleCNS (superseded) | Same seed, recorded before the code was committed | Superseded: its provenance points at `35afc94`, which contains no code |
| 2026-09-13 | `20260913T170708Z-553f51` | MOCK (course, commit `164a2d1`) | Front nine, round seed 7 | 35 (−1). Reference only: a heuristic with a distance table |
| 2026-09-13 | training `20260913T172347Z` | MaleCNS + trained readout (`164a2d1`) | Readout fit, 1,320 practice situations, 396 held out | Putts: median leave 6.3 m → 1.0 m; still below a no-brain baseline. See docs/TRAINING.md |
| 2026-09-14 | `20260914T115447Z-e62f18` | MaleCNS + trained readout `20260913T220118Z` (`fly-golf-lif-v1`, public commit `fd29296`, clean tree) | Front nine, round seed 7. The web demo's `trained-front-nine` until 2026-09-14 | 58 (+22), 7 of 9 holes holed, 1 water penalty. All 57 trajectories and motor outputs re-simulate identically (`fly-golf replay --controller`) |
| 2026-09-14 | `20260914T115447Z-81909c` | MaleCNS, fixed readout (`fly-golf-lif-v1`, `fd29296`, clean tree) | Front nine, round seed 7. The web demo's `untrained-front-nine` until 2026-09-14 | 81 (+45), every hole picked up, 29 penalty strokes, only 6/7/8-irons |
| 2026-09-14 | refit `20260914T191715Z-refit` | MaleCNS + trained readout, PCA ≤ 256 (`109c4a1`, clean) | The installed run's saved practice (3,360 situations), re-fitted with more PCA components | Better on every held-out kind. Bench 66.9 per nine on seeds 100–111 (installed: 70.0), 66.6 on 200–211 (installed: 71.9). See docs/TRAINING.md |
| 2026-09-14 | training `20260914T192725Z` | MaleCNS + trained readout on DN type × side rates (`28b7a06`, clean) | 6,720 practice situations, 2,016 held out, both feature spaces saved | PCA ≤ 64: bench 73.6 per nine on seeds 100–111, worse than the installed 70.0 |
| 2026-09-14 | 30 rounds (see docs/GITHUB_PAGES.md) | Trained readout `20260914T191715Z-refit`, untrained MaleCNS, Mock (`dd1e393`, clean) | Front nine, round seeds 7–16 for each brain, all exported to the web demo | Trained 68.5 per nine (57–75), 56 of 90 holes holed; untrained 81 every round; Mock 36.5. Trained seed 7: 60 (the previous readout's seed-7 round was 58) |
| 2026-09-14 | refit `20260914T212017Z-shuffled-refit` | Shuffled-wiring control, PCA ≤ 256 (`109c4a1`, clean) | The shuffled control's saved practice, re-fitted the same way | Still better than the real wiring on every held-out kind except the median leave of green putts. Real wiring is not an advantage |

Recorded runs stay out of git. Selected runs are exported, validated, into the web demo's static
showcase (`apps/web/public/showcase/`) with `fly-golf export-showcase`; see docs/GITHUB_PAGES.md.

## Planned controlled comparisons

Nothing here is claimed until these comparisons run on the same seeds:

1. **Mock baseline** vs **MaleCNS v0.1**: holes holed and strokes per hole over N seeded holes.
2. **Shuffled connectivity** (`CTRL2-01`): the same degree sequence with rewired targets, to test
   whether the specific wiring matters at all.
3. **Lesions** (`CTRL2-02`): silence LC10 or DNa01/02, and check that aim-related variance changes
   as predicted.
4. **Plasticity** (`CTRL2-03`): only after 1–3, with before/after weight snapshots and held-out
   evaluation seeds.
