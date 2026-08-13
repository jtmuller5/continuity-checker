"""One command per stage.

    python3 -m cinema info                 what the spec says
    python3 -m cinema bible                the ground truth and the checker's questions
    python3 -m cinema render               every shot that is not already cached
    python3 -m cinema render --shot s03    one shot, which is the re-render step
    python3 -m cinema assemble             join what is on disk into out/cut.mp4
    python3 -m cinema build                render then assemble
    python3 -m cinema timings              measured wall clock and spend per shot

`render` and `build` are cached and resumable: a shot is redrawn when its
inputs change and skipped when they have not. `--shot` names the shots to redo
whatever the cache says, and it may be repeated.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import assemble as assemble_mod
from . import backends, render as render_mod, spec


def _out_dir(args) -> Path:
    return Path(args.out)


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


def cmd_bible(args) -> int:
    """The ground truth, and the two things it produces.

    Printed rather than described, because the whole claim of this entry is that
    the check is against something written down. This is that thing.
    """
    film = _load(args)
    bible = film.bible
    if not bible.attributes:
        print(f"{args.spec} has no bible: there is nothing for the checker to judge against")
        return 1

    for subject in bible.subjects.values():
        print(f"{subject.kind}: {subject.name} — {subject.description}")
    print()
    for a in bible.attributes:
        detail = f"canon={a.canon}  values={', '.join(a.values)}"
        if a.changes_at:
            detail += "  changes at " + ", ".join(f"{k}->{v}" for k, v in a.changes_at.items())
        print(f"{a.name:<12} {a.rule:<12} {detail}")
    print()
    print("asked of every frame (the checker gets these, and never the canon above):")
    for q in bible.questions():
        print(f"  {q.attribute}: {q.text}")
        print(f"    answer with one of: {', '.join(q.values)}")
    if args.prompts:
        for shot in film.shots:
            print()
            print(f"--- {shot.id} prompt ---")
            print(shot.text)
    return 0


def cmd_render(args) -> int:
    film = _load(args)
    backend = backends.get(args.backend)
    if backend.bills and not args.i_will_pay:
        raise SystemExit(
            f"backend {backend.name!r} costs real money. The loop's spend cap is $0.00 "
            "(charter §3) — pass --i-will-pay only as a human who has authorised it."
        )

    try:
        config = render_mod.RenderConfig.build(
            film,
            backend.name,
            tier=args.tier,
            seed=args.seed,
            resolution=args.resolution,
        )
    except ValueError as exc:
        raise SystemExit(f"config error: {exc}")

    out = _out_dir(args)
    shots = args.shot or []
    print(
        f"render: {len(film.shots)} shot(s) considered on {backend.name} "
        f"[{config.tier} {config.resolution} seed={config.seed}]"
    )
    try:
        results = render_mod.render_film(
            film, backend, config, out, only=shots, force=args.force
        )
    except ValueError as exc:
        raise SystemExit(f"render error: {exc}")
    print("  " + render_mod.summarise(results, film, config, backend))
    return 0


def cmd_assemble(args) -> int:
    film = _load(args)
    out = _out_dir(args)
    print(f"assemble: {len(film.shots)} shots")
    cut = assemble_mod.concat(
        [render_mod.shot_path(out, s) for s in film.shots], out / "cut.mp4"
    )
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


def cmd_timings(args) -> int:
    """What renders have actually cost, in seconds and in dollars.

    Price is published; wall clock is not, and it is the number the cost model
    is missing. Every render writes one, so this reads rather than measures.
    """
    ledger = render_mod.load_ledger(_out_dir(args))
    entries = ledger["shots"]
    if not entries:
        print("nothing rendered yet")
        return 0
    print(f"{'shot':<6} {'backend':<12} {'tier':<9} {'resolution':<11} {'wall':>8} {'cost':>8}")
    for shot_id in sorted(entries):
        e = entries[shot_id]
        print(
            f"{shot_id:<6} {e.get('backend', '?'):<12} {e.get('tier', '?'):<9} "
            f"{e.get('resolution', '?'):<11} {float(e.get('wall_clock', 0)):>7.2f}s "
            f"${float(e.get('cost_usd', 0)):>7.2f}"
        )
    print()
    for group in render_mod.timings(_out_dir(args)).values():
        print(
            f"{group.backend} {group.tier} {group.resolution}: "
            f"{group.mean:.2f}s per shot over {len(group.samples)} render(s)"
        )
    total = sum(float(e.get("cost_usd", 0)) for e in entries.values())
    print(f"spent so far: ${total:.2f}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="cinema", description=__doc__)
    parser.add_argument("--spec", default="film.yaml")
    parser.add_argument("--out", default="out")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("info").set_defaults(func=cmd_info)

    p = sub.add_parser("bible")
    p.add_argument("--prompts", action="store_true", help="also print each shot's composed prompt")
    p.set_defaults(func=cmd_bible)

    for name, func in (("render", cmd_render), ("build", cmd_build)):
        p = sub.add_parser(name)
        p.add_argument("--backend", default=backends.DEFAULT)
        p.add_argument(
            "--shot",
            action="append",
            help="re-render this shot whatever the cache says; repeatable",
        )
        p.add_argument("--force", action="store_true", help="re-render every shot")
        p.add_argument("--tier", choices=sorted(render_mod.pricing.TIERS), help="model tier")
        p.add_argument("--seed", type=int, help="sampler seed, for a backend that has one")
        p.add_argument("--resolution", help="override the spec's WxH")
        p.add_argument(
            "--i-will-pay",
            action="store_true",
            help="permit a backend that bills. Not the loop's to pass.",
        )
        p.set_defaults(func=func)

    sub.add_parser("assemble").set_defaults(func=cmd_assemble)
    sub.add_parser("timings").set_defaults(func=cmd_timings)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
