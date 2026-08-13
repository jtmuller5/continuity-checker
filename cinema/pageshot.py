"""A picture of the hosted page, taken from the page rather than drawn.

Devpost asks for a project that runs on the web, and the page is that project:
`https://joemuller.com/continuity-checker/` carries the same run the video
reports, with a shot-by-shot inspector a judge can work through. A video that
only prints the URL is asking to be taken on trust, so the cut shows the page
being used.

The rule the rest of the build follows applies here too. Nothing is a
screen recording kept in the repository and nothing is retyped: the shot is
taken while the video is built, out of a site published from the same run, so a
worse run makes a worse picture. The one thing the browser is told to do is
press a control the judge would press (pick a shot in the strip) and report
where the inspector landed. It changes no text and hides nothing.

Headless Chrome is worth two warnings, because both failures exit 0:

- It captures the viewport and not the document. Scrolling first and shooting
  gives a blank frame, so the whole page is rendered into one tall window and
  the region is cropped out of the picture afterwards.
- Its screenshot cannot report geometry, so the same page is loaded twice: once
  with `--dump-dom`, where the injected script writes the measurement into the
  document title, and once for the picture. Both runs use the same window, or
  the lazily-loaded stills settle at different heights and the crop lands in the
  wrong place.
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

# The page is laid out at this width and rendered into a window tall enough to
# hold all of it, because only what is in the window reaches the picture.
CSS_WIDTH, WINDOW_HEIGHT = 1280, 6000

# Rendered at two device pixels to one CSS pixel, so the crop is scaled *down*
# into the frame. Upscaling a screenshot of a table is what makes a demo look
# like a photograph of a monitor.
SCALE = 2

# Scripts on the page draw the inspector, so the browser is given time to run
# them rather than shot the moment the document parses.
BUDGET_MS = 6000

TITLE = re.compile(r"<title>CINEMA (.*?)</title>", re.S)


class PageshotError(RuntimeError):
    """The page could not be photographed, so there is nothing honest to show."""


def browser() -> Path:
    """The headless Chrome this machine has, or a refusal naming what is missing."""
    found = sorted(Path.home().glob(".cache/ms-playwright/chromium-*/chrome-linux64/chrome"))
    if not found:
        raise PageshotError(
            "no headless Chrome under ~/.cache/ms-playwright. The demo shows the "
            "hosted page and cannot draw it from anything else"
        )
    return found[-1]


def _probe(shot: str) -> str:
    """The one script the page is asked to run: press a shot, then measure.

    `getBoundingClientRect` is relative to the viewport, and the viewport here
    is the whole document, so nothing is scrolled and the offsets are the
    document's own.
    """
    return """
