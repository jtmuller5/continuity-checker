"""The continuity checker: read the film back, and say which shots broke.

This is the entry. Everything else exists so that this can run.

    frames  ->  reader  ->  the bible's vocabulary  ->  the bible's rules

Four steps, and the design rule is that each one is allowed to know less than
the one before it:

1. `cinema/frames.py` takes a few stills per shot.
2. A reader answers the bible's questions about each still — Gemini on Vertex
   AI for real, the pixel stand-in offline. It is given the question and the
   words an answer may use. It is not given the canon, the shot's declared
   state, or the answer key.
3. `bible.read()` folds each answer into the vocabulary, dropping anything
   outside it. An unrecognised answer becomes an unanswered question, never a
   silent agreement.
4. `bible.derive_breaks()` applies the per-attribute rule across the shots in
   order, and that is the finding.

Step 4 is the same function that turns the *declared* state into the answer
key. One judgement, two readings of the film: if those were two functions, a
score would be measuring the difference between them rather than the checker.

The comparison is between adjacent shots because that is what a continuity
break is — nothing about a single frame is wrong, and `derive_breaks` walks the
sequence carrying what the value was last time it was legitimately seen.

**Frames of one shot may disagree**, and that is reported rather than resolved.
Two frames saying different things is either a break inside the shot or a
checker that cannot see, and both are worth a human's attention; picking the
majority and moving on would hide both.
"""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import frames as frames_mod
from . import pricing
from .bible import Break, derive_breaks

REPORT_NAME = "continuity.json"
REPORT_VERSION = 1


@dataclass(frozen=True)
class FrameReading:
    """What one still was said to contain, before and after the vocabulary."""

    shot_id: str
    index: int
    at: float
    path: str
    answers: dict = field(default_factory=dict)  # as the reader said it
    state: dict = field(default_factory=dict)  # folded into the bible's words


@dataclass(frozen=True)
class ShotReading:
    """What a shot was said to contain, over all of its frames."""

    shot_id: str
    state: dict = field(default_factory=dict)
    unanswered: tuple = ()
    disputed: dict = field(default_factory=dict)  # attribute -> the values seen
    frames: tuple = ()


@dataclass(frozen=True)
class Report:
    film: str
    reader: str
    model: str | None
    frames_per_shot: int
    readings: tuple
    breaks: tuple
    cost: float
    at: str

    def states(self) -> list:
        return [(r.shot_id, dict(r.state)) for r in self.readings]

    def to_dict(self) -> dict:
        return {
            "version": REPORT_VERSION,
            "film": self.film,
            "reader": self.reader,
            "model": self.model,
            "frames_per_shot": self.frames_per_shot,
            "at": self.at,
            "cost_usd": self.cost,
            "shots": [
                {
                    "shot": r.shot_id,
                    "state": r.state,
                    "unanswered": list(r.unanswered),
                    "disputed": {k: list(v) for k, v in r.disputed.items()},
                    "frames": [
                        {
                            "index": f.index,
                            "at": f.at,
                            "path": f.path,
                            "answers": f.answers,
                            "state": f.state,
                        }
                        for f in r.frames
                    ],
                }
                for r in self.readings
            ],
            "breaks": [
                {
                    "shot": b.shot,
                    "attribute": b.attribute,
                    "expected": b.before,
                    "found": b.after,
                    "rule": b.rule,
                    "sentence": b.sentence(),
                }
                for b in self.breaks
            ],
        }

    def write(self, out_dir) -> Path:
        path = Path(out_dir) / REPORT_NAME
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n")
        return path


