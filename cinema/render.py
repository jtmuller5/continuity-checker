"""The render loop: cached, resumable, and one shot at a time.

Rendering is the only expensive thing this project does. A five-shot pass costs
$16.00 on Veo 3.1 Standard, so re-rendering four good shots to fix one bad one
throws away $12.80 — and the whole entry is about fixing one bad shot. The cache
is therefore not an optimisation, it is the mechanism the demo runs on.

Three properties, and every one of them is asserted in `tests/test_render.py`:

**Cached.** A shot is rendered when its inputs change and not otherwise. The key
covers the shot (prompt, continuity, length), the output format (resolution,
fps, audio), the backend, and whatever that backend declares it also reads —
`KEY_INPUTS`. Veo reads the tier, the seed and the reference image; the
placeholder backend reads none of them, so switching tiers does not redraw a box
that would come out identical.

**Resumable.** The ledger is written after every single shot, so a crash, a
timeout or a killed cycle costs one shot rather than the pass. Files are written
to a `.part` and renamed, so a half-written file is never mistaken for a cached
one. The ledger also stores each output's digest: delete or corrupt a shot on
disk and it renders again.

**Chained, when the backend chains.** Veo's re-render feeds the previous shot's
last frame in as the reference image, so shot 4's pixels genuinely depend on
shot 3's. A backend that declares `reference` in `KEY_INPUTS` gets the previous
shot's digest folded into its key, so fixing shot 3 correctly invalidates what
came after it — and a backend that does not, does not pay for a cascade it never
had.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from . import pricing

LEDGER_NAME = "renders.json"
LEDGER_VERSION = 1


@dataclass(frozen=True)
class RenderConfig:
    """Everything about a render that is not the shot itself."""

    backend: str
    tier: str = "lite"
    seed: int = 0
    resolution: str = "1280x720"
    fps: int = 24
    audio: bool = False

    @classmethod
    def build(cls, film, backend_name: str, **overrides):
        """Spec defaults, then whatever the command line said on top."""
        defaults = dict(film.render)
        chosen = {
            "backend": backend_name,
            "tier": defaults.get("tier", "lite"),
            "seed": int(defaults.get("seed", 0)),
            "resolution": film.resolution,
            "fps": film.fps,
            "audio": bool(defaults.get("audio", False)),
        }
        for key, value in overrides.items():
            if value is not None:
                chosen[key] = value
        chosen["seed"] = int(chosen["seed"])
        if chosen["tier"] not in pricing.TIERS:
            raise ValueError(f"unknown tier {chosen['tier']!r}; have: {', '.join(pricing.TIERS)}")
        return cls(**chosen)


@dataclass
class Result:
    shot_id: str
    path: Path
    key: str
    cached: bool
    wall_clock: float
    cost: float


def shot_path(out_dir, shot) -> Path:
    return Path(out_dir) / "shots" / f"{shot.id}-{shot.slug}.mp4"


def file_digest(path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()[:16]


def key_inputs(backend) -> tuple:
    """Which parts of the config this backend's pixels actually depend on.

    A backend that ignores the seed must not have its cache broken by one, or
    every tier change would re-render a film that came out byte-identical.
    """
    return tuple(getattr(backend, "KEY_INPUTS", ("tier", "seed", "reference")))


def cache_key(shot, config: RenderConfig, backend, reference: str | None) -> str:
    payload = {
        "shot": shot.key(),
        "backend": config.backend,
        "resolution": config.resolution,
        "fps": config.fps,
        "audio": config.audio,
    }
    reads = key_inputs(backend)
    if "tier" in reads:
        payload["tier"] = config.tier
    if "seed" in reads:
        payload["seed"] = config.seed
    if "reference" in reads:
        payload["reference"] = reference
    return hashlib.sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()[:16]


def load_ledger(out_dir) -> dict:
    path = Path(out_dir) / LEDGER_NAME
    if not path.exists():
        return {"version": LEDGER_VERSION, "shots": {}}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        # A truncated ledger is a cold cache, never a crash: the files on disk
        # are still checked against it, so the worst case is re-rendering.
        return {"version": LEDGER_VERSION, "shots": {}}
    if data.get("version") != LEDGER_VERSION:
        return {"version": LEDGER_VERSION, "shots": {}}
    data.setdefault("shots", {})
    return data


def save_ledger(out_dir, ledger) -> Path:
    path = Path(out_dir) / LEDGER_NAME
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.part")
    tmp.write_text(json.dumps(ledger, indent=2, sort_keys=True) + "\n")
    os.replace(tmp, path)
    return path


def _cost(shot, config: RenderConfig, backend) -> float:
    if not getattr(backend, "bills", False):
        return 0.0
    return pricing.shot_cost(shot.seconds, config.tier, config.resolution, config.audio)


def _render_one(backend, shot, film, path: Path, log, config=None, reference_video=None) -> float:
    """Render to a `.part` and rename. Returns the wall clock in seconds.

    The rename is what makes the cache safe to trust: a killed render leaves a
    part file behind, never a short file under the name the ledger will bless.

    The part file keeps the `.mp4` suffix. ffmpeg picks its muxer from the
    extension, so a name ending `.part` fails with "Unable to find a suitable
    output format" — which reads as a broken filter graph rather than a
    temporary name.

    The config and the previous shot's file go with the shot. A backend that
    draws boxes needs neither; Veo needs both, because the tier picks the model
    and therefore the price, and the reference image is what makes the cut
    continuous. They are keyword arguments so a backend can ignore them.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    partial = path.with_name(f".{path.stem}.part{path.suffix}")
    started = time.monotonic()
    try:
        backend.render(shot, film, partial, log=log, config=config, reference_video=reference_video)
        elapsed = time.monotonic() - started
        if not partial.exists():
            raise RuntimeError(f"{backend.name} reported success but wrote no file for {shot.id}")
        os.replace(partial, path)
    finally:
        if partial.exists():
            partial.unlink()
    return elapsed


