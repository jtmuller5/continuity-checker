"""Grade a continuity report against the answer key.

The checker is never given `expected_breaks`; this module is the only thing that
reads both. It runs after the fact, on the written report, so there is no path
by which the key can reach the reader — that separation is the whole claim the
entry makes, and a scorer that ran inside the check would quietly destroy it.

Two numbers come out, and they answer different questions:

- **Breaks.** Did it find the planted ones, and did it invent any? A break found
  in the right shot on the right attribute but with the wrong values is neither
  a clean hit nor an ordinary false alarm — it is a `near miss`, counted against
  both totals and named separately, because "saw something here" and "read it
  correctly" fail for different reasons and get fixed in different places.
- **Cells.** Every shot × every tracked attribute: did the reader see what the
  spec declared? This is where "flags nothing it should not" is really settled.
  A single misread cell in a clean shot is what manufactures a false alarm, and
  it is visible here a stage before it becomes one.

`disputed` and `unanswered` cells are counted apart from both. The checker
declining to answer is a different failure from answering wrongly, and the
stated risk on this idea is detection quality on subtle breaks — a checker that
goes quiet on the subtle ones must not score as though it got them right.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

AGREED = "agreed"
MISREAD = "misread"
DISPUTED = "disputed"
UNANSWERED = "unanswered"


@dataclass(frozen=True)
class Cell:
    """One attribute of one shot: what the spec declared against what was read."""

    shot: str
    attribute: str
    declared: str
    read: str | None
    verdict: str


@dataclass(frozen=True)
class NearMiss:
    """The right cell, the wrong reading of it."""

    expected: object
    found: object


@dataclass(frozen=True)
class Score:
    hits: tuple = ()
    misses: tuple = ()
    false_alarms: tuple = ()
    near_misses: tuple = ()
    cells: tuple = ()
    stale_shots: tuple = ()

    @property
    def expected(self) -> int:
        return len(self.hits) + len(self.misses) + len(self.near_misses)

    @property
    def found(self) -> int:
        return len(self.hits) + len(self.false_alarms) + len(self.near_misses)

    def counted(self, verdict: str) -> tuple:
        return tuple(c for c in self.cells if c.verdict == verdict)

    @property
    def perfect(self) -> bool:
        """Every planted break found exactly, nothing else flagged, nothing dodged."""
        return not (
            self.misses
            or self.false_alarms
            or self.near_misses
            or self.counted(MISREAD)
            or self.counted(DISPUTED)
            or self.counted(UNANSWERED)
        )

    def to_dict(self) -> dict:
        as_break = lambda b: {  # noqa: E731 — one shape, used four times below
            "shot": b.shot,
            "attribute": b.attribute,
            "expected": b.before,
            "found": b.after,
            "sentence": b.sentence(),
        }
        return {
            "expected_breaks": self.expected,
            "found_breaks": self.found,
            "hits": [as_break(b) for b in self.hits],
            "misses": [as_break(b) for b in self.misses],
            "false_alarms": [as_break(b) for b in self.false_alarms],
            "near_misses": [
                {"expected": as_break(n.expected), "found": as_break(n.found)}
                for n in self.near_misses
            ],
            "cells": {
                "total": len(self.cells),
                AGREED: len(self.counted(AGREED)),
                MISREAD: [
                    {"shot": c.shot, "attribute": c.attribute, "declared": c.declared, "read": c.read}
                    for c in self.counted(MISREAD)
                ],
                DISPUTED: [{"shot": c.shot, "attribute": c.attribute} for c in self.counted(DISPUTED)],
                UNANSWERED: [{"shot": c.shot, "attribute": c.attribute} for c in self.counted(UNANSWERED)],
            },
            "stale_shots": list(self.stale_shots),
            "perfect": self.perfect,
        }


def stale_shots(film, out_dir, report) -> tuple:
    """Shots whose rendered file is newer than the report that judged them.

    Scoring reads a report off disk instead of re-running the check, which costs
    nothing and keeps the two stages honestly separate. The price is that a
    report can outlive the film it describes — and the moment that matters is
    exactly the demo: fix, re-render, then score the *old* report and watch it
    pass. This is the guard for that.
    """
    from . import render as render_mod

    when = _parsed(report.at)
    if when is None:
        return ()
    late = []
    for shot in film.shots:
        video = Path(render_mod.shot_path(out_dir, shot))
        if video.exists() and video.stat().st_mtime > when + 1:
            late.append(shot.id)
    return tuple(late)


def _parsed(at: str):
    from datetime import datetime

    try:
        return datetime.fromisoformat(at).timestamp()
    except (TypeError, ValueError):
        return None


def score(film, report, out_dir=None) -> Score:
    """Grade `report` against the film's answer key and declared continuity."""
    expected = list(film.expected_breaks)
    found = list(report.breaks)

    # `Break` equality ignores `rule`, so a derived finding compares equal to a
    # hand-written key entry. Match on the whole break first; only what is left
    # over can be a near miss.
    hits, misses, false_alarms, near = [], [], [], []
    unmatched_found = list(found)
    for want in expected:
        for i, got in enumerate(unmatched_found):
            if got == want:
                hits.append(got)
                unmatched_found.pop(i)
                break
        else:
            misses.append(want)

    still_missing = []
    for want in misses:
        for i, got in enumerate(unmatched_found):
            if (got.shot, got.attribute) == (want.shot, want.attribute):
                near.append(NearMiss(want, got))
                unmatched_found.pop(i)
                break
        else:
            still_missing.append(want)
    false_alarms = unmatched_found

    return Score(
        hits=tuple(hits),
        misses=tuple(still_missing),
        false_alarms=tuple(false_alarms),
        near_misses=tuple(near),
        cells=tuple(cells(film, report)),
        stale_shots=stale_shots(film, out_dir, report) if out_dir else (),
    )


def cells(film, report) -> list:
    """Every shot × attribute, declared against read."""
    readings = {r.shot_id: r for r in report.readings}
    out = []
    for shot in film.shots:
        reading = readings.get(shot.id)
        for name in film.bible.names:
            declared = str(shot.continuity.get(name, ""))
            if reading is None:
                out.append(Cell(shot.id, name, declared, None, UNANSWERED))
                continue
            if name in reading.disputed:
                out.append(Cell(shot.id, name, declared, None, DISPUTED))
            elif name in reading.unanswered or name not in reading.state:
                out.append(Cell(shot.id, name, declared, None, UNANSWERED))
            else:
                got = str(reading.state[name])
                out.append(
                    Cell(shot.id, name, declared, got, AGREED if got == declared else MISREAD)
                )
    return out
