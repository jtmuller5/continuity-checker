"""What the hosted page is allowed to say.

The page is the one artefact a judge reads without running anything, so the
failure to guard against is a page that keeps claiming a good run after the run
stopped being good. One claim, then, and every test here belongs to it: **every
figure on the page is read out of the files the pipeline wrote.**

The way to prove that is to change the files and watch the page change. A page
with "2 of 2 breaks found" typed into it passes any test that only looks for the
words, so each test below moves a number in `score.json` or `continuity.json`
and asserts the page moved with it.

Everything here runs offline and costs nothing.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cinema import publish  # noqa: E402

SCORE = {
    "expected_breaks": 2,
    "found_breaks": 2,
    "hits": [
        {"shot": "s03", "attribute": "jacket", "expected": "red", "found": "blue",
         "sentence": "s03: jacket was red, is blue"},
        {"shot": "s04", "attribute": "parcel", "expected": "present", "found": "absent",
         "sentence": "s04: parcel was present, is absent"},
    ],
    "misses": [],
    "false_alarms": [],
    "near_misses": [],
    "cells": {"total": 15, "agreed": 15, "misread": [], "disputed": [], "unanswered": []},
    "stale_shots": [],
    "perfect": True,
}

REPORT = {
    "version": 1,
    "film": "The Courier",
    "reader": "pixels",
    "model": None,
    "frames_per_shot": 2,
    "at": "2026-08-13T06:57:23+00:00",
    "cost_usd": 0.0,
    "shots": [{"shot": f"s0{i}"} for i in range(1, 6)],
}


def video(path: Path, seconds: int = 2) -> Path:
    """A real, tiny mp4 — `publish` copies it and grabs a poster out of it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c=navy:s=160x90:d={seconds}",
            "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )
    return path


def png(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", "color=c=red:s=160x90:d=1",
            "-frames:v", "1", str(path),
        ],
        check=True,
    )
    return path


def out_dir(root: Path, *, score=None, report=None, plates=("s03", "s04")) -> Path:
    """A believable `out/`, as `cinema fix` would have left it."""
    out = root / "out"
    out.mkdir(parents=True, exist_ok=True)
    (out / "score.json").write_text(json.dumps(score if score is not None else SCORE))
    (out / "continuity.json").write_text(json.dumps(report if report is not None else REPORT))
    video(out / "cut.mp4")
    for shot in plates:
        png(out / "before-after" / f"{shot}.png")
        png(out / "before-after" / f"{shot}-before.png")
        png(out / "before-after" / f"{shot}-after.png")
    return out


