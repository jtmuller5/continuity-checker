"""What a render costs, in dollars, before it is run.

Veo 3.1 bills per second of output, so a shot's price is known from the spec
alone — there is no need to render one to find out. The table is read straight
off Google's published rates; `notes/render-cost.md` has the citations and the
date.

The point of holding it here is the ledger: every entry records what that render
cost, so `cinema timings` can say what a cache hit saved rather than guess at it.
"""

from __future__ import annotations

# tier -> resolution class -> (video only, video + audio), $ per second of output.
PER_SECOND = {
    "standard": {
        "720p": (0.20, 0.40),
        "1080p": (0.20, 0.40),
        "4k": (0.40, 0.60),
    },
    "fast": {
        "720p": (0.08, 0.10),
        "1080p": (0.10, 0.12),
        "4k": (0.25, 0.30),
    },
    "lite": {
        "720p": (0.03, 0.05),
        "1080p": (0.05, 0.08),
        # Lite does not do 4K at all, so there is no price to fall back to.
    },
}

TIERS = tuple(PER_SECOND)


class PricingError(ValueError):
    """A tier and resolution Veo will not sell."""


def resolution_class(resolution: str) -> str:
    """Which rung of Veo's price ladder a `WxH` string lands on.

    Below 720p there is no cheaper rung — the placeholder renders at 320x180 and
    would be billed as 720p if it were billed at all — so the floor is 720p.
    """
    height = int(str(resolution).lower().split("x")[1])
    if height >= 2160:
        return "4k"
    if height >= 1080:
        return "1080p"
    return "720p"


def per_second(tier: str, resolution: str, audio: bool) -> float:
    try:
        rungs = PER_SECOND[tier]
    except KeyError:
        raise PricingError(f"unknown tier {tier!r}; have: {', '.join(TIERS)}")
    rung = resolution_class(resolution)
    if rung not in rungs:
        raise PricingError(f"Veo 3.1 {tier} does not generate {rung}")
    return rungs[rung][1 if audio else 0]


def shot_cost(seconds: int, tier: str, resolution: str, audio: bool) -> float:
    """What one shot costs on a billing backend. Rounded to the cent it appears on."""
    return round(seconds * per_second(tier, resolution, audio), 4)
