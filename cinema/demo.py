"""The demo video, cut from the run rather than recorded off a screen.

Devpost judges the first three minutes of the video and nothing after it, so the
running time is a hard limit here rather than a target: `storyboard` refuses a
cut it cannot fit, and it refuses before a single frame is encoded.

The rule the page follows applies twice over to a video, because a video is the
one artefact nobody re-runs. Every figure on a card is read out of
`out/score.json` and `out/continuity.json`, and the two console panels are the
real stdout of `cinema check` and `cinema score`, captured while the video is
built. Nothing is retyped, so a worse run makes a worse video instead of the
same confident one.

There is no narration. Every word is English text on the screen, and `demo.srt`
carries the same words for a player that wants a caption track.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from pathlib import Path

from . import assemble, pageshot, pricing
from . import publish as publish_mod

WIDTH, HEIGHT, FPS = 1280, 720, 24

# Devpost: "should not be longer than 3 minutes. If it is longer than 3 minutes,
# only the first 3 minutes will be evaluated." A cut that overruns does not get
# a warning, it gets truncated mid-sentence, so this is enforced rather than
# checked by eye.
LIMIT_SECONDS = 180

FONT = "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"
FONT_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"
FONT_MONO = "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf"

INK = "0xece8f0"
DIM = "0xa09aab"
BG = "0x16121c"
CONSOLE_BG = "0x0f0c14"

# The opaque strip a picture panel's caption is drawn in, across the foot of the
# frame. Opaque because the placeholder burns the shot's own prompt there, and a
# constant because anything fitted to the frame has to be fitted above it.
CAPTION_BAND = 96

# What the video is built from. The same refusal as `publish`: a missing
# artefact stops the build instead of leaving a hole in the cut.
REQUIRED = ("score.json", "continuity.json", "cut.mp4")

REPO = "https://github.com/jtmuller5/continuity-checker"
PAGE = "https://joemuller.com/continuity-checker/"

# The comparison the entry rests on: what a five-shot pass costs to generate at
# the quality a judge would watch, priced from Google's published rates rather
# than asserted here.
DEMO_TIER, DEMO_RESOLUTION = "standard", "1920x1080"


class DemoError(RuntimeError):
    """The video could not be built from what is on disk."""


@dataclass(frozen=True)
class Panel:
    """One segment of the cut. `kind` decides how it is drawn."""

    kind: str  # card | console | clip | still
    seconds: float
    heading: str
    lines: tuple[str, ...] = ()
    source: Path | None = None
    caption: str = ""

    @property
    def subtitle(self) -> str:
        """What this panel contributes to `demo.srt`."""
        body = " ".join(line.strip() for line in self.lines if line.strip())
        parts = [p for p in (self.heading, body or self.caption) if p]
        return " — ".join(parts)


def _read(out: Path, name: str) -> dict:
    path = out / name
    try:
        return json.loads(path.read_text())
    except FileNotFoundError:
        raise DemoError(f"{path} does not exist — run `python3 -m cinema fix` first")
    except json.JSONDecodeError as exc:
        raise DemoError(f"{path} is not readable JSON: {exc}")


def _plates(out: Path) -> list[tuple[str, Path]]:
    folder = out / "before-after"
    found = sorted(p for p in folder.glob("*.png") if not p.stem.endswith(("-before", "-after")))
    if not found:
        raise DemoError(f"no before/after plates in {folder} — run `python3 -m cinema fix` first")
    return [(p.stem, p) for p in found]


def _wrap(text: str, cols: int = 62) -> tuple[str, ...]:
    return tuple(textwrap.wrap(text, cols)) or ("",)


# DejaVu Sans Mono advances 0.6 em, so a 22px console line fits this many
# characters between the left margin and the right edge. A line past it is not
# scrolled or shrunk by ffmpeg — it is drawn off the frame and lost in silence,
# which is how the reader's own description came out as "It proves th".
CONSOLE_COLS = int((WIDTH - 90 - 40) / (22 * 0.6))

# The same arithmetic downwards: 22px lines on 6px of leading, from y=160 to the
# foot of the frame. A longer capture is a refusal, because ffmpeg draws the
# overflow off the bottom edge and says nothing.
CONSOLE_ROWS = int((HEIGHT - 160 - 16) / (22 + 6))

# A picture panel's caption is one line in the band across its foot, and it is
# not folded: it is drawn at 26px from x=60 and anything past the right edge is
# lost in the same silence a long console line was. DejaVu Sans averages about
# 0.58 em over ordinary prose, so this is what the band can hold. Captions carry
# the scorer's own sentences, so their length is data and has to be checked.
CAPTION_COLS = int((WIDTH - 60 - 40) / (26 * 0.58))


def _console(text: str) -> tuple[str, ...]:
    """Captured stdout, folded to the width the panel can actually draw."""
    lines: list[str] = []
    for line in text.splitlines():
        indent = " " * (len(line) - len(line.lstrip()))
        if len(line) <= CONSOLE_COLS:
            lines.append(line)
            continue
        lines.extend(
            textwrap.wrap(
                line, CONSOLE_COLS,
                initial_indent="", subsequent_indent=indent + "  ",
                # A long word is broken rather than kept whole: an unbroken path
                # wider than the frame would be drawn off the edge, which is the
                # failure this whole function exists to stop.
                break_long_words=True, drop_whitespace=False,
            )
        )
    return tuple(lines)


def _sentences(score: dict) -> tuple[str, ...]:
    """One line per verdict, in the words the scorer wrote."""
    lines = []
    for kind, label in (
        ("hits", "found"),
        ("misses", "MISSED"),
        ("false_alarms", "FALSE ALARM"),
    ):
        for item in score.get(kind) or []:
            lines.append(f"{label:<12} {item.get('sentence', '')}")
    for near in score.get("near_misses") or []:
        expected = near.get("expected") or {}
        lines.append(f"{'near miss':<12} {expected.get('shot', '')} {expected.get('attribute', '')}")
    return tuple(lines) or ("the last run reported nothing",)


def _cells(score: dict) -> str:
    cells = score.get("cells") or {}
    return f"{cells.get('agreed', 0)} of {cells.get('total', 0)} cells read as declared"


def capture(command: list[str], *, cwd: Path | None = None) -> str:
    """Run one of our own commands and keep what it printed.

    The console panels are this and not a transcript pasted in by hand, which is
    the difference between showing the tool run and describing it.
    """
    done = subprocess.run(
        [sys.executable, "-m", "cinema", *command],
        cwd=str(cwd) if cwd else None,
        capture_output=True,
        text=True,
    )
    if done.returncode != 0:
        raise DemoError(
            f"`cinema {' '.join(command)}` exited {done.returncode}, so there is nothing "
            f"honest to show:\n{done.stdout}{done.stderr}"
        )
    return done.stdout.rstrip("\n")


def storyboard(
    score: dict,
    report: dict,
    plates: list[tuple[str, Path]],
    cut: Path,
    consoles: dict[str, str],
    *,
    cut_seconds: float,
    page: Path | None = None,
) -> list[Panel]:
    """Every panel, in order. Pure: the same inputs give the same cut."""
    reader = report.get("reader") or "unknown"
    planted = score.get("expected_breaks", 0)
    found = score.get("found_breaks", 0)
    shots = len(report.get("shots") or [])
    frames = shots * int(report.get("frames_per_shot", 0) or 0)

    render_pass = round(
        shots * pricing.shot_cost(8, DEMO_TIER, DEMO_RESOLUTION, True), 2
    )
    check_pass = pricing.check_cost(frames or 1)

    # The first thirty seconds decide what a judge thinks of the rest, and the
    # film alone does not fill them with anything that works: it is the problem,
    # not the result. So the first repaired shot is shown before a word of
    # explanation, and shown again later once the checker has been watched
    # finding it. The caption is the scorer's own sentence rather than a claim
    # written here.
    lead: list[Panel] = []
    if plates:
        shot, path = plates[0]
        sentence = next(
            (
                hit.get("sentence", "")
                for hit in (score.get("hits") or [])
                if hit.get("shot") == shot
            ),
            f"{shot} was flagged and re-rendered",
        )
        lead = [
            Panel(
                "still", 8,
                "",
                source=path,
                caption=f"Found by the checker, not by a person — {sentence}",
            )
        ]

    panels = [
        Panel(
            "card", 9,
            "Everyone generates the film. Nobody checks it.",
            _wrap(
                "A generated film loses continuity between shots — the courier's "
                "jacket changes colour, the parcel he is carrying disappears. This "
                "reads the finished cut back, says which shots broke, and re-renders "
                "only those."
            ) + ("", "Built by an autonomous agent working for Joe Muller."),
        ),
        *lead,
        Panel(
            "clip", cut_seconds,
            "",
            source=cut,
            caption=(
                f"{report.get('film', 'the cut')} — {shots} shots, {int(cut_seconds)}s. "
                f"{planted} continuity breaks are in here."
            ),
        ),
        Panel(
            "card", 10,
            "What the checker is handed",
            _wrap(
                "The shot bible writes the generation prompt and the checker's "
                "questions from one source, so what was asked for and what is checked "
                "cannot drift apart. The checker gets the questions and the words it "
                "may answer with. It never gets the answer key, the canon, or the "
                "state any shot was written to hold."
            ),
        ),
        Panel(
            "console", 22,
            "$ python3 -m cinema check",
            _console(consoles["check"]),
        ),
        Panel(
            "console", 12,
            "$ python3 -m cinema score",
            _console(consoles["score"]),
        ),
        Panel(
            "card", 9,
            f"{planted} planted, {found} found",
            _sentences(score) + ("", _cells(score), f"reader: {reader}"),
        ),
    ]

    for shot, path in plates:
        panels.append(
            Panel(
                "still", 9,
                "",
                source=path,
                caption=f"{shot}: flagged, then re-rendered. Left is the break, right is the repair.",
            )
        )

    # Devpost asks for a project that runs on the web, and this is it: the same
    # run, opened and worked through in a browser. It follows the plates because
    # by now the judge knows what a plate is, and the page is where every one of
    # them can be inspected rather than watched.
    if page is not None:
        panels.append(
            Panel(
                "still", 9,
                "",
                source=page,
                caption=(
                    "Pick any shot and read what it answered: "
                    f"{PAGE.removeprefix('https://').rstrip('/')}"
                ),
            )
        )

    panels += [
        Panel(
            "card", 11,
            "Only the broken shots are re-rendered",
            _wrap(
                "A break names what the shot should have been as well as what it is, "
                "so the repair is read off the finding instead of guessed. The repair "
                "is a layer over the spec and never an edit to it: a tool that can "
                "edit its own answer key can report any accuracy it likes."
            ),
        ),
        Panel(
            "card", 11,
            "Checking costs a rounding error of generating",
            _wrap(
                f"Rendering these {shots} shots on Veo 3.1 at 1080p with audio is "
                f"${render_pass:.2f}. Reading all {frames} frames back with Gemini 2.5 Pro "
                f"is ${check_pass:.2f} — under one percent of it. That is the whole "
                "argument: the check is cheap enough to run on every pass, and the "
                "re-render is scoped to the shots that failed."
            ),
        ),
        Panel(
            "card", 10,
            "What this score is, and what it is not",
            _wrap(
                f"The run above used the {reader} reader, a free offline stand-in that "
                "reads the placeholder renderer's own boxes. It proves the pipeline "
                "and it is not the detection. Detection is Gemini on Vertex AI, one "
                "call per frame against an enum schema, and it is written and unrun: "
                "the credential is still open work."
            ),
        ),
        Panel(
            "card", 9,
            "Run it yourself: python3 -m cinema …",
            (
                # No column alignment here: the card font is proportional, so a
                # padded second column lands wherever the first one ended.
                "build — render the film",
                "check — read it back",
                "score — grade against the key it never saw",
                "fix — repair, then re-render only what moved",
                "",
                PAGE,
                REPO,
            ),
        ),
    ]

    for panel in panels:
        if panel.kind == "console" and len(panel.lines) > CONSOLE_ROWS:
            raise DemoError(
                f"`{panel.heading}` printed {len(panel.lines)} lines and the panel draws "
                f"{CONSOLE_ROWS}; the rest would be drawn off the bottom of the frame"
            )
        if len(panel.caption) > CAPTION_COLS:
            raise DemoError(
                f"the caption \"{panel.caption}\" is {len(panel.caption)} characters and the "
                f"band holds {CAPTION_COLS}; the tail would be drawn off the right edge"
            )

    total = sum(p.seconds for p in panels)
    if total > LIMIT_SECONDS:
        raise DemoError(
            f"the cut runs {total:.0f}s and only the first {LIMIT_SECONDS}s are judged; "
            "shorten a panel rather than let Devpost cut it mid-sentence"
        )
    return panels


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace(":", r"\:").replace("'", r"\'").replace(",", r"\,")


def _drawtext(path: Path, *, font: str, size: int, colour: str, x: str, y: str, spacing: int = 0) -> str:
    """Draw a text file. A file, not a literal, so nothing needs escaping."""
    return (
        f"drawtext=fontfile={font}:textfile={_escape(str(path))}"
        f":x={x}:y={y}:fontsize={size}:fontcolor={colour}:line_spacing={spacing}"
    )


def _encode(inputs: list[str], chain: list[str], dest: Path, seconds: float) -> Path:
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            *inputs,
            "-filter_complex", ";".join(chain),
            "-map", "[out]",
            "-t", f"{seconds}",
            "-r", str(FPS),
            "-c:v", "libx264", "-preset", "veryfast", "-pix_fmt", "yuv420p",
            "-video_track_timescale", str(FPS * 1000),
            str(dest),
        ],
        check=True,
    )
    return dest


def _caption_chain(source: str, text_file: Path) -> list[str]:
    """A band across the foot of a picture panel, so the frame is never bare."""
    # Opaque, not tinted. The placeholder burns the shot's own prompt across the
    # foot of every frame, and a translucent band leaves two lines of text on top
    # of each other.
    band = CAPTION_BAND
    return [
        f"[{source}]drawbox=x=0:y={HEIGHT - band}:w={WIDTH}:h={band}:color=black:t=fill,"
        + _drawtext(text_file, font=FONT, size=26, colour=INK, x="60", y=str(HEIGHT - band + 32))
        + "[out]"
    ]


def _panel(panel: Panel, index: int, work: Path) -> Path:
    dest = work / f"{index:02d}.mp4"
    head = work / f"{index:02d}-head.txt"
    body = work / f"{index:02d}-body.txt"

    if panel.kind in ("card", "console"):
        mono = panel.kind == "console"
        head.write_text(panel.heading + "\n")
        body.write_text("\n".join(panel.lines) + "\n")
        background = CONSOLE_BG if mono else BG
        inputs = [
            "-f", "lavfi",
            "-i", f"color=c={background}:s={WIDTH}x{HEIGHT}:r={FPS}:d={panel.seconds}",
        ]
        chain = [
            "[0]"
            + _drawtext(
                head,
                font=FONT_MONO if mono else FONT_BOLD,
                size=30 if mono else 40,
                colour="0x7fd48b" if mono else INK,
                x="90", y="86",
            )
            + ","
            + _drawtext(
                body,
                font=FONT_MONO if mono else FONT,
                size=22 if mono else 30,
                colour=DIM if mono else INK,
                # The console panel carries a whole command's output, so it
                # starts higher and sits tighter: a line past the foot of the
                # frame is drawn off it rather than scrolled.
                x="90", y="160" if mono else "176",
                spacing=6 if mono else 16,
            )
            + "[out]"
        ]
        return _encode(inputs, chain, dest, panel.seconds)

    if panel.source is None:
        raise DemoError(f"panel {index} is a {panel.kind} with nothing to show")
    body.write_text(panel.caption + "\n")

    if panel.kind == "still":
        inputs = ["-loop", "1", "-framerate", str(FPS), "-t", f"{panel.seconds}", "-i", str(panel.source)]
    else:
        inputs = ["-i", str(panel.source)]

    # Nearest neighbour on the way up: the placeholder draws hard-edged boxes at
    # 320x180 and a smooth scaler turns the jacket into a gradient, which is the
    # one thing the viewer is being asked to look at.
    chain = [
        f"[0:v]scale={WIDTH}:{HEIGHT}:flags=neighbor:force_original_aspect_ratio=decrease,"
        f"pad={WIDTH}:{HEIGHT}:(ow-iw)/2:(oh-ih)/2:color={BG},setsar=1[pic]"
    ] + _caption_chain("pic", body)
    return _encode(inputs, chain, dest, panel.seconds)


def _timestamp(seconds: float) -> str:
    whole = int(seconds)
    ms = int(round((seconds - whole) * 1000))
    return f"{whole // 3600:02d}:{whole // 60 % 60:02d}:{whole % 60:02d},{ms:03d}"


def subtitles(panels: list[Panel]) -> str:
    """An SRT of the same words that are on the screen."""
    lines, at = [], 0.0
    for number, panel in enumerate(panels, start=1):
        end = at + panel.seconds
        text = panel.subtitle or "(no text)"
        lines.append(f"{number}\n{_timestamp(at)} --> {_timestamp(end)}\n{text}\n")
        at = end
    return "\n".join(lines)


def page_still(
    out: Path,
    work: Path,
    plates: list[tuple[str, Path]],
    *,
    site: Path | None,
    log=print,
) -> Path:
    """Photograph the hosted page, showing the first shot the checker repaired.

    The site is published here rather than read out of `docs/`, and that is the
    answer to the obvious question of what happens when the picture is older
    than the page: it cannot be. `build` re-runs `check`, which moves the
    report's timestamp, so a `docs/` written before this cut always states an
    older run — photographing it would put a stale page next to fresh console
    output and call both the same run. The picture is taken from a site built
    out of the same artefacts as every card, and the committed `docs/` is
    compared against it afterwards so a page that no longer matches is said out
    loud rather than shipped quietly.
    """
    built = publish_mod.publish(out, work / "site", repo=REPO)
    shot = plates[0][0] if plates else "s01"
    dest = work / "page.png"
    pageshot.shoot(
        built.parent, dest, shot=shot,
        width=WIDTH, height=HEIGHT, footer=CAPTION_BAND, log=log,
    )

    if site is not None:
        live = Path(site) / "index.html"
        if not live.exists():
            log(f"  page: {live} does not exist — run `python3 -m cinema publish` before committing")
        elif live.read_text() != built.read_text():
            log(
                f"  page: {live} is not this run — the video shows the page as it will be "
                "once `python3 -m cinema publish` has written it"
            )
    return dest


def build(
    out: Path,
    dest: Path,
    *,
    cwd: Path | None = None,
    site: Path | None = Path("docs"),
    log=print,
) -> Path:
    """Cut the demo from what the last run left behind, and prove the file.

    `check` and `score` are run here rather than read, so the console panels are
    this machine's own output. Both are free and offline on the default reader.
    """
    out, dest = Path(out), Path(dest)
    missing = [name for name in REQUIRED if not (out / name).exists()]
    if missing:
        raise DemoError(
            f"missing {', '.join(missing)} in {out} — run `python3 -m cinema fix` first"
        )

    consoles = {"check": capture(["check"], cwd=cwd), "score": capture(["score"], cwd=cwd)}
    score = _read(out, "score.json")
    report = _read(out, "continuity.json")
    cut = out / "cut.mp4"
    plates = _plates(out)

    work = out / "demo"
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    page = page_still(out, work, plates, site=site, log=log)

    panels = storyboard(
        score, report, plates, cut, consoles,
        cut_seconds=float(assemble.probe(cut).get("seconds") or 0),
        page=page,
    )

    made = []
    for index, panel in enumerate(panels, start=1):
        made.append(_panel(panel, index, work))
        log(f"  panel {index:>2}: {panel.seconds:>5.1f}s  {panel.heading or panel.caption}")

    dest.parent.mkdir(parents=True, exist_ok=True)
    assemble.concat(made, dest, log=lambda _msg: None)

    srt = dest.with_suffix(".srt")
    srt.write_text(subtitles(panels))

    # The panel lengths are an intention; this is the file. A cut that overran
    # would be truncated by the judge rather than by us, so it is asserted here
    # against the same limit `storyboard` refused on.
    actual = assemble.probe(dest)
    if (actual.get("seconds") or 0) > LIMIT_SECONDS:
        raise DemoError(
            f"{dest} came out at {actual.get('seconds')}s, over the {LIMIT_SECONDS}s "
            "Devpost judges — the encode disagrees with the storyboard"
        )
    log(f"  demo: {dest} ({actual.get('seconds')}s, {actual.get('width')}x{actual.get('height')})")
    log(f"  subtitles: {srt}")
    return dest