class RefusalTests(unittest.TestCase):
    """A missing artefact is a refusal, not a page with a hole in it."""

    def test_no_out_dir_at_all(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with self.assertRaises(publish.PublishError) as caught:
                publish.publish(root / "out", root / "docs", repo="https://example.org")
            self.assertIn("score.json", str(caught.exception))
            self.assertFalse((root / "docs").exists())

    def test_each_required_artefact_is_named_when_it_is_missing(self):
        for name in publish.REQUIRED:
            with self.subTest(name=name), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                out = out_dir(root)
                (out / name).unlink()
                with self.assertRaises(publish.PublishError) as caught:
                    publish.publish(out, root / "docs", repo="https://example.org")
                self.assertIn(name, str(caught.exception))

    def test_a_run_that_repaired_nothing_has_no_plates_to_show(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = out_dir(root, plates=())
            with self.assertRaises(publish.PublishError) as caught:
                publish.publish(out, root / "docs", repo="https://example.org")
            self.assertIn("before-after", str(caught.exception))

    def test_the_cli_reports_the_refusal_and_exits_nonzero(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = subprocess.run(
                [sys.executable, "-m", "cinema", "--out", str(Path(tmp) / "out"),
                 "publish", "--site", str(Path(tmp) / "docs")],
                cwd=ROOT, capture_output=True, text=True,
            )
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("publish:", result.stdout)


class WrittenFromTheRunTests(unittest.TestCase):
    """Move a number in the files; the page has to move with it."""

    def build(self, root: Path, **kwargs) -> str:
        out = out_dir(root, **kwargs)
        index = publish.publish(out, root / "docs", repo="https://example.org/repo")
        return index.read_text()

    def test_the_assets_are_the_run_s_own_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            html = self.build(root)
            assets = root / "docs" / publish.ASSETS
            for name in ("cut.mp4", "poster.png", "s03.png", "s04.png"):
                self.assertTrue((assets / name).exists(), name)
                self.assertIn(name, html)
            # The poster is a frame of the cut, not one of the plates.
            self.assertGreater((assets / "poster.png").stat().st_size, 0)

    def test_a_missed_break_is_shown_as_missed(self):
        with tempfile.TemporaryDirectory() as tmp:
            score = json.loads(json.dumps(SCORE))
            score["misses"] = [score["hits"].pop()]
            score["found_breaks"] = 1
            score["perfect"] = False
            html = self.build(Path(tmp), score=score)
            self.assertIn("MISSED", html)
            self.assertIn("2 breaks planted, 1 found", html)

    def test_one_break_is_not_written_as_one_breaks(self):
        with tempfile.TemporaryDirectory() as tmp:
            score = json.loads(json.dumps(SCORE))
            score["expected_breaks"] = score["found_breaks"] = 1
            score["hits"] = score["hits"][:1]
            html = self.build(Path(tmp), score=score)
            self.assertIn("1 break planted, 1 found", html)

    def test_a_false_alarm_is_shown_as_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            score = json.loads(json.dumps(SCORE))
            score["false_alarms"] = [
                {"shot": "s02", "attribute": "jacket", "expected": "red", "found": "unclear",
                 "sentence": "s02: jacket was red, is unclear"}
            ]
            score["perfect"] = False
            html = self.build(Path(tmp), score=score)
            self.assertIn("FALSE ALARM", html)
            self.assertIn("s02", html)

    def test_a_near_miss_is_named_separately_from_a_hit(self):
        with tempfile.TemporaryDirectory() as tmp:
            score = json.loads(json.dumps(SCORE))
            score["near_misses"] = [{
                "expected": {"shot": "s03", "attribute": "jacket", "expected": "red", "found": "blue"},
                "found": {"shot": "s03", "attribute": "jacket", "expected": "red", "found": "green"},
            }]
            html = self.build(Path(tmp), score=score)
            self.assertIn("near miss", html)
            self.assertIn("green", html)

    def test_a_cell_the_checker_could_not_read_is_on_the_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            score = json.loads(json.dumps(SCORE))
            score["cells"] = {
                "total": 15, "agreed": 13,
                "misread": [{"shot": "s02", "attribute": "jacket", "declared": "red", "read": "blue"}],
                "disputed": [],
                "unanswered": [{"shot": "s05", "attribute": "parcel", "declared": "present", "read": None}],
            }
            score["perfect"] = False
            html = self.build(Path(tmp), score=score)
            self.assertIn("13 of 15 cells read as declared", html)
            self.assertIn("1 misread", html)
            self.assertIn("1 unanswered", html)

    def test_the_reader_is_named_and_described(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = self.build(Path(tmp))
            self.assertIn("pixels", html)
            self.assertIn("it is not the detection", html)

    def test_a_gemini_run_is_described_as_the_detector_with_its_model(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = dict(REPORT, reader="gemini", model="gemini-2.5-pro", cost_usd=0.0412)
            html = self.build(Path(tmp), report=report)
            self.assertIn("gemini-2.5-pro", html)
            self.assertIn("Gemini on Vertex AI, one call per frame", html)
            self.assertIn("$0.0412", html)

    def test_an_unrecognised_reader_is_not_given_a_description_it_did_not_earn(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = self.build(Path(tmp), report=dict(REPORT, reader="handwave"))
            self.assertIn("handwave", html)
            self.assertIn("unrecognised reader", html)
            self.assertNotIn("it is not the detection", html)

    def test_the_page_discloses_the_agent_and_links_the_repo(self):
        with tempfile.TemporaryDirectory() as tmp:
            html = self.build(Path(tmp))
            self.assertIn("autonomous agent working for Joe Muller", html)
            self.assertIn("https://example.org/repo", html)

    def test_a_value_out_of_the_report_cannot_inject_markup(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = dict(REPORT, film="<script>alert(1)</script>")
            html = self.build(Path(tmp), report=report)
            self.assertNotIn("<script>alert(1)</script>", html)
            self.assertIn("&lt;script&gt;", html)


class ShippedPageTests(unittest.TestCase):
    """The page in `docs/` is the one the checked-in run produced."""

    def test_docs_index_matches_what_publish_builds_from_out(self):
        out, docs = ROOT / "out", ROOT / "docs" / "index.html"
        if not (out / "score.json").exists() or not docs.exists():
            self.skipTest("no run on disk to compare against")
        score = json.loads((out / "score.json").read_text())
        report = json.loads((out / "continuity.json").read_text())
        expected = publish.page(score, report, publish._plates(out), publish.REPO)
        self.assertEqual(docs.read_text(), expected, "docs/index.html is stale — run `cinema publish`")


if __name__ == "__main__":
    unittest.main()
