"""Read and validate the film spec.

One spec file describes the whole cut. Everything downstream — rendering, the
continuity check, the re-render of a single shot — reads it, so a mistake here
is caught before any second of video is billed.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from pathlib import Path

import yaml

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

    def key(self) -> str:
        """Stable identity of this shot's render inputs.

        Two shots with the same key must produce the same file, which is what
        makes caching and a single-shot re-render possible.
        """
        payload = json.dumps(
            {
                "id": self.id,
                "seconds": self.seconds,
                "prompt": " ".join(self.prompt.split()),
                "continuity": self.continuity,
            },
            sort_keys=True,
        )
        return hashlib.sha256(payload.encode()).hexdigest()[:12]


@dataclass(frozen=True)
class Break:
    shot: str
    attribute: str
    before: str
    after: str


@dataclass(frozen=True)
class Film:
    title: str
    fps: int
    aspect: str
    resolution: str
    continuity_attributes: list
    shots: list
    expected_breaks: list = field(default_factory=list)

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


def load(path) -> Film:
    raw = yaml.safe_load(Path(path).read_text())
    if not isinstance(raw, dict):
        raise SpecError(f"{path} is not a mapping")

    attributes = list(raw.get("continuity_attributes") or [])
    if not attributes:
        raise SpecError("continuity_attributes is empty: the checker would have nothing to compare")

    shots = []
    seen = set()
    for entry in raw.get("shots") or []:
        shot = Shot(
            id=entry["id"],
            slug=entry.get("slug", entry["id"]),
            seconds=int(entry.get("seconds", SHOT_SECONDS)),
            prompt=" ".join(str(entry["prompt"]).split()),
            continuity=dict(entry.get("continuity") or {}),
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

    breaks = [
        Break(
            shot=b["shot"],
            attribute=b["attribute"],
            before=str(b["from"]),
            after=str(b["to"]),
        )
        for b in raw.get("expected_breaks") or []
    ]

    film = Film(
        title=raw.get("title", "untitled"),
        fps=int(raw.get("fps", 24)),
        aspect=raw.get("aspect", "16:9"),
        resolution=str(raw.get("resolution", "1280x720")),
        continuity_attributes=attributes,
        shots=shots,
        expected_breaks=breaks,
    )

    for b in breaks:
        film.shot(b.shot)  # raises if the answer key names a shot that is gone
        if b.attribute not in attributes:
            raise SpecError(f"expected_breaks names {b.attribute!r}, which is not tracked")

    return film
