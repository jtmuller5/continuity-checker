"""Where a shot's pixels come from.

A backend is a module with `name`, `bills`, and `render(shot, film, out_path)`.
`bills` is the one that matters: anything true there costs real money and must
not run without the credit and the permission behind task #1008.
"""

from . import placeholder, veo

BACKENDS = {m.name: m for m in (placeholder, veo)}
DEFAULT = placeholder.name


def get(name):
    try:
        return BACKENDS[name]
    except KeyError:
        raise SystemExit(f"unknown backend {name!r}; have: {', '.join(sorted(BACKENDS))}")
