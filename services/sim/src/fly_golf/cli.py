"""`fly-golf` command-line interface."""

from __future__ import annotations

import argparse
import sys

READOUT_HELP = "experiments/readouts/malecns-readout-v1.json (used by the malecns-trained controller)"


def cmd_serve(args) -> int:
    import uvicorn

    from .config import load_settings

    s = load_settings()
    uvicorn.run(
        "fly_golf.api.app:app",
        host=args.host or s.api_host,
        port=args.port or s.api_port,
        reload=args.reload,
        log_level="info",
    )
    return 0


def cmd_putt(args) -> int:
    from .brain.registry import ControllerRegistry
    from .config import load_settings
    from .experiments.runner import PuttingSession, RunRecorder, summarize

    s = load_settings()
    registry = ControllerRegistry(s)
    controller = registry.get(args.controller)
    recorder = RunRecorder(s.runs_dir, metadata={"controller": controller.info.to_dict(), "source": "cli"})
    session = PuttingSession(controller, recorder=recorder, detailed_traces=args.traces or s.detailed_traces)
    print(f"controller: {controller.info.label}  ({controller.info.description})")
    if controller.info.is_mock:
        print("NOTE: MOCK CONTROLLER - development infrastructure, not the connectome.")
    for hole in range(args.holes):
        session.new_hole(args.seed + hole)
        sc = session.env.scenario
        print(f"\nhole {hole}  seed {sc.seed}  {sc.distance_m / 0.3048:.1f} ft  stimp {sc.green.stimp_ft:.1f}")
        while session.env.state.value == "ready" and session.env.strokes < args.max_strokes:
            rec = session.play_shot()
            print("  " + summarize(rec))
            if rec["neural_summary"]:
                ns = rec["neural_summary"]
                print(
                    f"    neural: {ns['total_spikes']:,} spikes, {ns['active_neurons']:,}/{ns['neuron_count']:,} "
                    f"neurons active, {ns['sim_ms']:.0f} ms simulated in {ns['wall_s']:.2f} s"
                )
                print("    motor:  " + ", ".join(f"{k}={v:.3f}" for k, v in rec["motor"]["channels"].items()))
    print(f"\nrecorded run: {recorder.dir}")
    return 0


def cmd_round(args) -> int:
    from .brain.registry import ControllerRegistry
    from .config import load_settings
    from .experiments.runner import COURSE_EXPERIMENT_ID, RoundSession, RunRecorder, summarize

    s = load_settings()
    controller = ControllerRegistry(s).get(args.controller)
    recorder = RunRecorder(
        s.runs_dir,
        metadata={
            "controller": controller.info.to_dict(),
            "source": "cli",
            "mode": "course",
            "experiment_id": COURSE_EXPERIMENT_ID,
        },
    )
    session = RoundSession(controller, recorder=recorder, detailed_traces=args.traces or s.detailed_traces)
    print(f"controller: {controller.info.label}  ({controller.info.description})")
    if controller.info.is_mock:
        print("NOTE: MOCK CONTROLLER - development infrastructure, not the connectome.")
    session.new_round(args.seed, start_hole=args.first)
    while True:
        h = session.env.hole
        print(f"\nhole {h.number} '{h.name}'  par {h.par}  {h.length_m / 0.9144:.0f} yd")
        while not session.env.done:
            print("  " + summarize(session.play_shot()))
        card = session.scorecard[h.number]
        print(f"  -> {card['strokes']} ({card['strokes'] - card['par']:+d})" + ("" if card["holed"] else " picked up"))
        if session.round_complete or h.number >= args.last:
            break
        session.next_hole()
    t = session._totals()
    print(f"\nround: {t['strokes']} strokes over {t['holes_played']} holes ({t['to_par']:+d} to par)")
    print(f"recorded run: {recorder.dir}")
    return 0


FEATURE_SPACE_CHOICES = ["dn-type", "dn-type-side"]  # brain.malecns.controller.FEATURE_SPACES


