"""One command per stage.

    python3 -m cinema info                 what the spec says
    python3 -m cinema render               every shot, to out/shots/
    python3 -m cinema render --shot s03    one shot, which is the re-render step
    python3 -m cinema assemble             join what is on disk into out/cut.mp4
    python3 -m cinema build                render then assemble
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import assemble as assemble_mod
from . import backends, spec


def _out_dir(args) -> Path:
    return Path(args.out)


def _shot_path(out: Path, shot) -> Path:
    return out / "shots" / f"{shot.id}-{shot.slug}.mp4"


def _load(args):
    try:
        return spec.load(args.spec)
    except (spec.SpecError, KeyError) as exc:
        raise SystemExit(f"spec error: {exc}")


def cmd_info(args) -> int:
    film = _load(args)
    print(f"{film.title} — {len(film.shots)} shots, {film.seconds}s, {film.resolution} @ {film.fps}fps")
    for s in film.shots:
        state = "  ".join(f"{k}={v}" for k, v in sorted(s.continuity.items()))
        print(f"  {s.id} {s.slug:<10} {s.seconds}s  [{s.key()}]  {state}")
    if film.expected_breaks:
        print("answer key (never given to the checker):")
        for b in film.expected_breaks:
            print(f"  {b.shot} {b.attribute}: {b.before} -> {b.after}")
    return 0


def cmd_render(args) -> int:
    film = _load(args)
    backend = backends.get(args.backend)
    if backend.bills and not args.i_will_pay:
        raise SystemExit(
            f"backend {backend.name!r} costs real money. The loop's spend cap is $0.00 "
            "(charter §3) — pass --i-will-pay only as a human who has authorised it."
        )

    out = _out_dir(args)
    shots = [film.shot(args.shot)] if args.shot else film.shots
    print(f"render: {len(shots)} shot(s) on {backend.name}")
    for s in shots:
        backend.render(s, film, _shot_path(out, s))
    return 0


def cmd_assemble(args) -> int:
    film = _load(args)
    out = _out_dir(args)
    print(f"assemble: {len(film.shots)} shots")
    cut = assemble_mod.concat([_shot_path(out, s) for s in film.shots], out / "cut.mp4")
    facts = assemble_mod.probe(cut)
    print(
        f"  {facts['seconds']}s  {facts['width']}x{facts['height']}  "
        f"{facts['frames']} frames  {facts['format']}"
    )
    expected = film.seconds
    if abs(facts["seconds"] - expected) > 0.5:
        print(f"  WARNING: the cut is {facts['seconds']}s but the spec says {expected}s")
        return 1
    return 0


def cmd_build(args) -> int:
    return cmd_render(args) or cmd_assemble(args)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="cinema", description=__doc__)
    parser.add_argument("--spec", default="film.yaml")
    parser.add_argument("--out", default="out")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("info").set_defaults(func=cmd_info)

    for name, func in (("render", cmd_render), ("build", cmd_build)):
        p = sub.add_parser(name)
        p.add_argument("--backend", default=backends.DEFAULT)
        p.add_argument("--shot", help="render one shot only")
        p.add_argument(
            "--i-will-pay",
            action="store_true",
            help="permit a backend that bills. Not the loop's to pass.",
        )
        p.set_defaults(func=func)

    sub.add_parser("assemble").set_defaults(func=cmd_assemble)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
