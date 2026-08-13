"""Read and validate the film spec.

One spec file describes the whole cut. Everything downstream (rendering, the
continuity check, the re-render of a single shot) reads it, so a mistake here
is caught before any second of video is billed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field, replace
from pathlib import Path

import yaml

from . import bible as bible_mod
from .bible import Break  # noqa: F401. Re-exported: one Break, wherever it was found

# Veo 3.1 reference-image-to-video only accepts 8 seconds, and the re-render
# step depends on it. notes/render-cost.md has the citation.
SHOT_SECONDS = 8


class SpecError(ValueError):
    """The spec is wrong in a way that would waste a render."""


@dataclass(frozen=True)
class Shot:
    id: str
    slug: str
    seconds: int
    prompt: str
    continuity: dict
    # What is actually sent to the backend: the line above plus the continuity
    # clauses the bible writes. Empty when the spec has no bible.
    generation_prompt: str = ""

    @property
    def text(self) -> str:
        return self.generation_prompt or self.prompt

    def key(self) -> str:
        """Stable identity of this shot's render inputs.

        Two shots with the same key must produce the same file, which is what
        makes caching and a single-shot re-render possible. It hashes the
        composed prompt, so editing the bible's wardrobe clause re-renders the
        shots that clause reaches, and the author line alone would not notice.
        """
        payload = json.dumps(
            {
                "id": self.id,
                "seconds": self.seconds,
                "prompt": " ".join(self.text.split()),
                "continuity": self.continuity,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:12]


@dataclass(frozen=True)
class Film:
    title: str
    fps: int
    aspect: str
    resolution: str
    continuity_attributes: list
    shots: list
    expected_breaks: list = field(default_factory=list)
    # The ground truth the checker judges against: subjects, the vocabulary of
    # each attribute, and the rule that says whether a change is an error.
    bible: bible_mod.Bible = field(default_factory=bible_mod.Bible)
    # Render defaults: model tier, seed, audio. The command line overrides
    # them; `cinema/render.py` folds them into the cache key.
    render: dict = field(default_factory=dict)
    # Check defaults: frames per shot, the band of the frame worth reading,
    # the checker's model. `cinema/check.py` reads them.
    check: dict = field(default_factory=dict)

    @property
    def width(self) -> int:
        return int(self.resolution.split("x")[0])

    @property
    def height(self) -> int:
        return int(self.resolution.split("x")[1])

    @property
    def seconds(self) -> int:
        return sum(s.seconds for s in self.shots)

    def shot(self, shot_id: str) -> Shot:
        for s in self.shots:
            if s.id == shot_id:
                return s
        raise SpecError(f"no shot {shot_id!r} in the spec")

    def states(self) -> list:
        """The declared continuity of every shot, in order.

        The answer key is derived from this. The checker is handed the same
        shape, read out of the frames instead, and that is what makes the two
        comparable. See `cinema/bible.py`.
        """
        return [(s.id, dict(s.continuity)) for s in self.shots]


def load(path, fixes=None) -> Film:
    """The film as written, optionally with a repair layered over it.

    `fixes` is `{shot_id: {attribute: value}}`, what `cinema fix` decided a
    shot should have been rendered with. It is applied here rather than written
    back into the spec file, because the planted breaks in that file are the
    fixture this entry scores itself on and a tool that edits its own answer key
    proves nothing. A fixed cell is dropped from `expected_breaks` at the same
    time, so the derived-versus-declared check below still runs, and still
    fails if a repair introduced a break of its own.
    """
    raw = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, dict):
        raise SpecError(f"{path} is not a mapping")

    try:
        bible = bible_mod.load(raw.get("bible"))
    except (bible_mod.BibleError, KeyError) as exc:
        raise SpecError(f"bible: {exc}")

    # The bible names the attributes when there is one. `continuity_attributes`
    # is the older, flatter form: a bare list of names with no vocabulary and no
    # rule, which is enough to render the placeholder cut and not enough to
    # check it. Both may be present only if they agree.
    listed = list(raw.get("continuity_attributes") or [])
    attributes = bible.names or listed
    if not attributes:
        raise SpecError("no continuity attributes: the checker would have nothing to compare")
    if listed and bible.names and listed != bible.names:
        raise SpecError(
            f"continuity_attributes says {', '.join(listed)} and the bible says "
            f"{', '.join(bible.names)}"
        )

    patches = {str(k): dict(v) for k, v in (fixes or {}).items()}

    shots = []
    seen = set()
    for entry in raw.get("shots") or []:
        continuity = dict(entry.get("continuity") or {})
        continuity.update(patches.get(str(entry["id"]), {}))
        shot = Shot(
            id=entry["id"],
            slug=entry.get("slug", entry["id"]),
            seconds=int(entry.get("seconds", SHOT_SECONDS)),
            prompt=" ".join(str(entry["prompt"]).split()),
            continuity=continuity,
        )
        if shot.id in seen:
            raise SpecError(f"two shots share the id {shot.id!r}")
        seen.add(shot.id)
        if shot.seconds != SHOT_SECONDS:
            raise SpecError(
                f"{shot.id} is {shot.seconds}s: Veo reference-image-to-video only does "
                f"{SHOT_SECONDS}s, so this shot could never be re-rendered"
            )
        missing = [a for a in attributes if a not in shot.continuity]
        if missing:
            raise SpecError(f"{shot.id} does not say what {', '.join(missing)} is")
        shots.append(shot)

    if not shots:
        raise SpecError("the spec has no shots")

    known = {s.id for s in shots}
    for shot_id, cells in patches.items():
        if shot_id not in known:
            raise SpecError(f"a fix names {shot_id!r}, which is not a shot in this film")
        for name, value in cells.items():
            if name not in attributes:
                raise SpecError(f"a fix for {shot_id} sets {name!r}, which is not tracked")
            if bible.attributes and str(value) not in bible.attribute(name).values:
                raise SpecError(
                    f"a fix for {shot_id} sets {name}={value!r}, which is not one of "
                    f"{', '.join(bible.attribute(name).values)}"
                )

    fixed_cells = {(s, a) for s, cells in patches.items() for a in cells}
    breaks = [
        Break(
            shot=b["shot"],
            attribute=b["attribute"],
            before=str(b["from"]),
            after=str(b["to"]),
        )
        for b in raw.get("expected_breaks") or []
        if (str(b["shot"]), str(b["attribute"])) not in fixed_cells
    ]

    film = Film(
        title=raw.get("title", "untitled"),
        fps=int(raw.get("fps", 24)),
        aspect=raw.get("aspect", "16:9"),
        resolution=str(raw.get("resolution", "1280x720")),
        continuity_attributes=attributes,
        shots=shots,
        expected_breaks=breaks,
        bible=bible,
        render=dict(raw.get("render") or {}),
        check=dict(raw.get("check") or {}),
    )

    for b in breaks:
        film.shot(b.shot)  # raises if the answer key names a shot that is gone
        if b.attribute not in attributes:
            raise SpecError(f"expected_breaks names {b.attribute!r}, which is not tracked")

    if bible.attributes:
        # The answer key is checkable, so check it. A hand-written key drifts
        # the moment a shot's continuity is edited, and a drifted key scores the
        # checker against a film that is not the one on disk.
        try:
            derived = bible_mod.derive_breaks(bible, film.states())
        except bible_mod.BibleError as exc:
            raise SpecError(f"bible: {exc}")
        order = lambda b: (b.shot, b.attribute)  # noqa: E731. The key is the whole function
        if breaks and sorted(derived, key=order) != sorted(breaks, key=order):
            raise SpecError(
                "expected_breaks does not match what the shots declare. The shots say ["
                + "; ".join(b.sentence() for b in derived)
                + "] and the answer key says ["
                + "; ".join(b.sentence() for b in breaks)
                + "]"
            )
        # Compose the prompt only once the spec is known to be sound, so a
        # broken bible never reaches a backend.
        film = replace(
            film,
            shots=[replace(s, generation_prompt=bible.prompt_for(s)) for s in shots],
        )

    return film
