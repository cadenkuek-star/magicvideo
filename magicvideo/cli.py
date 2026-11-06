"""magicvideo command line (brief §5)."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__, ffmpeg
from .project import Project, ProjectError
from .util import log, setup_logging


def cmd_doctor(_: argparse.Namespace) -> int:
    ok = True
    try:
        out = ffmpeg.run(["-version"]).stdout.splitlines()[0]
        print(f"ffmpeg      : {out}")
    except Exception as e:
        print(f"ffmpeg      : MISSING ({e})")
        ok = False
    for f in ("v360", "sendcmd", "loudnorm", "alimiter", "vidstabdetect", "deshake", "lut3d"):
        print(f"filter {f:<12}: {'yes' if ffmpeg.has_filter(f) else 'no'}")
    print(f"gpu (cuda)  : {'yes' if ffmpeg.gpu_available() else 'no (CPU fallback)'}")
    for mod, extra in (("faster_whisper", "asr"), ("speechbrain", "voice"), ("insightface", "faces"),
                       ("anthropic", "tags"), ("reverse_geocoder", "geo"), ("opentimelineio", "core")):
        try:
            __import__(mod)
            print(f"{mod:<16}: installed")
        except ImportError:
            print(f"{mod:<16}: not installed (pip install 'magicvideo[{extra}]')")
    return 0 if ok else 1


def cmd_init(a: argparse.Namespace) -> int:
    p = Project.init(Path(a.work), [Path(s) for s in a.source], a.name, Path(a.people) if a.people else None)
    print(f"trip folder ready: {p.root}\n  policy: {p.root / 'policy.yaml'}\n  people: {p.people_dir}")
    return 0


def cmd_analyze(a: argparse.Namespace) -> int:
    from .analysis.runner import run_analysis
    steps = [s.strip() for s in a.steps.split(",")] if a.steps else None
    summary = run_analysis(Project(Path(a.work)), steps, a.force)
    for step, counts in summary.items():
        print(f"{step:<8} done={counts['done']} skipped={counts['skipped']} failed={counts['failed']}")
    return 0


def cmd_enroll(a: argparse.Namespace) -> int:
    from . import enroll
    p = Project(Path(a.work))
    if a.finalize:
        report = enroll.finalize(p, merges=a.merge, allow_sparse=a.allow_sparse)
        for k, v in report.items():
            for line in (v if isinstance(v, list) else [v]):
                print(f"{k}: {line}")
        print(f"next: magicvideo plan \"{p.root}\"")
        return 0
    r = enroll.prepare(p)
    print(f"{r['faces']} face candidates, {r['voices']} voice candidates exported to {p.people_dir}")
    print(f"follow {p.people_dir / ('REVIEW_' + p.name + '.md')}, then run: magicvideo enroll \"{p.root}\" --finalize")
    return 0


def cmd_plan(a: argparse.Namespace) -> int:
    from .plan.planner import run_plan
    paths = run_plan(Project(Path(a.work)), thumbs=a.thumbs)
    for k, v in paths.items():
        print(f"{k:<10}: {v}")
    return 0


def cmd_review(a: argparse.Namespace) -> int:
    from . import review
    review.serve(Project(Path(a.work)), a.plan, a.port, open_browser=not a.no_open)
    return 0


def cmd_render(a: argparse.Namespace) -> int:
    from .plan.planner import warn_if_stale
    from .render.renderer import Renderer
    p = Project(Path(a.work))
    r = Renderer(p, a.plan)
    warn_if_stale(p, r.tag)
    outputs = r.run()
    print(f"master    : {outputs['master']}")
    for c in outputs["chapters"]:
        print(f"chapter   : {c}")
    print(f"timeline  : {outputs['otio']}")
    return 0


def cmd_qc(a: argparse.Namespace) -> int:
    from .qc.runner import run_qc
    v, path = run_qc(Project(Path(a.work)), a.version)
    print(f"QC verdict: {v}  ({path})")
    return {"PASS": 0, "FAIL": 2, "INCOMPLETE": 3}[v]


def cmd_run(a: argparse.Namespace) -> int:
    from .analysis.runner import run_analysis
    from .plan.planner import run_plan
    from .qc.runner import run_qc
    from .render.renderer import Renderer
    p = Project(Path(a.work))
    run_analysis(p)
    run_plan(p)
    Renderer(p).run()
    v, path = run_qc(p)
    print(f"QC verdict: {v}  ({path})")
    return {"PASS": 0, "FAIL": 2, "INCOMPLETE": 3}[v]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="magicvideo", description="Couple travel film pipeline")
    ap.add_argument("--version", action="version", version=__version__)
    ap.add_argument("-v", "--verbose", action="store_true")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("doctor").set_defaults(fn=cmd_doctor)
    s = sub.add_parser("init")
    s.add_argument("work"); s.add_argument("--source", action="append", required=True)
    s.add_argument("--name"); s.add_argument("--people")
    s.set_defaults(fn=cmd_init)
    s = sub.add_parser("analyze")
    s.add_argument("work"); s.add_argument("--steps"); s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_analyze)
    s = sub.add_parser("enroll")
    s.add_argument("work"); s.add_argument("--finalize", action="store_true")
    s.add_argument("--merge", action="append", default=[], metavar="SRC:DST",
                   help="with --finalize: count the files of folder SRC under partner folder DST "
                        "(for example voice_003:voice_001); repeatable")
    s.add_argument("--allow-sparse", action="store_true",
                   help="with --finalize: accept a partner with fewer files than the minimum (down to 1)")
    s.set_defaults(fn=cmd_enroll)
    s = sub.add_parser("plan")
    s.add_argument("work"); s.add_argument("--thumbs", action="store_true", help="add thumbnails to the storyboard")
    s.set_defaults(fn=cmd_plan)
    s = sub.add_parser("review")
    s.add_argument("work"); s.add_argument("--plan", help="plan version, e.g. v002 (default: latest)")
    s.add_argument("--port", type=int, help="port (default: policy review.port, 8765)")
    s.add_argument("--no-open", action="store_true", help="do not open the browser")
    s.set_defaults(fn=cmd_review)
    s = sub.add_parser("render")
    s.add_argument("work"); s.add_argument("--plan", help="plan version, e.g. v002 (default: latest)")
    s.set_defaults(fn=cmd_render)
    s = sub.add_parser("qc")
    s.add_argument("work"); s.add_argument("--version")
    s.set_defaults(fn=cmd_qc)
    s = sub.add_parser("run")
    s.add_argument("work")
    s.set_defaults(fn=cmd_run)
    a = ap.parse_args(argv)
    setup_logging(a.verbose)
    try:
        return a.fn(a)
    except ProjectError as e:
        log.error("%s", e)
        return 1


if __name__ == "__main__":
    sys.exit(main())