def cmd_train(args) -> int:
    from pathlib import Path

    from .brain.malecns.graph import load_compiled
    from .config import load_settings
    from .training.pipeline import default_jobs, train

    s = load_settings()
    graph = load_compiled(Path(args.graph) if args.graph else s.compiled_dir)
    stamp = "shuffled" if args.control else "real"
    out = Path(args.out) if args.out else s.runs_dir / "training" / f"{stamp}-seed{args.seed}"
    scale = args.scale or (0.25 if args.quick else 1.0)
    report = train(
        graph,
        out,
        n_putt=int(120 * scale),
        n_green=int(120 * scale),
        n_short=int(120 * scale),
        n_full=int(200 * scale),
        seed=args.seed,
        jobs=args.jobs or default_jobs(),
        control=args.control,
        feature_space=args.features,
    )
    return _report_and_install(report, out, args.install)


def _report_and_install(report: dict, out, install: bool) -> int:
    import shutil

    from .brain.registry import READOUT_RELPATH
    from .config import load_settings

    for name, kinds in report["evaluation"]["variants"].items():
        print(
            f"{name:30s} "
            + "  ".join(
                f"{k}: holed {v['holed_pct']:5.1f}% median leave {v['median_leave_m']:6.2f} m" for k, v in kinds.items()
            )
        )
    if install:
        if report["meta"]["graph"].get("control"):
            print("refusing to install a control readout as the trained controller", file=sys.stderr)
            return 2
        dest = load_settings().repo_root / READOUT_RELPATH
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(out / "readout.json", dest)
        print(f"installed trained readout -> {dest}")
    return 0


def cmd_refit(args) -> int:
    from pathlib import Path

    from .training.pipeline import refit

    src = Path(args.source)
    out = Path(args.out) if args.out else src.parent / f"{src.name}-refit"
    return _report_and_install(refit(src, out, feature_space=args.features), out, args.install)


def cmd_bench(args) -> int:
    import json
    from datetime import UTC, datetime
    from pathlib import Path

    from .config import load_settings
    from .experiments.bench import bench
    from .training.pipeline import default_jobs

    s = load_settings()
    graph = None
    readout = None
    if (args.readout or args.attach) and args.controller != "malecns-trained":
        print("--readout / --attach only apply to --controller malecns-trained", file=sys.stderr)
        return 2
    if args.controller != "mock":
        from .brain.malecns.graph import load_compiled

        graph = load_compiled(Path(args.graph) if args.graph else s.compiled_dir)
    if args.controller == "malecns-trained":
        from .brain.registry import READOUT_RELPATH

        readout = str(Path(args.readout) if args.readout else s.repo_root / READOUT_RELPATH)
    report = bench(
        args.controller,
        rounds=args.rounds,
        seed0=args.seed,
        jobs=args.jobs or default_jobs(),
        graph=graph,
        readout_path=readout,
    )
    out = (
        Path(args.out)
        if args.out
        else s.runs_dir / "bench" / (f"{args.controller}-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json")
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=1) + "\n")
    sm = report["summary"]
    print(
        f"{args.controller}: {sm['rounds']} rounds, mean {sm['mean_strokes']} (par {sm['par']}), best "
        f"{sm['best_round']}, holes holed {sm['holes_holed_pct']}%, picked up {sm['holes_picked_up']}, "
        f"trees {sm['trees_per_round']}/round, water {sm['water_per_round']}/round"
    )
    for band, b in sm["by_distance"].items():
        clubs = ", ".join(f"{c} {p:.0f}%" for c, p in b["top_clubs"])
        print(f"  {band:>10s}: {b['shots']:4d} shots  {clubs}  (trees {b['trees_pct']}%)")
    print(f"-> {out}")
    if args.attach:
        # Record the result in the readout's own provenance (metadata only; weights untouched).
        path = Path(readout)
        d = json.loads(path.read_text())
        d.setdefault("meta", {})["bench"] = {
            k: sm[k]
            for k in ("rounds", "mean_strokes", "best_round", "holes_holed_pct", "trees_per_round", "water_per_round")
        } | {
            "bench": report["bench"],
            "seeds": report["seeds"],
            "git_commit": report["git"]["commit"],
            "report": str(out),
        }
        path.write_text(json.dumps(d, indent=1) + "\n")
        print(f"attached the bench summary to {path}")
    return 0


