"""Read a frame with Gemini on Vertex AI. This is the entry's detector.

The hackathon rules are explicit: "Projects must use Google Cloud AI tools
exclusively... No other AI models, agent frameworks, or AI APIs are permitted,
regardless of vendor." So the thing that looks at a frame and says what colour
the jacket is has to be Gemini, and it has to be on Vertex AI.

Three things this module does that a bigger prompt would not:

**It asks one question per tracked attribute, with a closed list of words.**
The answer comes back as JSON against an enum schema, so "dark crimson, though
the light makes it hard to say" is not a possible reply. The words come from
the bible, which also wrote the generation prompt, so what was asked for and
what is checked cannot drift apart.

**It is never told the answer.** The canon, the shot's declared continuity and
`expected_breaks` are all withheld, and the model gets the question and the
vocabulary. A model told the jacket should be red will find a red jacket.

**It may say it cannot tell.** Every enum carries `unclear`, which is outside
the bible's vocabulary and normalises to nothing rather than to agreement. A
checker with no way to abstain guesses, and a guess is indistinguishable from a
finding.

Cost is not a reason to skip it: a frame is 258 input tokens, so ten frames of
a five-shot film cost about a third of a cent against $16.00 to render it
(`notes/render-cost.md`).

**Unrun.** Vertex AI access is task #1008, so this code has never made a call.
The request it builds is asserted in `tests/test_check.py`, which is a test of
shape and of what is withheld, not of the API. The first real call is the thing
that proves the rest.
"""

from __future__ import annotations

import json
import os

from .. import pricing

name = "gemini"
bills = True

DEFAULT_MODEL = "gemini-2.5-pro"
# Region is pinned to the one Veo runs in, so a run cannot straddle two.
DEFAULT_LOCATION = "us-central1"

# The word the model uses when the frame does not answer the question. It is
# deliberately not one of the bible's values, so `Attribute.normalise` drops it.
UNCLEAR = "unclear"

INSTRUCTIONS = """\
You are checking one still frame from a film for continuity.

Answer each question below about this frame and nothing else. Do not guess from
what a scene like this usually contains, and do not reason about what the story
needs. Report only what is visible in this picture.

Answer each question with exactly one of the words offered. If the frame does
not show enough to answer, answer "{unclear}". Answering "{unclear}" is correct
and useful; a guess is not.

Reply as JSON matching the schema you were given.
"""


def question_lines(questions) -> list:
    return [
        f"- {q.attribute}: {q.text} One of: {', '.join(list(q.values) + [UNCLEAR])}."
        for q in questions
    ]


def prompt_text(questions) -> str:
    return INSTRUCTIONS.format(unclear=UNCLEAR) + "\n" + "\n".join(question_lines(questions))


def response_schema(questions) -> dict:
    """One enum property per attribute, all of them required.

    Required rather than optional so a frame the model skipped is visible as
    `unclear` instead of as a missing key that reads like agreement.
    """
    return {
        "type": "object",
        "properties": {
            q.attribute: {"type": "string", "enum": list(q.values) + [UNCLEAR]}
            for q in questions
        },
        "required": [q.attribute for q in questions],
    }


def cost(frames: int, model: str = DEFAULT_MODEL) -> float:
    return pricing.check_cost(frames, model)


def describe(model: str = DEFAULT_MODEL) -> str:
    return f"gemini: {model} on Vertex AI, one call per frame, JSON against an enum schema"


def _client(project=None, location=None):
    """A Vertex AI client, or a refusal that says which part is missing."""
    try:
        from google import genai
    except ImportError:
        raise SystemExit(
            "the gemini reader needs the Gen AI SDK: pip install google-genai "
            "(task #1008 covers the Vertex AI access it then needs)"
        )
    project = project or os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        raise SystemExit(
            "no Google Cloud project: set GOOGLE_CLOUD_PROJECT, or pass --project. "
            "Vertex AI access and the budget behind it are task #1008."
        )
    return genai.Client(
        vertexai=True,
        project=project,
        location=location or os.environ.get("GOOGLE_CLOUD_LOCATION") or DEFAULT_LOCATION,
    )


def read(frame, questions, *, model: str = DEFAULT_MODEL, client=None, log=print, **_options) -> dict:
    """One frame's answers, straight from the model's JSON.

    Nothing is coerced here. An answer outside the vocabulary is passed through
    exactly as it arrived and dropped by the bible, so a model that ignores its
    schema shows up as an unanswered question rather than as a quiet default.
    """
    from google.genai import types

    client = client or _client()
    response = client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=frame.path.read_bytes(), mime_type="image/png"),
            prompt_text(questions),
        ],
        config=types.GenerateContentConfig(
            response_mime_type="application/json",
            response_json_schema=response_schema(questions),
            # The frame is the only evidence. A model asked to be imaginative
            # about a continuity check will be.
            temperature=0.0,
        ),
    )
    try:
        answers = json.loads(response.text)
    except (TypeError, ValueError):
        log(f"  {frame.label}: the model returned no usable JSON")
        return {q.attribute: None for q in questions}
    return {q.attribute: answers.get(q.attribute) for q in questions}
