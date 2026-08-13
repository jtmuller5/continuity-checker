"""Pull still frames out of the rendered shots, for the checker to read.

The checker does not watch the film. It reads a handful of frames per shot and
answers the bible's questions about each one, which is what makes the check
cheap enough to run on every pass: a frame is 258 input tokens, so ten frames
cost about a third of a cent (`notes/render-cost.md`).

Two decisions live here, and both are about not measuring the wrong thing.

**More than one frame per shot.** One frame is one moment, and a moment can be
unlucky — the courier turns and the parcel is behind them. Two frames spread
through the shot also catch a break that happens *inside* a shot, which a single
sample cannot see at all. When the frames of one shot disagree, the checker says
so rather than picking a winner.

**The label band is cropped off.** The placeholder backend burns the shot id and
the author's prompt into the picture, and that prompt says the words "brown
parcel". A checker reading its own caption is grading the text, not the frame.
The crop is a spec setting rather than a constant because real Veo footage has
no caption to remove.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

# Two is the cheapest number that can disagree with itself.
DEFAULT_PER_SHOT = 2


class FrameError(RuntimeError):
    """A frame could not be taken, so there is nothing to check."""


@dataclass(frozen=True)
class Frame:
    """One still, and where in the film it came from."""

    shot_id: str
    index: int
    at: float  # seconds into the shot
    path: Path

    @property
    def label(self) -> str:
        return f"{self.shot_id}#{self.index}"


def offsets(seconds: float, per_shot: int) -> list:
    """Where in a shot to sample, in seconds.

    Evenly spread across the shot and pulled in from both ends: the first and
    last frames of a generated shot are the ones most likely to be a dissolve,
    a black frame, or the reference image the next shot is chained from.
    """
    if per_shot < 1:
        raise FrameError("a shot cannot be checked with no frames")
    return [round(seconds * (i + 0.5) / per_shot, 3) for i in range(per_shot)]


def _crop_filter(crop) -> str | None:
    """`(top, height)` as fractions of the frame, as an ffmpeg crop filter."""
    if not crop:
        return None
    top, height = float(crop[0]), float(crop[1])
    if not 0 <= top < 1 or not 0 < height <= 1 or top + height > 1:
        raise FrameError(f"crop {crop!r} does not describe a band inside the frame")
    return f"crop=iw:ih*{height:g}:0:ih*{top:g}"


def grab(video, at: float, out_path, *, crop=None) -> Path:
    """One frame of `video` at `at` seconds, written as a PNG.

    `-ss` goes after `-i` on purpose. Before the input it seeks to a keyframe,
    which on an 8-second shot can land a second and a half from where it was
    asked for — and a frame from the wrong shot would be checked without
    anything looking wrong.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-i", str(video), "-ss", str(at)]
    crop_filter = _crop_filter(crop)
    if crop_filter:
        cmd += ["-vf", crop_filter]
    cmd += ["-frames:v", "1", str(out_path)]
    subprocess.run(cmd, check=True)
    if not out_path.exists():
        raise FrameError(f"ffmpeg wrote no frame for {video} at {at}s")
    return out_path


def sample(film, out_dir, *, per_shot: int = DEFAULT_PER_SHOT, crop=None, log=print) -> list:
    """Every frame the checker will read, in shot order.

    Frames are always re-taken rather than cached. The render ledger caches the
    expensive thing; a cached frame would only save a tenth of a second and
    could quietly hold a picture of the shot as it was before it was fixed,
    which is exactly the failure the re-render demo would show off.
    """
    from .render import shot_path  # local: render imports nothing from here

    out_dir = Path(out_dir)
    frames = []
    for shot in film.shots:
        video = shot_path(out_dir, shot)
        if not video.exists():
            raise FrameError(
                f"{shot.id} has not been rendered: run `python3 -m cinema build` first"
            )
        for index, at in enumerate(offsets(shot.seconds, per_shot)):
            path = grab(
                video, at, out_dir / "frames" / f"{shot.id}-{index}.png", crop=crop
            )
            frames.append(Frame(shot.id, index, at, path))
    log(f"  sampled {len(frames)} frames from {len(film.shots)} shots")
    return frames


def raw_rgb(path, width: int, height: int) -> bytes:
    """A frame as `width * height * 3` bytes of rgb24, scaled down.

    Decoding a PNG is ffmpeg's job here rather than a dependency's: this project
    already needs ffmpeg and needs no pixel library, and scaling to a few
    thousand pixels is also what makes reading them by hand cheap.
    """
    out = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-i", str(path),
            "-vf", f"scale={width}:{height}:flags=area",
            "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ],
        check=True, capture_output=True,
    ).stdout
    expected = width * height * 3
    if len(out) != expected:
        raise FrameError(f"{path} decoded to {len(out)} bytes, expected {expected}")
    return out
