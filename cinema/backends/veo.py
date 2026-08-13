"""Render a shot on Veo 3.1, through Vertex AI.

This is the backend that costs money. It is written, and it is unrun: Vertex AI
access and the $100 credit are task #1008, and the loop's cap is $0.00. Nothing
here weakens that. The CLI still refuses a billing backend without
`--i-will-pay`, which is a human's flag, and this module refuses to guess at
anything that would change the bill.

What is fixed, from notes/render-cost.md:

  region        us-central1 only
  models        veo-3.1-lite-generate-001 while iterating ($0.24 per 8s shot,
                720p, video only), veo-3.1-generate-001 for the shots a judge
                watches ($3.20 per 8s shot, 1080p with audio)
  duration      8 seconds, always
  re-render     the previous shot's last frame goes in as the reference image
  billing       per second of output; a failed generation is not charged
  prompt        `shot.text`, never `shot.prompt`. The first is the author's
                line plus the continuity clauses the bible writes, and the
                second is the author's line alone. Generating from the second
                asks for a shot the checker was never told about.

The request is built by `request()`, which is a plain dict and imports nothing.
That split is the same one `readers/gemini.py` makes and for the same reason:
the Gen AI SDK is not installed on the machine the tests run on, so the shape of
what would be sent (the model the tier picks, the eight seconds, the composed
prompt, the seed, the reference frame) is asserted without an API. `render()`
is the thin half that turns that dict into SDK types, polls, and writes bytes.
"""

from __future__ import annotations

import base64
import os
import time
from pathlib import Path

from .. import pricing

name = "veo"
bills = True

# Every one of these changes the pixels, so every one belongs in the cache key.
# `reference` is the sharp one: the previous shot's last frame is this shot's
# reference image, so re-rendering shot 3 makes shots 4 and 5 stale. At $3.20
# a Standard shot, getting that wrong either ships a mismatched film or spends
# $6.40 pretending it might have.
KEY_INPUTS = ("tier", "seed", "reference")

MODELS = {
    "lite": "veo-3.1-lite-generate-001",
    "fast": "veo-3.1-fast-generate-001",
    "standard": "veo-3.1-generate-001",
}

# Veo runs in one region. Pinning it here rather than reading the environment
# keeps a run from straddling two, and the checker is pinned to the same one.
LOCATION = "us-central1"

SECONDS = 8

# Only two shapes are worth having: a film that is neither is a spec mistake,
# and Veo would letterbox it into one of these anyway at full price.
ASPECT_RATIOS = {(16, 9): "16:9", (9, 16): "9:16"}

POLL_SECONDS = 15
# Ten minutes. A shot that has not arrived by then is a stuck operation, and
# waiting longer costs cycle time without changing the outcome; the operation is
# named in the error so it can be picked up by hand.
TIMEOUT_SECONDS = 600


class VeoError(RuntimeError):
    """A render that did not happen, said in terms of what to do about it."""