<script>
(function () {
  function fail(why) { document.title = 'CINEMA ' + JSON.stringify({error: why}); }
  var run = document.getElementById('run');
  var strip = run && run.querySelector('.strip');
  if (!strip || !strip.children.length) return fail('the page has no shot inspector on it');
  var target = null;
  Array.prototype.forEach.call(strip.children, function (button) {
    if (!target && button.textContent.indexOf(%s) === 0) target = button;
  });
  if (!target) return fail('no shot in the strip is called ' + %s);
  target.click();
  function box(node) {
    var r = node.getBoundingClientRect();
    return {x: Math.round(r.left), y: Math.round(r.top),
            w: Math.round(r.width), h: Math.round(r.height)};
  }
  function measure() {
    var table = run.querySelector('.panel table');
    var card = box(run);
    document.title = 'CINEMA ' + JSON.stringify({
      card: card,
      // The answers table is the bottom of what has to be legible: below it the
      // panel repeats a plate the cut has already shown twice.
      bottom: table ? box(table).y + box(table).h : card.y + card.h,
      page: Math.ceil(document.documentElement.scrollHeight)
    });
  }
  // Measured three times over, and the last one is what the crop uses. The
  // page carries a video and a set of stills, and until their own bytes have
  // arrived the browser lays the document out at the wrong height. A
  // measurement taken while the document parses put the crop 600px above the
  // inspector, on a table that happened to be there instead.
  measure();
  window.addEventListener('load', measure);
  setTimeout(measure, 3000);
})();
</script>
""" % (json.dumps(shot), json.dumps(shot))


def _run(chrome: Path, page: Path, *, extra: list[str]) -> str:
    done = subprocess.run(
        [
            str(chrome),
            "--headless=new",
            # Chrome dies in a stack trace without this on chonky, and a sandbox
            # is not what stops a local file being read here.
            "--no-sandbox",
            "--disable-gpu",
            "--hide-scrollbars",
            f"--force-device-scale-factor={SCALE}",
            f"--window-size={CSS_WIDTH},{WINDOW_HEIGHT}",
            f"--virtual-time-budget={BUDGET_MS}",
            *extra,
            # Resolved, because a relative path has no file URI at all and the
            # failure is a ValueError from pathlib rather than anything about
            # the page.
            page.resolve().as_uri(),
        ],
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise PageshotError(f"chrome exited {done.returncode}: {done.stderr.strip()[-400:]}")
    return done.stdout


def render(chrome: Path, page: Path, raw: Path) -> dict:
    """One load: the picture, and where the inspector is in it.

    `--dump-dom` and `--screenshot` in the same run is not a convenience. Two
    runs of the same page do not agree on their own layout (the video and the
    stills settle at different heights depending on when their bytes arrive),
    and a measurement from one render cropped out of another lands wherever it
    likes. It landed 600px high, on the summary table, and chrome and ffmpeg
    both exited 0 on it.
    """
    dom = _run(chrome, page, extra=["--dump-dom", f"--screenshot={raw}"])
    if not raw.exists():
        raise PageshotError("chrome exited 0 and wrote no screenshot")
    found = TITLE.search(dom)
    if not found:
        raise PageshotError(
            "the page did not report its own geometry: its inspector script did not run"
        )
    try:
        measured = json.loads(found.group(1))
    except json.JSONDecodeError as exc:
        raise PageshotError(f"the page reported {found.group(1)!r}, which is not readable: {exc}")
    if "error" in measured:
        raise PageshotError(measured["error"])
    if measured["page"] > WINDOW_HEIGHT:
        raise PageshotError(
            f"the page is {measured['page']}px tall and the window is {WINDOW_HEIGHT}px; "
            "everything past the window is missing from the picture, not shrunk into it"
        )
    return measured


def crop_box(measured: dict, ratio: float = 16 / 9) -> dict:
    """The region to keep, in CSS pixels, always at the frame's own shape.

    Anchored on the foot of the answers table rather than the head of the card,
    so the reading is never cut off mid-row. When the inspector grows past what
    a 16:9 box of its own width can hold, the box widens instead of clipping.
    The picture gets smaller, which is recoverable, where a missing shot strip
    is not.
    """
    card = measured["card"]
    need = max(measured["bottom"] - card["y"], 1)
    height = max(round(card["w"] / ratio), need)
    width = round(height * ratio)
    x = min(max(card["x"] - (width - card["w"]) // 2, 0), max(CSS_WIDTH - width, 0))
    y = min(max(measured["bottom"] - height, 0), max(measured["page"] - height, 0))
    return {"x": x, "y": y, "w": min(width, CSS_WIDTH), "h": height}


def _variety(path: Path) -> int:
    """How many distinct grey levels the picture holds.

    A screenshot of the wrong scroll offset is a rectangle of one colour and
    ffmpeg and chrome both exit 0 on it, so the picture is read rather than
    assumed.
    """
    done = subprocess.run(
        ["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
         "-vf", "scale=160:90", "-pix_fmt", "gray", "-f", "rawvideo", "-"],
        capture_output=True,
    )
    if done.returncode != 0:
        raise PageshotError(f"the picture could not be read back: {done.stderr.decode()[-300:]}")
    return len(set(done.stdout))


def shoot(
    site: Path,
    dest: Path,
    *,
    shot: str,
    width: int,
    height: int,
    footer: int = 0,
    log=print,
) -> dict:
    """Photograph `site/index.html` with `shot` selected, and prove the picture.

    `footer` is the strip at the foot of the frame the caller draws over: the
    caption band, which is opaque. The page is fitted above it and the strip is
    left black, because a picture fitted to the whole frame has its last row of
    answers painted out by the band and nothing says so.
    """
    site, dest = Path(site), Path(dest)
    index = site / "index.html"
    if not index.exists():
        raise PageshotError(f"{index} does not exist. Nothing to photograph")

    chrome = browser()
    # A sibling of the real page, so every relative asset on it resolves the way
    # it does when the page is served.
    probed = site / "_pageshot.html"
    markup = index.read_text()
    if "</body>" not in markup:
        raise PageshotError(f"{index} has no </body> to attach the measurement to")
    probed.write_text(markup.replace("</body>", _probe(shot) + "</body>", 1))

    raw = dest.parent / "_pageshot-full.png"
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        measured = render(chrome, probed, raw)
        content = height - footer
        if content <= 0:
            raise PageshotError(f"a {footer}px band leaves no frame to draw the page in")
        box = crop_box(measured, width / content)
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(raw),
             "-vf",
             f"crop={box['w'] * SCALE}:{box['h'] * SCALE}:{box['x'] * SCALE}:{box['y'] * SCALE},"
             f"scale={width}:{content}:flags=lanczos,"
             f"pad={width}:{height}:0:0:color=black",
             str(dest)],
            check=True,
        )
        levels = _variety(dest)
        if levels < 8:
            raise PageshotError(
                f"the picture holds {levels} grey levels, so it is a blank rectangle: "
                "the crop landed off the rendered page"
            )
        log(f"  page: {dest} ({box['w']}x{box['h']} css at {box['x']},{box['y']}, {levels} levels)")
        return {**box, "levels": levels}
    finally:
        probed.unlink(missing_ok=True)
        raw.unlink(missing_ok=True)
