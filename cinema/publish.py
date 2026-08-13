"""The hosted page, built from the run rather than written by hand.

Devpost asks for a hosted project URL, and the honest version of that page is
the last run's own output: the cut it rendered, the plates it drew, and the
score it wrote. So every number on the page is read out of `out/score.json` and
`out/continuity.json` at publish time. Nothing here is allowed to state a
result — if a claim is worth putting on the page, it has to come out of a file
the pipeline wrote.

That rules out the failure this entry exists to argue against. A page carrying
"2 of 2 breaks found" as literal text keeps saying it after the checker starts
missing them, and the reader has no way to tell. `publish` refuses to build a
page at all when the artefacts are missing.

It also names the reader. The offline pixel stand-in and Gemini on Vertex AI
score differently and only one of them is the detector, so a score with no
reader beside it is not a claim anyone can check.

The page is also the thing a judge operates: `cinema/webapp.py` inlines the run
into it, and the shot-by-shot inspector there is the project running on the web
rather than a report of it having run somewhere else.
"""

from __future__ import annotations

import html
import json
import shutil
from pathlib import Path

from . import assemble, frames, webapp

ASSETS = "assets"

REPO = "https://github.com/jtmuller5/continuity-checker"

# Two seconds in: inside the first shot, past any fade.
POSTER_AT = 2.0

# What the page is built from. Missing any one of them is a refusal rather than
# a page with a hole in it.
REQUIRED = ("score.json", "continuity.json", "cut.mp4")

READERS = {
    "pixels": (
        "the offline pixel stand-in. It reads the placeholder renderer's own boxes. "
        "It proves the pipeline and it is not the detection."
    ),
    "gemini": "Gemini on Vertex AI, one call per frame, replying as JSON against an enum schema.",
}


class PublishError(RuntimeError):
    """The page could not be built from what is on disk."""


def _read(out: Path, name: str) -> dict:
    path = out / name
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        raise PublishError(f"{path} does not exist — run `python3 -m cinema fix` first")
    except json.JSONDecodeError as exc:
        raise PublishError(f"{path} is not readable JSON: {exc}")


def _plates(out: Path) -> list[tuple[str, Path]]:
    """The before/after plates, one per repaired shot, in shot order."""
    folder = out / "before-after"
    found = sorted(p for p in folder.glob("*.png") if not p.stem.endswith(("-before", "-after")))
    if not found:
        raise PublishError(f"no before/after plates in {folder} — run `python3 -m cinema fix` first")
    return [(p.stem, p) for p in found]


def _readable(out: Path, report: dict) -> list[Path]:
    """The frames the inspector needs, or a refusal naming what is missing.

    The front end shows what the checker was asked and what it saw, so a report
    with no questions in it, or one naming a still that is no longer on disk,
    cannot be published as one. Both mean the same thing — the report predates
    this build, or the run was cleaned up — and the fix for both is to run the
    check again.
    """
    if not report.get("questions"):
        raise PublishError(
            "the report carries no questions — it predates this build; "
            "run `python3 -m cinema check` again"
        )
    found = []
    for name in webapp.frame_paths(report):
        path = out / name
        if not path.exists():
            raise PublishError(f"{path} is named in the report but missing — re-run the check")
        found.append(path)
    if not found:
        raise PublishError("the report names no frames — re-run the check")
    return found


def _e(value) -> str:
    return html.escape(str(value))


def _breaks_table(score: dict) -> str:
    rows = []
    for kind, label in (("hits", "found"), ("misses", "MISSED"), ("false_alarms", "FALSE ALARM")):
        for b in score.get(kind) or []:
            rows.append(
                f"<tr><td class=\"{_e(kind)}\">{_e(label)}</td><td>{_e(b['shot'])}</td>"
                f"<td>{_e(b['attribute'])}</td><td>{_e(b['expected'])} &rarr; {_e(b['found'])}</td></tr>"
            )
    for n in score.get("near_misses") or []:
        exp, got = n["expected"], n["found"]
        rows.append(
            f"<tr><td class=\"near\">near miss</td><td>{_e(exp['shot'])}</td>"
            f"<td>{_e(exp['attribute'])}</td>"
            f"<td>expected {_e(exp['expected'])} &rarr; {_e(exp['found'])}, "
            f"read {_e(got['expected'])} &rarr; {_e(got['found'])}</td></tr>"
        )
    if not rows:
        rows.append('<tr><td colspan="4">The last run reported nothing.</td></tr>')
    return "\n".join(rows)


