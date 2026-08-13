"""Render a shot on Veo 3.1, through Vertex AI.

Not implemented yet, and deliberately so. It sits behind task #1008 — a billed
Google Cloud project, the $100 credit form, and Joe's permission to spend. The
loop's cap is $0.00, so this backend must never be reachable by accident: it
raises rather than falling back to the free one.

What it will do, from notes/render-cost.md:

  region        us-central1 only
  models        veo-3.1-lite-generate-001 while iterating ($0.24 per 8s shot,
                720p, video only), veo-3.1-generate-001 for the shots a judge
                watches ($3.20 per 8s shot, 1080p with audio)
  duration      8 seconds, always
  re-render     the previous shot's last frame goes in as the reference image
  billing       per second of output; a failed generation is not charged
  prompt        `shot.text`, never `shot.prompt` — the first is the author's
                line plus the continuity clauses the bible writes, and the
                second is the author's line alone. Generating from the second
                asks for a shot the checker was never told about.
"""

from __future__ import annotations

name = "veo"
bills = True

# Every one of these changes the pixels, so every one belongs in the cache key.
# `reference` is the sharp one: the previous shot's last frame is this shot's
# reference image, so re-rendering shot 3 makes shots 4 and 5 stale — at $3.20
# a Standard shot, getting that wrong either ships a mismatched film or spends
# $6.40 pretending it might have.
KEY_INPUTS = ("tier", "seed", "reference")

MODELS = {
    "lite": "veo-3.1-lite-generate-001",
    "fast": "veo-3.1-fast-generate-001",
    "standard": "veo-3.1-generate-001",
}


def render(shot, film, out_path, *, log=print):
    raise NotImplementedError(
        "The Veo backend needs Vertex AI access and permission to spend (task #1008). "
        "Render with --backend placeholder until that lands."
    )
