"""Where an answer about a frame comes from.

A reader is a module with `name`, `bills`, and
`read(frame, questions, *, log) -> {attribute: answer}`. It is handed the
question and the words an answer may use, and nothing else — not the canon, not
the shot's declared state, not the answer key. That withholding is the whole
reason a score means anything, and it is enforced by `cinema/check.py` building
the question list from `bible.questions()`.

The split mirrors the render backends exactly. `gemini` is the real one and the
only one the hackathon rules permit to do the detection: Google Cloud AI only,
no other vendor's model anywhere in the runtime. `pixels` is a stand-in that
reads the placeholder cut's own boxes, so the checker can be built, tested and
scored before Vertex AI access exists (#1008) — the same trade the placeholder
render backend makes.
"""

from . import gemini, pixels

READERS = {m.name: m for m in (pixels, gemini)}
DEFAULT = pixels.name


def get(name):
    try:
        return READERS[name]
    except KeyError:
        raise SystemExit(f"unknown reader {name!r}; have: {', '.join(sorted(READERS))}")