def cmd_runs(args) -> int:
    from .config import load_settings
    from .experiments.runner import list_runs

    for r in list_runs(load_settings().runs_dir):
        ctrl = (r.get("controller") or {}).get("label", "?")
        used = r.get("controllers_used") or []
        if len(used) > 1:  # a brain was swapped mid-run: never label it by the first brain alone
            ctrl = "MIXED " + "+".join(used)
        print(f"{r['run_id']}  {ctrl:16s}  shots={r['shots']:3d}  holed={r['holed']}")
    return 0


def cmd_replay(args) -> int:
    from .brain.registry import ControllerRegistry
    from .config import load_settings
    from .experiments.runner import load_run, replay_controller, replay_physics

    settings = load_settings()
    data = load_run(settings.runs_dir, args.run_id)
    if data is None:
        print("run not found", file=sys.stderr)
        return 1
    registry = ControllerRegistry(settings)
    ok = True
    unavailable = 0
    for shot in data["shots"]:
        if args.shot and shot["shot_id"] != args.shot:
            continue
        r = replay_physics(shot)
        ok &= r["identical"]
        line = (
            f"{shot['shot_id']}: trajectory identical={r['identical']} outcome={r['outcome']} "
            f"points={r['points_replayed']}"
        )
        if not r["same_physics_version"]:
            line += f" (recorded with {r['physics_version_recorded']}, now {r['physics_version_current']})"
        if args.controller:
            # Re-run the controller on the recorded sensory frame, with the engine and readout the
            # record names, and compare motor channels.
            try:
                controller = registry.replay_controller(shot)
            except (FileNotFoundError, ValueError) as exc:
                unavailable += 1
                line += f" motor NOT re-run ({exc})"
            else:
                c = replay_controller(shot, controller)
                ok &= c["identical"]
                line += f" motor identical={c['identical']}"
        print(line)
    if unavailable:
        print(f"{unavailable} shot(s) could not be re-run by their controller", file=sys.stderr)
    return 2 if not ok else (3 if unavailable else 0)


