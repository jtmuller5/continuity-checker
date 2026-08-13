"""The render pipeline for the Agentic Cinema entry.

Stages are separate on purpose: a shot can be re-rendered without re-rendering
the film, which is the whole demo — catch a continuity break, fix one shot,
join the cut again.
"""

__all__ = ["spec", "assemble", "backends"]
