"""Answer the bible's questions by reading the pixels, with no model at all.

This is to the checker what `backends/placeholder.py` is to the renderer: a
free, offline stand-in that makes the whole pipeline runnable and testable
before the billed thing exists (#1008). It is **not** the entry's detector —
the hackathon rules require Google Cloud AI, and `readers/gemini.py` is what
ships. What this buys is that every other part of the checker — the sampling,
the vocabulary, the reconciliation of frames that disagree, the break rules and
the score — is exercised end to end today, at $0.00, against a cut whose answer
is known.

It is deliberately crude, and the crudeness is stated rather than hidden:

  * a **colour** question is answered by the average colour of the largest
    thing that is not the background, matched to the nearest of the words the
    question allows;
  * a **presence** question is answered by looking for a pale, unsaturated
    patch of a few hundred pixels — the parcel, in this film;
  * a **light** question is answered from the background's brightness on a
    fixed ladder.

It dispatches on the vocabulary a question offers, never on the attribute's
name, so it is not wired to this one film — but it understands only these three
kinds of question and says `None` to anything else, which the report shows as
unanswered rather than as agreement. A real frame from Veo, with a real
background and real lighting, is what a model is for.
"""

from __future__ import annotations

from .. import vocab
from ..bible import fold
from ..frames import raw_rgb

name = "pixels"
bills = False

# Small enough to read in a list comprehension, big enough that the parcel is
# still a few dozen pixels after the scale.
RASTER = (128, 72)

# Plain colour words with plain anchors. Only the ones a question actually
# offers are ever candidates, which is the same constraint the Gemini reader
# puts on the model with an enum.
COLOURS = {
    "red": (200, 40, 40),
    "blue": (40, 80, 200),
    "green": (45, 150, 80),
    "yellow": (220, 190, 50),
    "orange": (230, 130, 40),
    "purple": (130, 60, 170),
    "brown": (140, 90, 55),
    "pink": (235, 150, 175),
    "white": (240, 240, 240),
    "grey": (128, 128, 128),
    "black": (20, 20, 25),
}

# A ladder of screen brightness, not a measurement of the sky.
LIGHT = {"night": 20.0, "dusk": 40.0, "dawn": 60.0, "day": 130.0}

# How far from the background a pixel has to be to count as part of an object.
FOREGROUND_DISTANCE = 60.0
# A pale patch smaller than this is a compression artefact, not a prop.
PATCH_FRACTION = 0.002


def describe() -> str:
    return (
        "pixels: a free offline stand-in that reads the placeholder cut's own boxes. "
        "It proves the pipeline, not the detection — the entry detects with Gemini."
    )


def luma(pixel) -> float:
    r, g, b = pixel
    return 0.299 * r + 0.587 * g + 0.114 * b


def saturation(pixel) -> float:
    top, bottom = max(pixel), min(pixel)
    return 0.0 if top == 0 else (top - bottom) / top


def distance(a, b) -> float:
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5


def _pixels(data) -> list:
    return [tuple(data[i : i + 3]) for i in range(0, len(data), 3)]


def _mean(pixels) -> tuple:
    n = len(pixels)
    return tuple(sum(p[i] for p in pixels) / n for i in range(3))


def _background(pixels, width: int, height: int) -> tuple:
    """The frame's ground colour, from the top rows.

    The subject crosses the middle of the frame, so the band above it is the
    cheapest honest sample of what is behind everything.
    """
    rows = max(1, height // 10)
    return _mean(pixels[: rows * width])


def _foreground(pixels, background) -> list:
    return [p for p in pixels if distance(p, background) > FOREGROUND_DISTANCE]


def _subject_colour(foreground):
    """The average colour of the biggest thing in front of the background.

    Foreground pixels are grouped by a coarse quantisation and the largest
    group wins, so a small pale prop cannot drag the jacket's colour towards it.
    """
    if not foreground:
        return None
    groups = {}
    for pixel in foreground:
        groups.setdefault(tuple(v >> 5 for v in pixel), []).append(pixel)
    return _mean(max(groups.values(), key=len))


def _nearest(colour, allowed) -> str | None:
    candidates = {v: COLOURS[fold(v)] for v in allowed if fold(v) in COLOURS}
    if colour is None or not candidates:
        return None
    return min(candidates, key=lambda v: distance(colour, candidates[v]))


def _pale_patch(foreground, total: int) -> bool:
    pale = [p for p in foreground if luma(p) >= 140 and saturation(p) <= 0.35]
    return len(pale) >= max(4, int(total * PATCH_FRACTION))


def _presence_values(allowed):
    """`(present_value, absent_value)` if this is a yes/no question, else None.

    `cinema/vocab.py` decides, because the placeholder renderer decides whether
    to draw the prop from the same call.
    """
    return vocab.presence_pair(allowed)


def _light_value(background, allowed) -> str | None:
    candidates = {v: LIGHT[fold(v)] for v in allowed if fold(v) in LIGHT}
    if not candidates:
        return None
    brightness = luma(background)
    return min(candidates, key=lambda v: abs(brightness - candidates[v]))


def read(frame, questions, *, log=print, **_options) -> dict:
    """One frame's answers: `{attribute: word}`, with `None` for "cannot tell".

    Options meant for another reader — a model name, a project — are ignored
    rather than refused, so the checker can hand every reader the same call.
    """
    width, height = RASTER
    pixels = _pixels(raw_rgb(frame.path, width, height))
    background = _background(pixels, width, height)
    foreground = _foreground(pixels, background)
    subject = _subject_colour(foreground)

    answers = {}
    for question in questions:
        allowed = list(question.values)
        presence = _presence_values(allowed)
        if presence:
            present, absent = presence
            answers[question.attribute] = (
                present if _pale_patch(foreground, len(pixels)) else absent
            )
        elif vocab.is_light(allowed):
            answers[question.attribute] = _light_value(background, allowed)
        else:
            answers[question.attribute] = _nearest(subject, allowed)
    return answers
