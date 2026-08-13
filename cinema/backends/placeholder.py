"""Render a shot without spending anything.

This draws the shot's continuity state instead of generating it: the jacket is
a moving colour block, the parcel is a pale rectangle that is there or is not,
and the time of day is the background. Nothing here is a model — it is ffmpeg
drawing boxes — so it is free, it runs offline, and it produces a cut before
Vertex AI access exists (#1008).

It also gives the checker (#1013) a fixture whose answer is known, which is why
the breaks are drawn rather than described.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

BACKGROUND = {
    "dawn": "0x3b3450",
    "day": "0x6d8ea8",
    "dusk": "0x2c2338",
    "night": "0x11121c",
}

PARCEL = "0xd8cdb4"

JACKET = {
    "red": "0xc0392b",
    "blue": "0x2b5fc0",
    "green": "0x2f8f4e",
    "yellow": "0xd4b02a",
}

name = "placeholder"
bills = False


def _escape(text: str) -> str:
    """Quote text for a drawtext filter argument."""
    return text.replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'").replace(",", r"\,")


def _fit(text: str, width_px: int, fontsize: int) -> str:
    """Cut text to what fits. DejaVu Sans Mono advances 0.6 em per glyph."""
    room = max(4, int((width_px - 12) / (fontsize * 0.6)))
    return text if len(text) <= room else text[: room - 1].rstrip() + "…"


def render(shot, film, out_path, *, log=print) -> Path:
    """Draw one shot to `out_path` and return it."""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    w, h = film.width, film.height
    bg = BACKGROUND.get(str(shot.continuity.get("time_of_day")), "0x202020")
    jacket = JACKET.get(str(shot.continuity.get("jacket")), "0x808080")
    parcel_visible = str(shot.continuity.get("parcel")) == "present"

    figure_w, figure_h = w // 8, h // 3
    figure_y = h // 2 - figure_h // 2
    parcel_w, parcel_h = figure_w // 2, figure_h // 4

    # The figure crosses the frame over the shot's length, so the file is video
    # rather than a still and a frame grab at any timestamp differs.
    #
    # This is an overlay and not a drawbox because drawbox's `t` is thickness,
    # not the timestamp: an expression using it there silently evaluates to the
    # fill sentinel and parks the box off the left edge.
    travel = f"({w}-{figure_w})*t/{shot.seconds}"

    inputs = [
        "-f", "lavfi", "-i", f"color=c={bg}:s={w}x{h}:r={film.fps}:d={shot.seconds}",
        "-f", "lavfi", "-i", f"color=c={jacket}:s={figure_w}x{figure_h}:r={film.fps}:d={shot.seconds}",
    ]
    chain = [f"[0][1]overlay=x='{travel}':y={figure_y}:eval=frame[fig]"]
    last = "fig"

    if parcel_visible:
        inputs += [
            "-f", "lavfi",
            "-i", f"color=c={PARCEL}:s={parcel_w}x{parcel_h}:r={film.fps}:d={shot.seconds}",
        ]
        chain.append(
            f"[{last}][2]overlay=x='{travel}+{figure_w // 4}'"
            f":y={figure_y + figure_h // 3}:eval=frame[car]"
        )
        last = "car"

    label_size = max(8, h // 18)
    caption_size = max(7, h // 22)
    chain.append(
        f"[{last}]drawtext=fontfile={FONT}:text='{_escape(shot.id + '  ' + shot.slug)}'"
        f":x=6:y=6:fontsize={label_size}:fontcolor=white,"
        f"drawtext=fontfile={FONT}"
        f":text='{_escape(_fit(shot.prompt, w, caption_size))}'"
        f":x=6:y=h-{caption_size}-8:fontsize={caption_size}:fontcolor=0xbbbbbb[out]"
    )

    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
        *inputs,
        "-filter_complex", ";".join(chain),
        "-map", "[out]",
        "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
        str(out_path),
    ]
    log(f"  {shot.id}: placeholder {w}x{h} {shot.seconds}s  $0.00")
    subprocess.run(cmd, check=True)
    return out_path