def cmd_export_showcase(args) -> int:
    from pathlib import Path

    from .config import load_settings
    from .experiments.showcase import ShowcaseExportError, export_showcase

    s = load_settings()
    out = Path(args.out) if args.out else s.repo_root / "apps" / "web" / "public" / "showcase"
    try:
        report = export_showcase(
            s.runs_dir,
            args.run_id,
            out,
            slug=args.slug,
            title=args.title,
            description=args.description,
            round_seed=args.round,
            featured=args.featured,
        )
    except ShowcaseExportError as exc:
        print(f"export-showcase: {exc}", file=sys.stderr)
        return 2
    rnd = report["round"]
    print(
        f"{report['controller']}: {report['shots']} shots, {rnd['strokes']} strokes over {rnd['holes_played']} holes "
        f"({rnd['to_par']:+d})" + ("" if rnd["complete"] else ", round incomplete")
    )
    print(f"  {report['run_file']}  {report['run_bytes'] / 1e6:.2f} MB")
    print(f"  course.json  {report['course_bytes'] / 1e3:.0f} kB   index.json  {report['index_bytes'] / 1e3:.1f} kB")
    for note in report["notes"]:
        print(f"  note: {note}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="fly-golf")
    sub = p.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("serve", help="run the API + WebSocket server")
    sp.add_argument("--host")
    sp.add_argument("--port", type=int)
    sp.add_argument("--reload", action="store_true")
    controllers = ["mock", "malecns", "malecns-trained"]
    rd = sub.add_parser("round", help="play the front nine headless and record it")
    rd.add_argument("--controller", choices=controllers, default="mock")
    rd.add_argument("--seed", type=int, default=7)
    rd.add_argument("--first", type=int, default=1, help="first hole (1-9)")
    rd.add_argument("--last", type=int, default=9, help="last hole (1-9)")
    rd.add_argument("--traces", action="store_true", help="save detailed neural traces")
    tr = sub.add_parser("train", help="fit a trained readout of MaleCNS activity from practice (docs/TRAINING.md)")
    tr.add_argument("--seed", type=int, default=0)
    tr.add_argument("--jobs", type=int, default=0, help="worker processes (default: up to 6)")
    tr.add_argument("--control", choices=["shuffled"], help="run the degree-preserving shuffled-connectome control")
    tr.add_argument("--graph", help="compiled graph directory (default: the MaleCNS data dir)")
    tr.add_argument("--out", help="output directory (default: runs/training/...)")
    tr.add_argument("--quick", action="store_true", help="a quarter of the practice situations")
    tr.add_argument(
        "--scale", type=float, default=0.0, help="multiply the 120/120/120/200 putt/green/short/full situations"
    )
    tr.add_argument("--install", action="store_true", help=f"copy the readout to {READOUT_HELP}")
    tr.add_argument(
        "--features",
        choices=FEATURE_SPACE_CHOICES,
        default="dn-type",
        help="readout input: DN-type rates, or DN-type x soma-side rates (both are always saved)",
    )
    rf = sub.add_parser(
        "refit", help="redo fit + calibration + evaluation from a training run's saved practice (no brain simulation)"
    )
    rf.add_argument("source", help="a runs/training/<name> directory written by `fly-golf train`")
    rf.add_argument("--out", help="output directory (default: <source>-refit)")
    rf.add_argument("--install", action="store_true", help=f"copy the readout to {READOUT_HELP}")
    rf.add_argument(
        "--features", choices=FEATURE_SPACE_CHOICES, help="readout input (default: the source run's feature space)"
    )
    bn = sub.add_parser("bench", help="play complete front-nine rounds headless and summarise them")
    bn.add_argument("--controller", choices=controllers, default="malecns-trained")
    bn.add_argument("--rounds", type=int, default=8)
    bn.add_argument("--seed", type=int, default=100, help="first round seed (rounds use seed, seed+1, ...)")
    bn.add_argument("--jobs", type=int, default=0, help="worker processes (default: up to 6)")
    bn.add_argument("--readout", help=f"trained readout to test (default: {READOUT_HELP})")
    bn.add_argument("--graph", help="compiled graph directory (default: the MaleCNS data dir)")
    bn.add_argument("--out", help="report path (default: runs/bench/<controller>-<utc>.json)")
    bn.add_argument("--attach", action="store_true", help="write the summary into the readout's metadata")
    pp = sub.add_parser("putt", help="play headless putts and record them")
    pp.add_argument("--controller", choices=controllers, default="mock")
    pp.add_argument("--seed", type=int, default=7)
    pp.add_argument("--holes", type=int, default=1)
    pp.add_argument("--max-strokes", type=int, default=6)
    pp.add_argument("--traces", action="store_true", help="save detailed neural traces")
    sub.add_parser("runs", help="list recorded runs")
    rp = sub.add_parser("replay", help="deterministically re-simulate recorded shots")
    rp.add_argument("run_id")
    rp.add_argument("--shot")
    rp.add_argument("--controller", action="store_true", help="also re-run the controller and compare motor output")
    ex = sub.add_parser(
        "export-showcase", help="export a recorded front-nine run for the static web showcase (GitHub Pages)"
    )
    ex.add_argument("run_id")
    ex.add_argument("--slug", required=True, help="showcase id and file name, e.g. trained-front-nine")
    ex.add_argument("--title", required=True, help='e.g. "Trained MaleCNS - Front Nine"')
    ex.add_argument("--description", help="one or two sentences shown with the run (default: generated)")
    ex.add_argument("--round", type=int, help="round seed to export when the run holds more than one round")
    ex.add_argument("--out", help="showcase directory (default: apps/web/public/showcase)")
    ex.add_argument("--featured", action="store_true", help="open the showcase on this run")
    args = p.parse_args(argv)
    handlers = {
        "serve": cmd_serve,
        "putt": cmd_putt,
        "round": cmd_round,
        "train": cmd_train,
        "bench": cmd_bench,
        "refit": cmd_refit,
        "runs": cmd_runs,
        "replay": cmd_replay,
        "export-showcase": cmd_export_showcase,
    }
    return handlers[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