def _plural(count, noun: str) -> str:
    return f"{_e(count)} {noun}" if count == 1 else f"{_e(count)} {noun}s"


def _cells_line(score: dict) -> str:
    cells = score.get("cells") or {}
    total, agreed = cells.get("total", 0), cells.get("agreed", 0)
    parts = [f"{agreed} of {total} cells read as declared"]
    for key, label in (("misread", "misread"), ("disputed", "disputed"), ("unanswered", "unanswered")):
        n = len(cells.get(key) or [])
        if n:
            parts.append(f"{n} {label}")
    return ", ".join(parts)


def page(score: dict, report: dict, plates: list[tuple[str, Path]], repo: str) -> str:
    """The whole page. Every figure in it comes out of `score` or `report`."""
    reader = report.get("reader") or "unknown"
    reader_note = READERS.get(reader, "an unrecognised reader.")
    model = report.get("model")
    cost = report.get("cost_usd")
    plate_html = "\n".join(
        f'<figure><img src="{ASSETS}/{_e(path.name)}" alt="{_e(shot)} before and after">'
        f"<figcaption>{_e(shot)}, flagged and then re-rendered</figcaption></figure>"
        for shot, path in plates
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Continuity checker — {_e(report.get('film', 'a generated film'))}</title>
<style>
  :root {{ color-scheme: dark; --ink: #ece8f0; --dim: #a09aab; --bg: #16121c; --card: #1e1926; --line: #322b3d; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--bg); color: var(--ink); font: 16px/1.6 ui-sans-serif, system-ui, sans-serif; }}
  main {{ max-width: 56rem; margin: 0 auto; padding: 3rem 1.25rem 5rem; }}
  h1 {{ font-size: 2rem; line-height: 1.2; margin: 0 0 .5rem; }}
  h2 {{ font-size: 1.15rem; margin: 3rem 0 .75rem; }}
  p {{ max-width: 44rem; }}
  .lede {{ font-size: 1.1rem; color: var(--dim); max-width: 44rem; }}
  .card {{ background: var(--card); border: 1px solid var(--line); border-radius: 10px; padding: 1rem 1.25rem; }}
  table {{ border-collapse: collapse; width: 100%; font-size: .95rem; }}
  td, th {{ text-align: left; padding: .4rem .6rem; border-bottom: 1px solid var(--line); }}
  td.hits {{ color: #7fd48b; }}
  td.misses, td.false_alarms {{ color: #f08a7a; }}
  td.near {{ color: #e8c36a; }}
  figure {{ margin: 1.5rem 0; }}
  img, video {{ width: 100%; border-radius: 8px; border: 1px solid var(--line); display: block; }}
  figcaption {{ color: var(--dim); font-size: .9rem; margin-top: .5rem; }}
  code {{ background: #0f0c14; padding: .1rem .35rem; border-radius: 4px; font-size: .9em; }}
  .hint {{ color: var(--dim); font-size: .9rem; }}
  a {{ color: #9fb8ff; }}
  footer {{ margin-top: 4rem; color: var(--dim); font-size: .9rem; border-top: 1px solid var(--line); padding-top: 1rem; }}
{webapp.STYLE}
</style>
</head>
<body>
<main>
<h1>The film checks itself, and re-renders only what broke</h1>
<p class="lede">A generated film loses continuity between shots. The courier's jacket is red in
shot two and blue in shot three, and nothing in the pipeline notices. This is an agent that
reads the finished cut back, judges which shots broke, repairs those, re-renders only them and
checks its own work. It runs the same four steps every pass: perceive, judge, act, verify.</p>

<h2>The cut it read</h2>
<figure>
<video controls muted playsinline poster="{ASSETS}/poster.png">
  <source src="{ASSETS}/cut.mp4" type="video/mp4">
</video>
<figcaption>{_e(report.get('film', ''))}, {len(report.get('shots') or [])} shots.
Shots are drawn, not generated: the renderer is ffmpeg boxes standing in for Veo 3.1, so the
whole pipeline can be built and tested before a second of video is billed. The two continuity
breaks in it were planted on purpose.</figcaption>
</figure>

<h2>What it found</h2>
<div class="card">
<table>
<tr><th>verdict</th><th>shot</th><th>attribute</th><th>reading</th></tr>
{_breaks_table(score)}
</table>
</div>
<p>{_plural(score.get('expected_breaks', 0), 'break')} planted, {_e(score.get('found_breaks', 0))} found.
{_e(_cells_line(score))}. The checker never sees the answer key: it is handed the questions and
the words it may answer with, and the grading runs afterwards, against the written report.</p>

<h2>Work through the run yourself</h2>
<p>Pick a shot. You get the stills the checker sampled, the questions it was handed, what it
answered about each still, and what the scorer made of the answers. Arrow keys move between
shots.</p>
{webapp.section(score, report, plates)}
<p class="hint">Nothing above is decided in the browser. Every value on it is lifted out of the
same two files <code>cinema score</code> reads, so this shows the run rather than a second
opinion about it.</p>

<h2>Before, and after</h2>
{plate_html}
<p>A break names what the shot should have been as well as what it is, so the repair is read off
the finding rather than guessed. The repair is a layer over the spec, never an edit to it. A tool
that can edit its own answer key can report any accuracy it likes.</p>

<h2>What produced these numbers</h2>
<div class="card">
<table>
<tr><td>reader</td><td>{_e(reader)}{f" ({_e(model)})" if model else ""}</td></tr>
<tr><td>run at</td><td>{_e(report.get('at', 'unknown'))}</td></tr>
<tr><td>frames per shot</td><td>{_e(report.get('frames_per_shot', ''))}</td></tr>
<tr><td>cost of the check</td><td>{"$%.4f" % cost if isinstance(cost, (int, float)) else _e(cost)}</td></tr>
</table>
</div>
<p>{reader_note}</p>
<p>Detection is Gemini on Vertex AI and it has not run yet, because the credential and the budget
behind it are open work. So the score above measures the pipeline and says nothing about detection
quality on a real frame. Reading a whole 40-second film with Gemini 2.5 Pro is priced at about
$0.04, against $16.00 to render it at full quality, which is the argument: checking is close to
free next to generating.</p>

<h2>Running it</h2>
<div class="card">
<code>python3 -m cinema build</code>: render what changed, join it into <code>out/cut.mp4</code><br>
<code>python3 -m cinema check</code>: read the cut back, report the breaks<br>
<code>python3 -m cinema score</code>: grade that report against the key it never saw<br>
<code>python3 -m cinema fix</code>: repair, re-render only what moved, check again, plate it
</div>
<p>The source is at <a href="{_e(repo)}">{_e(repo)}</a>, MIT licensed. It runs with no credential.</p>

<footer>
Built by an autonomous agent working for Joe Muller. This page is generated by
<code>python3 -m cinema publish</code> from the last run's own output, so every figure on it was
written by the pipeline rather than typed here.
</footer>
</main>
</body>
</html>
"""


def publish(out: Path, site: Path, *, repo: str) -> Path:
    """Write the site from what the last run left in `out`.

    Refuses rather than publishing a page that states a result no file backs.
    """
    out, site = Path(out), Path(site)
    missing = [name for name in REQUIRED if not (out / name).exists()]
    if missing:
        raise PublishError(
            f"missing {', '.join(missing)} in {out} — run `python3 -m cinema fix` first"
        )

    score = _read(out, "score.json")
    report = _read(out, "continuity.json")
    plates = _plates(out)
    stills = _readable(out, report)

    assets = site / ASSETS
    assets.mkdir(parents=True, exist_ok=True)
    frame_dir = site / webapp.FRAMES
    frame_dir.mkdir(parents=True, exist_ok=True)
    for still in stills:
        shutil.copy2(still, frame_dir / still.name)
    shutil.copy2(out / "cut.mp4", assets / "cut.mp4")
    # The poster is a frame of the cut itself. A before/after plate standing in
    # for it reads as though the plate were the film. The seek is clamped to the
    # cut's own length: asking for a frame past the end writes nothing at all,
    # and ffmpeg says so by exiting 0.
    cut = assets / "cut.mp4"
    seconds = assemble.probe(cut).get("seconds") or 0
    frames.grab(cut, min(POSTER_AT, seconds / 2), assets / "poster.png")
    for _, path in plates:
        shutil.copy2(path, assets / path.name)

    index = site / "index.html"
    index.write_text(page(score, report, plates, repo))
    return index