def read(out_dir) -> Report:
    """The last report, back off disk.

    `cinema score` and `cinema fix` both work from the written report rather
    than re-running the check. That keeps the reading and the judging of it in
    separate processes — nothing the scorer knows can reach the reader — and it
    means a repair is decided from the same file a human can open and argue
    with.
    """
    path = Path(out_dir) / REPORT_NAME
    if not path.exists():
        raise ValueError(f"no report at {path}: run `python3 -m cinema check` first")
    raw = json.loads(path.read_text())
    if int(raw.get("version", 0)) != REPORT_VERSION:
        raise ValueError(
            f"{path} is version {raw.get('version')}, and this build writes "
            f"version {REPORT_VERSION} — re-run the check"
        )
    readings = tuple(
        ShotReading(
            shot_id=s["shot"],
            state=dict(s.get("state") or {}),
            unanswered=tuple(s.get("unanswered") or ()),
            disputed={k: tuple(v) for k, v in (s.get("disputed") or {}).items()},
            frames=tuple(
                FrameReading(
                    s["shot"], f["index"], f["at"], f["path"],
                    dict(f.get("answers") or {}), dict(f.get("state") or {}),
                )
                for f in s.get("frames") or ()
            ),
        )
        for s in raw.get("shots") or ()
    )
    breaks = tuple(
        Break(
            shot=b["shot"],
            attribute=b["attribute"],
            before=str(b["expected"]),
            after=str(b["found"]),
            rule=b.get("rule", ""),
        )
        for b in raw.get("breaks") or ()
    )
    return Report(
        film=raw.get("film", ""),
        reader=raw.get("reader", ""),
        model=raw.get("model"),
        frames_per_shot=int(raw.get("frames_per_shot", 0)),
        readings=readings,
        breaks=breaks,
        cost=float(raw.get("cost_usd", 0.0)),
        at=raw.get("at", ""),
    )


def _relative(path, out_dir) -> str:
    """The frame's path as the report records it: short where it can be."""
    try:
        return str(Path(path).relative_to(Path(out_dir)))
    except ValueError:
        return str(path)


def reconcile(states, attributes) -> tuple:
    """One shot's per-frame states, folded into one state.

    Returns `(state, unanswered, disputed)`. An attribute the frames disagree
    about is put in `disputed` and left out of the state entirely: a value two
    frames contradict is not evidence, and reporting a break from it would be
    reporting a coin toss. An attribute no frame could answer is `unanswered`,
    which is a question for the author and not a finding.

    `attributes` is every attribute the bible tracks, not the ones that came
    back. An attribute nothing answered has to be named here or it vanishes:
    silence would read as a clean shot.
    """
    agreed, unanswered, disputed = {}, [], {}
    for name in attributes:
        counts = Counter(s[name] for s in states if name in s)
        if not counts:
            unanswered.append(name)
            continue
        ranked = counts.most_common()
        if len(ranked) > 1 and ranked[0][1] == ranked[1][1]:
            disputed[name] = tuple(sorted(counts))
            continue
        agreed[name] = ranked[0][0]
    return agreed, tuple(unanswered), disputed


def check_film(
    film,
    out_dir,
    reader,
    *,
    per_shot: int | None = None,
    crop=None,
    model: str | None = None,
    log=print,
    **options,
) -> Report:
    """Sample, read, fold, judge. Returns the report; writing it is the caller's."""
    if not film.bible.attributes:
        raise ValueError("the spec has no bible, so there is nothing to check against")

    settings = dict(film.check)
    per_shot = per_shot or int(settings.get("frames_per_shot", frames_mod.DEFAULT_PER_SHOT))
    crop = crop if crop is not None else settings.get("crop")
    if model is None:
        model = settings.get("model") if getattr(reader, "bills", False) else None
    if getattr(reader, "bills", False) and model is None:
        model = getattr(reader, "DEFAULT_MODEL", None)

    # Questions and vocabulary only. This is the line the score depends on: the
    # canon, every shot's declared continuity and `expected_breaks` all stay on
    # this side of it.
    questions = film.bible.questions()

    if model:
        options.setdefault("model", model)

    stills = frames_mod.sample(film, out_dir, per_shot=per_shot, crop=crop, log=log)
    by_shot = {}
    for still in stills:
        answers = reader.read(still, questions, log=log, **options)
        state = film.bible.read({k: v for k, v in answers.items() if v is not None})
        by_shot.setdefault(still.shot_id, []).append(
            FrameReading(
                still.shot_id,
                still.index,
                still.at,
                _relative(still.path, out_dir),
                answers,
                state,
            )
        )

    readings = []
    for shot in film.shots:
        got = by_shot.get(shot.id, [])
        state, unanswered, disputed = reconcile(
            [f.state for f in got], film.bible.names
        )
        readings.append(ShotReading(shot.id, state, unanswered, disputed, tuple(got)))

    breaks = derive_breaks(film.bible, [(r.shot_id, r.state) for r in readings])
    cost = pricing.check_cost(len(stills), model) if getattr(reader, "bills", False) else 0.0

    return Report(
        film=film.title,
        reader=reader.name,
        model=model,
        frames_per_shot=per_shot,
        readings=tuple(readings),
        breaks=tuple(breaks),
        cost=cost,
        at=datetime.now(timezone.utc).isoformat(timespec="seconds"),
    )
