"""Render a shot without spending anything.

This draws the shot's continuity state instead of generating it: the subject is
a moving colour block, a prop is a pale rectangle that is there or is not, and
the time of day is the background. Nothing here is a model. It is ffmpeg
drawing boxes, so it is free, it runs offline, and it produces a cut before
Vertex AI access exists (#1008).

It also gives the checker (#1013) a fixture whose answer is known, which is why
the breaks are drawn rather than described.

**Which attribute is drawn how is decided by its vocabulary, not by its name.**
`cinema/vocab.py` sorts an attribute into a colour, a presence or a light
question, and `readers/pixels.py` reads the frame back through the same call.
That is what lets the repository carry more than one fixture film: a second
film can call its subject a coat and its prop a lamp and still render and read
without a line changing here. A film with no bible at all (the older, flatter
spec form) falls back to the three names the first film used.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from .. import vocab
from ..bible import fold

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

# The names the first film used, for a spec that has no bible to sort by.
FLAT = {"colour": "jacket", "presence": "parcel", "light": "time_of_day"}

GREY = "0x808080"
UNLIT = "0x202020"

name = "placeholder"
bills = False

# Which render-config inputs change these pixels: none of them. There is no
# model to pick, no sampler to seed, and no reference frame. The drawing comes
# entirely from the shot's continuity state. Saying so keeps the cache honest:
# switching tier while iterating must not redraw five identical boxes.
KEY_INPUTS = ()


def _escape(text: str) -> str:
    """Quote text for a drawtext filter argument."""
    return text.replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'").replace(",", r"\,")


def _fit(text: str, width_px: int, fontsize: int) -> str:
    """Cut text to what fits. DejaVu Sans Mono advances 0.6 em per glyph."""
    room = max(4, int((width_px - 12) / (fontsize * 0.6)))
    return text if len(text) <= room else text[: room - 1].rstrip() + "…"


def drawing(shot, film) -> dict:
    """What this shot looks like: `{background, subject, prop}`.

    One pass over the bible, sorting each attribute by the words it offers.
    Only the first presence attribute is drawn. Two pale props in one frame
    would land on top of each other, and the pixel reader could not tell them
    apart anyway, so a film wanting two of them needs Veo and Gemini.
    """
    state = {name: str(value) for name, value in shot.continuity.items()}
    seen = {}
    for attribute in film.bible.attributes:
        if attribute.name in state:
            seen.setdefault(vocab.kind(attribute.values), attribute.name)
    for sort, name in FLAT.items():
        if name in state:
            seen.setdefault(sort, name)

    light = state.get(seen.get("light", ""), "")
    colour = state.get(seen.get("colour", ""), "")
    presence = seen.get("presence", "")
    pair = None
    if presence:
        attribute = next(
            (a for a in film.bible.attributes if a.name == presence), None
        )
        pair = vocab.presence_pair(attribute.values) if attribute else ("present", "absent")

    return {
        "background": BACKGROUND.get(fold(light), UNLIT),
        "subject": JACKET.get(fold(colour), GREY),
        "prop": bool(pair) and state.get(presence) == pair[0],
    }


def render(shot, film, out_path, *, log=print, **_options) -> Path:
    """Draw one shot to `out_path` and return it.

    The render config and the previous shot's file arrive as keywords and are
    dropped here: this backend declares `KEY_INPUTS = ()` and must read none of
    them, or the cache would break on a tier change that redraws the same box.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    w, h = film.width, film.height
    drawn = drawing(shot, film)
    bg, jacket, parcel_visible = drawn["background"], drawn["subject"], drawn["prop"]

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
    # No log line here. The render loop reports every shot with its wall clock
    # and its price; a backend that also announced itself printed each shot
    # twice. A backend logs progress it alone can see (Veo's polling) and
    # nothing else.
    subprocess.run(cmd, check=True)
    return out_path