def _ratio(width: int, height: int) -> str:
    from math import gcd

    divisor = gcd(width, height)
    shape = (width // divisor, height // divisor)
    try:
        return ASPECT_RATIOS[shape]
    except KeyError:
        raise VeoError(
            f"Veo generates {' and '.join(ASPECT_RATIOS.values())}, not {shape[0]}:{shape[1]} "
            f"({width}x{height}). Change `resolution` in film.yaml."
        )


def request(shot, film, config, reference: Path | None = None) -> dict:
    """Everything the call is made of, as data. Nothing here bills.

    Returned rather than sent so it can be printed, asserted and diffed. The
    caller has already paid for the previous shot; this is the last chance to
    see what the next $3.20 buys.
    """
    if config is None:
        raise VeoError(
            "the veo backend needs the render config: it decides the model, the seed and "
            "therefore the price. Call it through `cinema.render.render_film`."
        )
    if config.tier not in MODELS:
        raise VeoError(f"unknown tier {config.tier!r}; have: {', '.join(sorted(MODELS))}")
    if shot.seconds != SECONDS:
        # A shot of another length cannot be chained from a reference frame, so
        # it could never be re-rendered, which is the whole demo. `spec.py`
        # refuses one too; this is the second lock, on the side that spends.
        raise VeoError(f"{shot.id} is {shot.seconds}s: Veo generates {SECONDS}s shots only")

    body = {
        "model": MODELS[config.tier],
        "prompt": shot.text,
        "config": {
            "duration_seconds": SECONDS,
            "number_of_videos": 1,
            "aspect_ratio": _ratio(film.width, film.height),
            "resolution": pricing.resolution_class(config.resolution),
            "generate_audio": bool(config.audio),
            "seed": int(config.seed),
            # Veo's prompt rewriter is off on purpose. It expands a short prompt
            # into a more cinematic one, and the clauses it would rewrite are the
            # bible's continuity clauses: the jacket colour, the parcel, the
            # time of day. A rewritten prompt is a prompt the checker was not
            # told about, and every break it then finds is the rewriter's.
            "enhance_prompt": False,
        },
    }
    if reference is not None:
        # The previous shot's last frame, as this shot's first. This is what
        # makes the cut continuous, and it is why fixing shot 3 stales 4 and 5.
        body["image"] = {"path": str(reference), "mime_type": "image/png"}
    return body


def cost(config, seconds: int = SECONDS) -> float:
    return pricing.shot_cost(seconds, config.tier, config.resolution, config.audio)


def describe(config) -> str:
    return (
        f"veo: {MODELS[config.tier]} in {LOCATION}, {SECONDS}s, "
        f"{pricing.resolution_class(config.resolution)}"
        f"{' with audio' if config.audio else ', video only'}, ${cost(config):.2f} a shot"
    )


def _client(project=None, location=None):
    """A Vertex AI client, or a refusal that says which part is missing."""
    try:
        from google import genai
    except ImportError:
        raise SystemExit(
            "the veo backend needs the Gen AI SDK: pip install google-genai "
            "(task #1008 covers the Vertex AI access and the budget it then needs)"
        )
    project = project or os.environ.get("GOOGLE_CLOUD_PROJECT")
    if not project:
        raise SystemExit(
            "no Google Cloud project: set GOOGLE_CLOUD_PROJECT. Vertex AI access and "
            "permission to spend are task #1008."
        )
    return genai.Client(vertexai=True, project=project, location=location or LOCATION)


def last_frame(video, film, out_path) -> Path:
    """The final frame of `video`, which is the next shot's reference image.

    Sampled a frame short of the end rather than at it: ffmpeg seeking to the
    exact duration lands past the last frame and writes nothing, and a missing
    reference would be sent as a shot with no chain at full price.
    """
    from .. import frames

    at = max(0.0, SECONDS - 1.5 / max(1, film.fps))
    return frames.grab(video, at, out_path)


def _video_bytes(operation) -> bytes:
    """The generated video, however this SDK version hands it back."""
    result = getattr(operation, "result", None) or getattr(operation, "response", None)
    videos = getattr(result, "generated_videos", None) or []
    if not videos:
        raise VeoError("Veo reported success and returned no video")
    video = videos[0].video
    payload = getattr(video, "video_bytes", None)
    if payload is None:
        uri = getattr(video, "uri", None)
        raise VeoError(
            f"Veo returned a URI ({uri}) rather than bytes. This backend does not set "
            "`output_gcs_uri`, so the video is expected inline; fetch it by hand and re-run."
        )
    if isinstance(payload, str):
        # Some SDK versions hand back the base64 they were given.
        payload = base64.b64decode(payload)
    return payload


def render(shot, film, out_path, *, log=print, config=None, reference_video=None) -> Path:
    """Generate one shot and write it to `out_path`. This spends money.

    The wall clock is the render loop's to measure; what this logs is the only
    thing it alone can see, which is the poll. A Veo shot is minutes, not
    seconds, and a silent minute reads as a hang.
    """
    # Validated before anything touches the disk or the API: what is wrong with
    # a request is worth knowing before a shot's worth of money is committed.
    body = request(shot, film, config)

    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    reference = None
    if reference_video is not None and Path(reference_video).exists():
        reference = last_frame(reference_video, film, out_path.with_name(f".{shot.id}-ref.png"))
        body = request(shot, film, config, reference)
    log(f"  {shot.id}: {body['model']} {body['config']['resolution']} ${cost(config):.2f}")

    from google.genai import types

    client = _client()
    image = None
    if reference is not None:
        image = types.Image(image_bytes=Path(reference).read_bytes(), mime_type="image/png")

    operation = client.models.generate_videos(
        model=body["model"],
        prompt=body["prompt"],
        image=image,
        config=types.GenerateVideosConfig(**body["config"]),
    )

    waited = 0.0
    while not operation.done:
        if waited >= TIMEOUT_SECONDS:
            raise VeoError(
                f"{shot.id} did not finish in {TIMEOUT_SECONDS}s. The operation is "
                f"{getattr(operation, 'name', 'unnamed')}; it may still complete and still bill."
            )
        time.sleep(POLL_SECONDS)
        waited += POLL_SECONDS
        log(f"  {shot.id}: waiting on Veo, {waited:.0f}s")
        operation = client.operations.get(operation)

    if getattr(operation, "error", None):
        raise VeoError(f"{shot.id} failed: {operation.error}")

    out_path.write_bytes(_video_bytes(operation))
    if out_path.stat().st_size == 0:
        raise VeoError(f"{shot.id} came back empty")
    if reference is not None:
        Path(reference).unlink(missing_ok=True)
    return out_path
