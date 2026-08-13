"""One command per stage.

    python3 -m cinema info                 what the spec says
    python3 -m cinema bible                the ground truth and the checker's questions
    python3 -m cinema render               every shot that is not already cached
    python3 -m cinema render --shot s03    one shot, which is the re-render step
    python3 -m cinema assemble             join what is on disk into out/cut.mp4
    python3 -m cinema build                render then assemble
    python3 -m cinema check                read the cut back and report the breaks
    python3 -m cinema score                grade that report against the answer key
    python3 -m cinema fix                  repair what broke, re-render only that
    python3 -m cinema fix --revert         put the planted breaks back
    python3 -m cinema timings              measured wall clock and spend per shot
    python3 -m cinema publish              build the hosted page from the last run
    python3 -m cinema demo                 cut the submission video from the last run

`render` and `build` are cached and resumable: a shot is redrawn when its
inputs change and skipped when they have not. `--shot` names the shots to redo
whatever the cache says, and it may be repeated.

`check` reads the film; `score` is the only thing that reads the answer key as
well, and it runs afterwards on the written report so nothing it knows can
reach the reader. `fix` is the whole demo in one command — keep the broken
frame, repair, re-render the shots whose keys moved, check again, and score.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import assemble as assemble_mod
from . import compare as compare_mod
from . import demo as demo_mod
from . import fixes as fixes_mod
from . import publish as publish_mod
from . import score as score_mod
from . import backends, check as check_mod, frames as frames_mod, readers, render as render_mod, spec


def _out_dir(args) -> Path:
    return Path(args.out)


def _load(args):
    """The film, with any recorded repair layered over it.

    Every command loads through here, so once `fix` has written `out/fixes.json`
    the repaired film is the one the renderer, the checker and the scorer all
    see. `cinema fix --revert` puts it back.
    """
    try:
        return spec.load(args.spec, fixes=fixes_mod.load(_out_dir(args)))
    except (spec.SpecError, KeyError, ValueError) as exc:
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


def cmd_check(args) -> int:
    """Read the rendered film back and say which shots broke continuity.

    Exit code is 0 whether or not breaks were found, because this film is meant
    to have two and the demo is `check` followed by `render --shot`. `--strict`
    is the linter behaviour, for a pipeline that wants a clean film or nothing.
    """
    film = _load(args)
    reader = readers.get(args.reader)
    if reader.bills and not args.i_will_pay:
        raise SystemExit(
            f"reader {reader.name!r} costs real money. The loop's spend cap is $0.00 "
            "(charter §3) — pass --i-will-pay only as a human who has authorised it."
        )

    out = _out_dir(args)
    per_shot = args.frames or int(
        film.check.get("frames_per_shot", frames_mod.DEFAULT_PER_SHOT)
    )
    print(f"check: {len(film.shots)} shots, {per_shot} frames each, on {reader.name}")
    if hasattr(reader, "describe"):
        print(f"  {reader.describe()}")
    try:
        report = check_mod.check_film(
            film, out, reader, per_shot=per_shot, model=args.model
        )
    except (ValueError, frames_mod.FrameError) as exc:
        raise SystemExit(f"check error: {exc}")

    print(f"  read {per_shot * len(film.shots)} frames for ${report.cost:.4f}")
    for reading in report.readings:
        state = "  ".join(f"{k}={v}" for k, v in sorted(reading.state.items()))
        print(f"  {reading.shot_id}  {state}")
        for attribute, values in sorted(reading.disputed.items()):
            print(
                f"    ? {attribute}: the frames disagree ({', '.join(values)}) — either the "
                "break is inside this shot, or the checker cannot see it"
            )
        for attribute in reading.unanswered:
            print(f"    ? {attribute}: no frame answered, so it was not judged")

    print()
    if not report.breaks:
        print("no continuity breaks found")
    else:
        print(f"{len(report.breaks)} continuity break(s):")
        for b in report.breaks:
            print(
                f"  {b.shot}  {b.attribute}: should be {b.before}, found {b.after}  ({b.rule})"
            )
        # Earliest first, because a backend that chains makes every later shot
        # stale: fixing shot 3 re-renders 4 and 5 anyway.
        print(f"fix the earliest first: python3 -m cinema render --shot {report.breaks[0].shot}")
    print(f"  report: {report.write(out)}")
    return 1 if (report.breaks and args.strict) else 0


def _report(args):
    try:
        return check_mod.read(_out_dir(args))
    except ValueError as exc:
        raise SystemExit(f"report error: {exc}")


def cmd_score(args) -> int:
    """Grade the last report against the answer key the checker never saw.

    Exit 1 on anything short of perfect, so this is the command a pipeline runs:
    a missed break and an invented one are both failures, and so is a shot the
    checker declined to read.
    """
    film = _load(args)
    report = _report(args)
    result = score_mod.score(film, report, _out_dir(args))

    if result.stale_shots:
        print(
            f"score: the report is older than {', '.join(result.stale_shots)} on disk — "
            "it judged a film that has since been re-rendered. Run `check` again."
        )
        if not args.allow_stale:
            return 2

    print(f"score: {result.expected} break(s) planted, {result.found} found")
    for b in result.hits:
        print(f"  hit          {b.sentence()}")
    for b in result.misses:
        print(f"  MISSED       {b.sentence()}")
    for n in result.near_misses:
        print(
            f"  near miss    {n.expected.shot} {n.expected.attribute}: expected "
            f"{n.expected.before}->{n.expected.after}, read {n.found.before}->{n.found.after}"
        )
    for b in result.false_alarms:
        print(f"  FALSE ALARM  {b.sentence()}")

    agreed = result.counted(score_mod.AGREED)
    print(f"  {len(agreed)}/{len(result.cells)} cells read as declared")
    for verdict, label in (
        (score_mod.MISREAD, "misread"),
        (score_mod.DISPUTED, "disputed"),
        (score_mod.UNANSWERED, "unanswered"),
    ):
        for c in result.counted(verdict):
            detail = f" (declared {c.declared}, read {c.read})" if c.read else ""
            print(f"    {label:<11} {c.shot} {c.attribute}{detail}")

    out = _out_dir(args) / "score.json"
    out.write_text(json.dumps(result.to_dict(), indent=2) + "\n")
    print(f"  written: {out}")
    if not result.perfect:
        verdict = "not clean — see above"
    elif result.expected:
        verdict = "every planted break found, nothing else flagged"
    else:
        # A repaired film scores here, and it has no breaks left to find. Saying
        # it "found every break" would read as an accuracy claim it did not earn.
        verdict = "the film declares no breaks and none were found"
    print(f"verdict: {verdict}")
    return 0 if result.perfect else 1


def cmd_fix(args) -> int:
    """Repair the shots the checker flagged, and re-render only those.

    This is the demo. Each step is a real one and none of them is skipped when
    the answer is already known: the broken frame is kept before anything is
    overwritten, the repair is read off the finding, the cache decides what is
    re-rendered, and the film is checked again afterwards rather than declared
    fixed.
    """
    out = _out_dir(args)
    if args.revert:
        print("fix --revert: dropped the repairs" if fixes_mod.clear(out) else "fix --revert: nothing was fixed")
        print("  re-render with: python3 -m cinema build")
        return 0

    film = _load(args)
    report = _report(args)
    if not report.breaks:
        print("fix: the last report found no breaks, so there is nothing to repair")
        return 0

    repairs = fixes_mod.corrections(report.breaks)
    print(f"fix: {len(report.breaks)} break(s) from the last report")
    for shot_id, cells in sorted(repairs.items()):
        for name, value in sorted(cells.items()):
            print(f"  {shot_id} {name} -> {value}")

    # Before anything is overwritten. A re-rendered shot replaces its own file,
    # so this frame cannot be recovered afterwards.
    plates = out / "before-after"
    before = {}
    for shot_id in sorted(repairs):
        shot = film.shot(shot_id)
        before[shot_id] = frames_mod.grab(
            render_mod.shot_path(out, shot),
            shot.seconds / 2,
            plates / f"{shot_id}-before.png",
        )
    print(f"  kept {len(before)} broken frame(s) in {plates}")

    fixes_mod.save(
        out,
        fixes_mod.merge(fixes_mod.load(out), repairs),
        note=f"from {report.reader} at {report.at}",
    )
    film = _load(args)  # the repaired film: the shot keys have moved

    args.shot, args.force = None, False
    if cmd_render(args) or cmd_assemble(args):
        return 1

    print()
    if cmd_check(args):
        return 1

    for shot_id, before_path in sorted(before.items()):
        shot = film.shot(shot_id)
        after = frames_mod.grab(
            render_mod.shot_path(out, shot),
            shot.seconds / 2,
            plates / f"{shot_id}-after.png",
        )
        # The break says both halves: `after` is what was rendered and wrong,
        # `before` is what the bible asked for. Labelling both sides with the
        # repaired value would caption the broken frame with the fix.
        flagged = [b for b in report.breaks if b.shot == shot_id]
        wrong = ", ".join(f"{b.attribute}={b.after}" for b in flagged)
        right = ", ".join(f"{b.attribute}={b.before}" for b in flagged)
        made = compare_mod.plate(
            before_path,
            after,
            plates / f"{shot_id}.png",
            left=f"{shot_id} before  ({wrong} — flagged)",
            right=f"{shot_id} after  ({right} — re-rendered)",
        )
        print(f"  plate: {made}")

    print()
    return cmd_score(args)


def cmd_publish(args) -> int:
    """Build the hosted page out of the last run's own output.

    Nothing is typed into the page: the figures are read from the report and the
    score on disk, so a page that survives a worse run says the worse thing.
    """
    try:
        index = publish_mod.publish(_out_dir(args), Path(args.site), repo=args.repo)
    except publish_mod.PublishError as exc:
        print(f"publish: {exc}")
        return 1
    print(f"publish: wrote {index}")
    for asset in sorted((Path(args.site) / publish_mod.ASSETS).iterdir()):
        print(f"  asset: {asset}")
    return 0


def cmd_demo(args) -> int:
    """Cut the submission video out of the last run's own output.

    The console panels in it are `check` and `score` run here, not a transcript,
    and the figures come off the report and the score on disk.
    """
    try:
        made = demo_mod.build(_out_dir(args), Path(args.dest))
    except demo_mod.DemoError as exc:
        print(f"demo: {exc}")
        return 1
    print(f"demo: wrote {made}")
    return 0


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

    def render_options(p):
        p.add_argument("--backend", default=backends.DEFAULT)
        p.add_argument("--tier", choices=sorted(render_mod.pricing.TIERS), help="model tier")
        p.add_argument("--seed", type=int, help="sampler seed, for a backend that has one")
        p.add_argument("--resolution", help="override the spec's WxH")
        p.add_argument(
            "--i-will-pay",
            action="store_true",
            help="permit a backend or reader that bills. Not the loop's to pass.",
        )

    def check_options(p):
        p.add_argument("--reader", default=readers.DEFAULT, help="who looks at the frames")
        p.add_argument("--frames", type=int, help="stills per shot; the spec's default otherwise")
        p.add_argument("--model", help="the checker's model, for a reader that has one")

    for name, func in (("render", cmd_render), ("build", cmd_build)):
        p = sub.add_parser(name)
        render_options(p)
        p.add_argument(
            "--shot",
            action="append",
            help="re-render this shot whatever the cache says; repeatable",
        )
        p.add_argument("--force", action="store_true", help="re-render every shot")
        p.set_defaults(func=func)

    sub.add_parser("assemble").set_defaults(func=cmd_assemble)

    p = sub.add_parser("check")
    check_options(p)
    p.add_argument("--strict", action="store_true", help="exit non-zero when a break is found")
    p.add_argument(
        "--i-will-pay",
        action="store_true",
        help="permit a reader that bills. Not the loop's to pass.",
    )
    p.set_defaults(func=cmd_check)

    p = sub.add_parser("score")
    p.add_argument(
        "--allow-stale",
        action="store_true",
        help="score a report that is older than the rendered film. Says nothing useful.",
    )
    p.set_defaults(func=cmd_score)

    # `fix` runs render, check and score, so it carries all three sets of
    # options. The defaults below are the ones those commands would have parsed
    # for themselves.
    p = sub.add_parser("fix")
    render_options(p)
    check_options(p)
    p.add_argument("--revert", action="store_true", help="drop every repair and go back")
    p.set_defaults(func=cmd_fix, shot=None, force=False, strict=False, allow_stale=False)

    sub.add_parser("timings").set_defaults(func=cmd_timings)

    p = sub.add_parser("demo")
    p.add_argument("--dest", default="out/demo.mp4", help="where the submission video is written")
    p.set_defaults(func=cmd_demo)

    p = sub.add_parser("publish")
    p.add_argument("--site", default="docs", help="where the hosted page is written")
    p.add_argument("--repo", default=publish_mod.REPO, help="the public source repository")
    p.set_defaults(func=cmd_publish)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
