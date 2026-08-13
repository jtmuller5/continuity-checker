"""What the checker's findings imply, and the record of what was repaired.

A break says a shot is not what the bible asks for. A fix is the other half of
that sentence: the value the shot should have been rendered with. This module
holds them, and nothing else: deciding is `cinema/bible.py`, re-rendering is
`cinema/render.py`.

The file lives beside the render ledger in `out/`, not in `film.yaml`. Two
reasons, and both are the point of the entry rather than housekeeping:

- The planted breaks in the spec are the fixture the checker is scored against.
  A tool that edits its own answer key can report any accuracy it likes.
- A fix has to be undoable in one command, because the demo is the before and
  the after side by side. `clear()` is that command.

`spec.load(path, fixes=...)` layers them, so the renderer sees the repaired
film and the cache re-renders exactly the shots whose keys moved.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

FIXES_NAME = "fixes.json"
FIXES_VERSION = 1


def path(out_dir) -> Path:
    return Path(out_dir) / FIXES_NAME


def load(out_dir) -> dict:
    """The repairs recorded so far, as `{shot_id: {attribute: value}}`."""
    p = path(out_dir)
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"{p} is not readable as JSON: {exc}")
    shots = raw.get("shots") if isinstance(raw, dict) else None
    if not isinstance(shots, dict):
        raise ValueError(f"{p} has no 'shots' mapping, so it is not a fixes file")
    return {str(k): {str(a): str(v) for a, v in cells.items()} for k, cells in shots.items()}


def save(out_dir, fixes, *, note: str = "") -> Path:
    p = path(out_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {
                "version": FIXES_VERSION,
                "at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "note": note,
                "shots": {k: dict(v) for k, v in sorted(fixes.items())},
            },
            indent=2,
        )
        + "\n"
    )
    return p


def clear(out_dir) -> bool:
    """Undo every fix. True when there was something to undo."""
    p = path(out_dir)
    if not p.exists():
        return False
    p.unlink()
    return True


def corrections(breaks) -> dict:
    """The repair each break asks for, as `{shot_id: {attribute: value}}`.

    A break carries what the shot should have been (`before`) as well as what it
    is, so the repair is read off the finding rather than guessed at, which is
    why the checker has to name the expected value and not only the wrong one.
    """
    out = {}
    for b in breaks:
        out.setdefault(b.shot, {})[b.attribute] = b.before
    return out


def merge(existing, new) -> dict:
    """Later repairs win, earlier ones on other cells survive."""
    merged = {k: dict(v) for k, v in existing.items()}
    for shot_id, cells in new.items():
        merged.setdefault(shot_id, {}).update(cells)
    return merged
