"""Join the rendered shots into one playable file."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path


def probe(path) -> dict:
    """Ask ffprobe what a file actually is. The spec is an intention; this is the file."""
    out = subprocess.run(
        [
            "ffprobe", "-v", "error",
            "-select_streams", "v:0",
            "-show_entries", "stream=width,height,avg_frame_rate,nb_read_packets",
            "-show_entries", "format=duration,format_name",
            "-count_packets", "-of", "json", str(path),
        ],
        check=True, capture_output=True, text=True,
    ).stdout
    data = json.loads(out)
    stream = (data.get("streams") or [{}])[0]
    fmt = data.get("format") or {}
    return {
        "width": stream.get("width"),
        "height": stream.get("height"),
        "fps": stream.get("avg_frame_rate"),
        "frames": int(stream.get("nb_read_packets", 0) or 0),
        "seconds": round(float(fmt.get("duration", 0) or 0), 2),
        "format": fmt.get("format_name"),
    }


def concat(shot_paths, out_path, *, log=print) -> Path:
    """Concatenate shots without re-encoding.

    The demuxer, not the filter: every shot comes out of the same encoder with
    the same parameters, so a stream copy is exact and costs no quality. If a
    shot ever arrives from somewhere else, this is where it will fail loudly
    rather than quietly re-encode the film.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    missing = [str(p) for p in shot_paths if not Path(p).exists()]
    if missing:
        raise SystemExit("cannot assemble, these shots were never rendered: " + ", ".join(missing))

    listing = out_path.parent / "concat.txt"
    listing.write_text(
        "".join(f"file '{Path(p).resolve()}'\n" for p in shot_paths)
    )

    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "concat", "-safe", "0", "-i", str(listing),
            "-c", "copy", str(out_path),
        ],
        check=True,
    )
    log(f"  cut: {out_path}")
    return out_path
