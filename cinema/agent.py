"""The check-and-fix loop as four steps, and the ADK graph that runs them.

The loop the entry describes is one agent turn: **perceive** the film by reading
frames back, **judge** what the reading means against the shot bible, **act** by
repairing the earliest break and re-rendering only what that staled, then
**verify** by reading the new film and grading it. Every step is a real one, and
none is skipped because the answer is already known.

The four steps below are plain functions. They take a `Job`, which holds the
stages the CLI already implements — render, assemble, check, score — so this
module orchestrates the pipeline without reaching into it, and a test can drive
the whole loop with stand-in stages and no ffmpeg.

`run_steps` runs them in order in this process, and that is what `cinema fix`
does. `build_workflow` wraps the same four functions as nodes of a
`google.adk.workflow.Workflow`, which is what `cinema agent` runs: the graph is
Google's Agent Development Kit, the nodes are the functions below, and the two
paths cannot drift because there is one copy of each step.

The ADK import is deliberately inside the functions that need it. A judge with
no Google Cloud account clones the repo and runs `build`, `check` and `fix`
first, and those must not pay for an import they never use.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import compare as compare_mod
from . import fixes as fixes_mod
from . import frames as frames_mod
from . import render as render_mod
from . import score as score_mod

#: The order the steps run in, and the names the graph gives its nodes.
STEPS = ("perceive", "judge", "act", "verify")

APP_NAME = "continuity-checker"


class AgentError(RuntimeError):
    """A step could not finish. Carries the exit code the CLI should return."""

    def __init__(self, message: str, code: int = 1):
        super().__init__(message)
        self.code = code


@dataclass
class Job:
    """One run of the loop: where it works, and what it may call.

    The four stages are injected rather than imported so that this module owns
    the order of the work and nothing else. `cinema/cli.py` passes the commands
    a person would otherwise type; a test passes recorders.
    """

    out: Path
    load: Callable[[], object]
    read_report: Callable[[], object]
    check: Callable[[], int]
    render: Callable[[], int]
    assemble: Callable[[], int]
    score: Callable[[], int]
    say: Callable[[str], None] = print

    # What the run produced. The graph carries a summary of each step; the
    # artefacts themselves stay here, because a report and a PNG are not things
    # to serialise into a session.
    report: object = None
    repairs: dict = field(default_factory=dict)
    plates: dict = field(default_factory=dict)
    exit_code: int = 0


# --- the four steps ------------------------------------------------------


def perceive(job: Job) -> dict:
    """Read the film back, and use the last reading only if it still describes it.

    A report written before a shot was re-rendered describes a film that no
    longer exists, and acting on it is how a demo of this kind lies. So the step
    checks the report against what is on disk and re-reads the film when it has
    moved — which is the one decision this step makes.
    """
    film = job.load()
    report = None
    reason = ""
    try:
        report = job.read_report()
    except (ValueError, SystemExit) as exc:
        reason = str(exc).split(":")[0] or "there is no report"

    if report is not None:
        stale = score_mod.stale_shots(film, job.out, report)
        if stale:
            reason = f"the report is older than {', '.join(stale)}"
            report = None

    checked = report is None
    if checked:
        job.say(f"perceive: {reason}, so the film is read again")
        if job.check():
            raise AgentError("perceive: the check did not finish")
        report = job.read_report()
    else:
        job.say(f"perceive: the reading from {report.at} still describes the film on disk")

    job.report = report
    job.say(f"  {len(report.breaks)} break(s) reported by {report.reader}")
    return {
        "step": "perceive",
        "reader": report.reader,
        "at": report.at,
        "re_read": checked,
        "breaks": [b.sentence() for b in report.breaks],
    }


def judge(job: Job) -> dict:
    """Turn the findings into the repair each one asks for.

    Nothing here looks at the film. The break already says what the bible
    declared and what the frames showed, so the repair is the declared value —
    and deriving it anywhere else would be a second opinion about a question
    that has already been answered.
    """
    report = job.report
    if report is None:
        raise AgentError("judge: nothing has been perceived yet")

    job.repairs = fixes_mod.corrections(report.breaks)
    if not job.repairs:
        job.say("judge: the reading found no breaks, so there is nothing to repair")
        return {"step": "judge", "repairs": {}}

    job.say(f"judge: {len(report.breaks)} break(s) from the reading")
    for shot_id, cells in sorted(job.repairs.items()):
        for name, value in sorted(cells.items()):
            job.say(f"  {shot_id} {name} -> {value}")
    return {"step": "judge", "repairs": job.repairs}


def act(job: Job) -> dict:
    """Keep the broken frame, record the repair, and re-render what it staled.

    The repair is a layer over the spec rather than an edit to it, so the
    planted breaks the checker is scored against stay where they are. The cache
    decides what is re-rendered: a repaired shot's key moves, and a backend that
    chains makes every later shot stale with it.
    """
    if not job.repairs:
        return {"step": "act", "repaired": [], "plates": []}

    film = job.load()
    plates = job.out / "before-after"
    for shot_id in sorted(job.repairs):
        shot = film.shot(shot_id)
        # Before anything is overwritten. A re-rendered shot replaces its own
        # file, so this frame cannot be recovered afterwards.
        job.plates[shot_id] = frames_mod.grab(
            render_mod.shot_path(job.out, shot),
            shot.seconds / 2,
            plates / f"{shot_id}-before.png",
        )
    job.say(f"act: kept {len(job.plates)} broken frame(s) in {plates}")

    fixes_mod.save(
        job.out,
        fixes_mod.merge(fixes_mod.load(job.out), job.repairs),
        note=f"from {job.report.reader} at {job.report.at}",
    )
    if job.render() or job.assemble():
        raise AgentError("act: the re-render did not finish")
    return {
        "step": "act",
        "repaired": sorted(job.repairs),
        "plates": [str(p) for p in job.plates.values()],
    }


def verify(job: Job) -> dict:
    """Read the repaired film back, show both frames, and grade the result.

    The film is checked again rather than declared fixed, and the plate is made
    from the frame kept in `act` beside the one that replaced it. The scorer runs
    last and on the written report, so nothing it knows can reach the reader.
    """
    if not job.repairs:
        job.say("verify: nothing was repaired, so there is nothing to verify")
        return {"step": "verify", "exit": 0, "verified": False}

    job.say("")
    if job.check():
        raise AgentError("verify: the check did not finish")

    film = job.load()
    for shot_id, before_path in sorted(job.plates.items()):
        shot = film.shot(shot_id)
        after = frames_mod.grab(
            render_mod.shot_path(job.out, shot),
            shot.seconds / 2,
            job.out / "before-after" / f"{shot_id}-after.png",
        )
        # The break says both halves: `after` is what was rendered and wrong,
        # `before` is what the bible asked for. Labelling both sides with the
        # repaired value would caption the broken frame with the fix.
        flagged = [b for b in job.report.breaks if b.shot == shot_id]
        wrong = ", ".join(f"{b.attribute}={b.after}" for b in flagged)
        right = ", ".join(f"{b.attribute}={b.before}" for b in flagged)
        made = compare_mod.plate(
            before_path,
            after,
            job.out / "before-after" / f"{shot_id}.png",
            left=f"{shot_id} before  ({wrong} — flagged)",
            right=f"{shot_id} after  ({right} — re-rendered)",
        )
        job.say(f"  plate: {made}")

    job.say("")
    job.exit_code = job.score()
    return {"step": "verify", "exit": job.exit_code, "verified": True}


#: The step functions by name, in the order they run.
FUNCTIONS = {"perceive": perceive, "judge": judge, "act": act, "verify": verify}


def run_steps(job: Job) -> list:
    """The loop, in this process. `cinema fix` is this."""
    summaries = []
    for name in STEPS:
        summaries.append(FUNCTIONS[name](job))
    return summaries


# --- the same four steps, as an ADK graph --------------------------------


def build_workflow(job: Job):
    """The loop as a `google.adk.workflow.Workflow`: four nodes, one edge chain.

    The nodes are the functions above and nothing else, so what the graph runs
    is what `cinema fix` runs. Each node writes its summary into the session
    state under its own name, which is what a resumed or inspected run reads.
    """
    from google.adk.workflow import FunctionNode, START, Workflow

    def node(name: str):
        step = FUNCTIONS[name]

        def run(ctx) -> dict:
            summary = step(job)
            ctx.state[name] = summary
            return summary

        run.__name__ = name
        return FunctionNode(name=name, func=run)

    chain = tuple(node(name) for name in STEPS)
    return Workflow(
        name="continuity_agent",
        description="Perceive a rendered film, judge it against the shot bible, repair the earliest break, and verify the result.",
        edges=[(START, *chain)],
    )


async def _drive(workflow, said: Callable[[str], None]) -> dict:
    """Run the graph once through ADK's runner, and collect what each node said."""
    from google.adk.runners import InMemoryRunner
    from google.genai import types

    runner = InMemoryRunner(agent=workflow, app_name=APP_NAME)
    session = await runner.session_service.create_session(
        app_name=APP_NAME, user_id="loop"
    )
    outputs = {}
    try:
        async for event in runner.run_async(
            user_id="loop",
            session_id=session.id,
            new_message=types.Content(
                role="user", parts=[types.Part(text="check this film and fix what broke")]
            ),
        ):
            summary = getattr(event, "output", None)
            if isinstance(summary, dict) and summary.get("step"):
                outputs[summary["step"]] = summary
                said(f"  [adk] {summary['step']} done")
    finally:
        await runner.close()
    return outputs


def run_workflow(job: Job) -> dict:
    """Build the graph and run it. Returns each node's summary, by step name."""
    return asyncio.run(_drive(build_workflow(job), job.say))
