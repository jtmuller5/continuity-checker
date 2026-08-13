"""What kind of question an attribute's vocabulary makes it.

The free placeholder renderer draws a shot's continuity state and the free pixel
reader reads it back, and the two only agree if they sort an attribute the same
way. Sorting it twice is how a second film breaks the fixture: rename `jacket`
to `coat` and one of the pair keeps working while the other quietly answers
nothing. So the sorting lives here, once, and both import it.

Three kinds, and nothing else:

  * **presence** — a two-word yes/no vocabulary. Drawn as a pale prop that is in
    frame or is not.
  * **light** — a vocabulary of times of day. Drawn as the background.
  * **colour** — a vocabulary of colour words. Drawn as the subject's block.

The dispatch is on the words an attribute offers, never on its name, which is
what lets a second film call its subject a coat and its prop a lamp. An
attribute whose vocabulary is none of the three is not drawable and not
readable by this pair — the reader says so as an unanswered question rather
than as agreement, and `film.yaml` should use Veo and Gemini for it instead.
"""

from __future__ import annotations

from .bible import fold

PRESENT_WORDS = {"present", "yes", "visible", "carrying", "carried", "there", "lit"}
ABSENT_WORDS = {"absent", "no", "missing", "gone", "none", "unlit"}

# The ladder itself is a rendering and a reading decision, so each side keeps
# its own numbers. What is shared is only which words mean "time of day".
LIGHT_WORDS = ("dawn", "day", "dusk", "night")

COLOUR_WORDS = (
    "red", "blue", "green", "yellow", "orange",
    "purple", "brown", "pink", "white", "grey", "black",
)


def presence_pair(values):
    """`(present_value, absent_value)` when this is a yes/no vocabulary.

    Exactly one word of each, or it is not a presence question — a three-value
    vocabulary with "yes" in it is something else, and guessing at it would
    draw a prop the author never asked for.
    """
    yes = [v for v in values if fold(v) in PRESENT_WORDS]
    no = [v for v in values if fold(v) in ABSENT_WORDS]
    if len(yes) == 1 and len(no) == 1:
        return yes[0], no[0]
    return None


def is_light(values) -> bool:
    return any(fold(v) in LIGHT_WORDS for v in values)


def is_colour(values) -> bool:
    return any(fold(v) in COLOUR_WORDS for v in values)


def kind(values) -> str:
    """`"presence"`, `"light"`, `"colour"` or `""` — in the order they are tried.

    Presence first: a lamp that is "lit" or "unlit" is a prop, not a colour,
    and the colour test would otherwise never see it. Light before colour for
    the same reason — "dawn" is not a colour word, but a light vocabulary that
    someone extends with one should still be the sky.
    """
    if presence_pair(values):
        return "presence"
    if is_light(values):
        return "light"
    if is_colour(values):
        return "colour"
    return ""
