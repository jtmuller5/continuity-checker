"""The before/after plate: one picture, the broken frame beside the fixed one.

Joe's note on accepting this idea was "show the broken frame, then the fixed
one, side by side", so this is a deliverable and not a debug aid. It is built
from full frames rather than the cropped stills the checker reads: the crop
exists to keep the checker from grading the placeholder's own caption, and a
viewer should see the whole shot.

The broken frame has to be grabbed *before* the re-render, because a fixed shot
overwrites the file it replaces. `cinema fix` does that ordering.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"
PLATE_HEIGHT = 360
LABEL_HEIGHT = 34
GUTTER = 8


class PlateError(RuntimeError):
    """The plate could not be drawn."""


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def _side(index: int, label: str, out_label: str) -> str:
    """One half: scaled, given a label bar above it, and named for the stack."""
    chain = (
        f"[{index}:v]scale=-2:{PLATE_HEIGHT},"
        f"pad=iw:ih+{LABEL_HEIGHT}:0:{LABEL_HEIGHT}:color=black"
    )
    if Path(FONT).exists():
        chain += (
            f",drawtext=fontfile={FONT}:text='{_escape(label)}'"
            f":x=8:y=8:fontsize=18:fontcolor=white"
        )
    return chain + f"[{out_label}]"


def plate(before, after, out_path, *, left: str, right: str) -> Path:
    """Write `before | after` as one PNG, each half labelled."""
    before, after, out_path = Path(before), Path(after), Path(out_path)
    for src in (before, after):
        if not src.exists():
            raise PlateError(f"{src} does not exist, so there is no plate to draw")
    out_path.parent.mkdir(parents=True, exist_ok=True)

    graph = ";".join(
        [
            _side(0, left, "l"),
            _side(1, right, "r"),
            f"[l][r]hstack=inputs=2,pad=iw+{GUTTER * 2}:ih+{GUTTER * 2}:{GUTTER}:{GUTTER}"
            ":color=black[out]",
        ]
    )
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        "-i", str(before), "-i", str(after),
        "-filter_complex", graph, "-map", "[out]", "-frames:v", "1", str(out_path),
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0 or not out_path.exists():
        raise PlateError(f"ffmpeg could not draw {out_path}: {result.stderr.strip()}")
    return out_path