def render_film(
    film,
    backend,
    config: RenderConfig,
    out_dir,
    *,
    only=None,
    force: bool = False,
    log=print,
) -> list:
    """Render what needs rendering and return one Result per shot.

    `only` names shots to render whatever the cache says — naming a shot is how
    a caught continuity break is fixed, and it is the demo. Shots outside it are
    still rendered if they are missing, because a film with a hole in it cannot
    be assembled and because a chaining backend needs its predecessor.
    """
    out_dir = Path(out_dir)
    ledger = load_ledger(out_dir)
    only = set(only or ())
    unknown = only - {s.id for s in film.shots}
    if unknown:
        raise ValueError(f"no such shot: {', '.join(sorted(unknown))}")

    chains = "reference" in key_inputs(backend)
    results = []
    # Two halves of the same fact. The digest is what the cache key moves on;
    # the file is what the backend is handed, because a reference image cannot
    # be reconstructed from a hash.
    reference = None
    reference_video = None

    for shot in film.shots:
        path = shot_path(out_dir, shot)
        key = cache_key(shot, config, backend, reference)
        entry = ledger["shots"].get(shot.id) or {}

        fresh = (
            entry.get("key") == key
            and path.exists()
            and entry.get("sha256") == file_digest(path)
        )
        wanted = force or shot.id in only

        if fresh and not wanted:
            log(f"  {shot.id}: cached  [{key}]  $0.00")
            results.append(
                Result(shot.id, path, key, True, float(entry.get("wall_clock", 0.0)), 0.0)
            )
            reference = entry.get("sha256") if chains else None
            reference_video = path if chains else None
            continue

        cost = _cost(shot, config, backend)
        elapsed = _render_one(
            backend, shot, film, path, log, config=config, reference_video=reference_video
        )
        digest = file_digest(path)
        ledger["shots"][shot.id] = {
            "key": key,
            "path": str(path.relative_to(out_dir)),
            "sha256": digest,
            "backend": config.backend,
            "tier": config.tier,
            "seed": config.seed,
            "resolution": config.resolution,
            "audio": config.audio,
            "seconds": shot.seconds,
            "wall_clock": round(elapsed, 3),
            "cost_usd": cost,
            "reference": reference,
            "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        }
        # After every shot, not at the end: a killed pass must cost one shot.
        save_ledger(out_dir, ledger)
        log(f"  {shot.id}: rendered {elapsed:.2f}s  [{key}]  ${cost:.2f}")
        results.append(Result(shot.id, path, key, False, elapsed, cost))
        reference = digest if chains else None
        reference_video = path if chains else None

    return results


def summarise(results: list, film, config: RenderConfig, backend) -> str:
    rendered = [r for r in results if not r.cached]
    cached = [r for r in results if r.cached]
    spent = sum(r.cost for r in rendered)
    saved = sum(_cost(film.shot(r.shot_id), config, backend) for r in cached)
    line = f"{len(rendered)} rendered, {len(cached)} cached  spent ${spent:.2f}"
    if saved:
        line += f", saved ${saved:.2f}"
    return line


@dataclass
class Timing:
    backend: str
    tier: str
    resolution: str
    samples: list = field(default_factory=list)

    @property
    def mean(self) -> float:
        return sum(self.samples) / len(self.samples)


def timings(out_dir) -> dict:
    """Measured wall clock per shot, grouped by what produced it.

    This is the number `notes/render-cost.md` records as unmeasured: the price
    of a shot is published, the time it takes is not. Every render writes one,
    so the first real Veo pass answers it without anyone remembering to time it.
    """
    grouped = {}
    for entry in load_ledger(out_dir)["shots"].values():
        which = (entry.get("backend"), entry.get("tier"), entry.get("resolution"))
        grouped.setdefault(which, Timing(*which)).samples.append(float(entry.get("wall_clock", 0.0)))
    return grouped
