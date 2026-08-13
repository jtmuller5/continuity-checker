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
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cinema import publish, webapp  # noqa: E402

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

QUESTIONS = [
    {"attribute": "jacket", "text": "What colour is the courier's jacket?",
     "values": ["red", "blue", "unclear"]},
    {"attribute": "parcel", "text": "Is the courier carrying the parcel?",
     "values": ["present", "absent", "unclear"]},
    {"attribute": "time_of_day", "text": "What time of day is it?",
     "values": ["dusk", "night", "unclear"]},
]


def _shot(shot_id: str, jacket: str = "red", parcel: str = "present") -> dict:
    """One shot as `check` writes it: two stills, each with its own answers."""
    answers = {"jacket": jacket, "parcel": parcel, "time_of_day": "dusk"}
    return {
        "shot": shot_id,
        "state": dict(answers),
        "unanswered": [],
        "disputed": {},
        "frames": [
            {"index": i, "at": 2.0 + 4 * i, "path": f"frames/{shot_id}-{i}.png",
             "answers": dict(answers), "state": dict(answers)}
            for i in range(2)
        ],
    }


REPORT = {
    "version": 2,
    "film": "The Courier",
    "reader": "pixels",
    "model": None,
    "frames_per_shot": 2,
    "at": "2026-08-13T06:57:23+00:00",
    "cost_usd": 0.0,
    "questions": QUESTIONS,
    "shots": [
        _shot("s01"), _shot("s02"), _shot("s03", jacket="blue"),
        _shot("s04", jacket="blue", parcel="absent"), _shot("s05", jacket="blue", parcel="absent"),
    ],
    "breaks": [
        {"shot": "s03", "attribute": "jacket", "expected": "red", "found": "blue",
         "rule": "constant", "sentence": "s03: jacket was red, is blue"},
        {"shot": "s04", "attribute": "parcel", "expected": "present", "found": "absent",
         "rule": "constant", "sentence": "s04: parcel was present, is absent"},
    ],
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


_PNG: list = []


def png(path: Path) -> Path:
    """A real png. Drawn once and copied after that — a run has ten frames in it."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not _PNG:
        made = Path(tempfile.mkdtemp()) / "seed.png"
        subprocess.run(
            [
                "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
                "-f", "lavfi", "-i", "color=c=red:s=160x90:d=1",
                "-frames:v", "1", str(made),
            ],
            check=True,
        )
        _PNG.append(made)
    shutil.copy2(_PNG[0], path)
    return path


def out_dir(root: Path, *, score=None, report=None, plates=("s03", "s04")) -> Path:
    """A believable `out/`, as `cinema fix` would have left it."""
    out = root / "out"
    out.mkdir(parents=True, exist_ok=True)
    report = report if report is not None else REPORT
    (out / "score.json").write_text(json.dumps(score if score is not None else SCORE))
    (out / "continuity.json").write_text(json.dumps(report))
    for name in webapp.frame_paths(report):
        png(out / name)
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
            assets = root / "docs" / webapp.assets_dir(publish.MAIN)
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


class InspectorTests(unittest.TestCase):
    """The part a judge operates, and the one claim it has to keep.

    It shows the run. It does not decide anything about the run — so every test
    here reads the data the page carries and asserts it is what the two files
    say, not what a second implementation would have worked out.
    """

    def inlined(self, html: str) -> dict:
        """Everything the page carries, back out of the inlined block."""
        opener = '<script type="application/json" id="run-data">'
        start = html.index(opener) + len(opener)
        end = html.index("</script>", start)
        return json.loads(html[start:end])

    def payload(self, html: str, index: int = 0) -> dict:
        """One film of the run, in picker order."""
        return self.inlined(html)["films"][index]

    def build(self, root: Path, **kwargs) -> str:
        out = out_dir(root, **kwargs)
        index = publish.publish(out, root / "docs", repo="https://example.org/repo")
        return index.read_text()

    def test_the_frames_the_report_names_are_served_beside_the_page(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            html = self.build(root)
            for shot in self.payload(html)["shots"]:
                for frame in shot["frames"]:
                    served = root / "docs" / frame["src"]
                    self.assertTrue(served.exists(), frame["src"])
                    self.assertIn(frame["src"], html)

    def test_a_frame_named_in_the_report_but_gone_from_disk_is_a_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            out = out_dir(root)
            (out / "frames" / "s03-1.png").unlink()
            with self.assertRaises(publish.PublishError) as caught:
                publish.publish(out, root / "docs", repo="https://example.org")
            self.assertIn("s03-1.png", str(caught.exception))

    def test_a_report_from_before_this_build_is_refused_rather_than_shown_blank(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = json.loads(json.dumps(REPORT))
            del report["questions"]
            with self.assertRaises(publish.PublishError) as caught:
                self.build(Path(tmp), report=report)
            self.assertIn("questions", str(caught.exception))

    def test_the_questions_shown_are_the_ones_the_checker_was_asked(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = json.loads(json.dumps(REPORT))
            report["questions"][0]["text"] = "Which coat is the rider wearing?"
            html = self.build(Path(tmp), report=report)
            self.assertIn("Which coat is the rider wearing?", html)
            self.assertEqual(
                [q["text"] for q in self.payload(html)["questions"]],
                [q["text"] for q in report["questions"]],
            )

    def test_what_each_still_was_said_to_contain_is_carried_per_frame(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = json.loads(json.dumps(REPORT))
            report["shots"][2]["frames"][1]["answers"]["jacket"] = "green"
            shots = {s["id"]: s for s in self.payload(self.build(Path(tmp), report=report))["shots"]}
            self.assertEqual(shots["s03"]["frames"][1]["answers"]["jacket"], "green")
            self.assertEqual(shots["s03"]["frames"][0]["answers"]["jacket"], "blue")

    def test_the_verdict_beside_a_shot_is_the_scorer_s_own(self):
        with tempfile.TemporaryDirectory() as tmp:
            score = json.loads(json.dumps(SCORE))
            score["misses"] = [score["hits"].pop()]
            score["found_breaks"] = 1
            shots = {s["id"]: s for s in self.payload(self.build(Path(tmp), score=score))["shots"]}
            self.assertEqual([v["label"] for v in shots["s03"]["verdicts"]], ["found"])
            self.assertEqual([v["label"] for v in shots["s04"]["verdicts"]], ["MISSED"])
            self.assertEqual(shots["s01"]["verdicts"], [])

    def test_a_break_the_checker_never_reported_still_reaches_its_shot(self):
        """The one thing a shot's own reading cannot show is silence."""
        with tempfile.TemporaryDirectory() as tmp:
            score = json.loads(json.dumps(SCORE))
            report = json.loads(json.dumps(REPORT))
            score["misses"] = [score["hits"].pop()]
            report["breaks"] = report["breaks"][:1]
            shots = {
                s["id"]: s
                for s in self.payload(self.build(Path(tmp), score=score, report=report))["shots"]
            }
            self.assertEqual(shots["s04"]["breaks"], [])
            self.assertEqual([v["label"] for v in shots["s04"]["verdicts"]], ["MISSED"])

    def test_a_cell_the_scorer_flagged_is_flagged_on_its_own_shot(self):
        with tempfile.TemporaryDirectory() as tmp:
            score = json.loads(json.dumps(SCORE))
            score["cells"]["unanswered"] = [
                {"shot": "s05", "attribute": "parcel", "declared": "present", "read": None}
            ]
            shots = {s["id"]: s for s in self.payload(self.build(Path(tmp), score=score))["shots"]}
            self.assertEqual(shots["s05"]["flags"], {"parcel": "unanswered"})
            self.assertEqual(shots["s01"]["flags"], {})

    def test_only_a_repaired_shot_carries_its_plate(self):
        with tempfile.TemporaryDirectory() as tmp:
            shots = {s["id"]: s for s in self.payload(self.build(Path(tmp), plates=("s03",)))["shots"]}
            self.assertEqual(shots["s03"]["plate"], f"assets/{publish.MAIN}/s03.png")
            self.assertIsNone(shots["s04"]["plate"])
            self.assertFalse(shots["s04"]["repaired"])

    def test_the_inlined_run_cannot_close_the_script_block(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = dict(REPORT, film="</script><script>alert(1)</script>")
            html = self.build(Path(tmp), report=report)
            self.assertNotIn("<script>alert(1)</script>", html)
            self.assertEqual(self.payload(html)["film"], report["film"])


class MoreThanOneFilmTests(unittest.TestCase):
    """A second film is a folder under `out/`, and it reaches the picker.

    One film with one pair of breaks is one example, and a checker only ever
    shown against one example is indistinguishable from a checker with that
    example's answer written into it. So the page carries every run on disk —
    and the rule that decides which runs those are has to be a rule, not a flag
    someone remembers to pass, or the shipped page and the page a test rebuilds
    are two different pages.
    """

    SECOND = dict(REPORT, film="The Lighthouse Keeper")

    def two_runs(self, root: Path) -> Path:
        out = out_dir(root)
        second = out / "lighthouse"
        second.mkdir()
        (second / "score.json").write_text(json.dumps(SCORE))
        (second / "continuity.json").write_text(json.dumps(self.SECOND))
        for name in webapp.frame_paths(self.SECOND):
            png(second / name)
        video(second / "cut.mp4")
        for shot in ("s03", "s04"):
            png(second / "before-after" / f"{shot}.png")
        return out

    def inlined(self, html: str) -> dict:
        opener = '<script type="application/json" id="run-data">'
        start = html.index(opener) + len(opener)
        return json.loads(html[start:html.index("</script>", start)])

    def test_a_folder_with_a_score_in_it_is_a_run_and_one_without_is_not(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = self.two_runs(Path(tmp))
            (out / "frames").mkdir(exist_ok=True)
            (out / "demo").mkdir(exist_ok=True)
            self.assertEqual([publish.MAIN, "lighthouse"], [r.key for r in publish.runs(out)])

    def test_both_films_reach_the_picker_named_by_their_own_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index = publish.publish(self.two_runs(root), root / "docs", repo="https://e.org")
            films = self.inlined(index.read_text())["films"]
            self.assertEqual(["The Courier", "The Lighthouse Keeper"], [f["film"] for f in films])
            # And a reader with JavaScript off is still told the second exists.
            self.assertIn("The Lighthouse Keeper", index.read_text())

    def test_each_film_serves_its_own_stills_because_both_have_an_s01(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index = publish.publish(self.two_runs(root), root / "docs", repo="https://e.org")
            seen = set()
            for film in self.inlined(index.read_text())["films"]:
                for shot in film["shots"]:
                    for frame in shot["frames"]:
                        self.assertTrue((root / "docs" / frame["src"]).exists(), frame["src"])
                        seen.add(frame["src"])
            self.assertEqual(
                len(seen), sum(len(webapp.frame_paths(r)) for r in (REPORT, self.SECOND))
            )

    def test_only_the_films_the_page_has_no_player_for_carry_a_cut(self):
        """The hero's video is already at the top; drawing it twice reads as two films."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            index = publish.publish(self.two_runs(root), root / "docs", repo="https://e.org")
            films = self.inlined(index.read_text())["films"]
            self.assertIsNone(films[0]["cut"])
            self.assertEqual("assets/lighthouse/cut.mp4", films[1]["cut"])
            self.assertTrue((root / "docs" / films[1]["cut"]).exists())

    def test_a_still_from_a_run_that_is_gone_is_not_left_on_the_site(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            site = root / "docs"
            publish.publish(self.two_runs(root), site, repo="https://e.org")
            shutil.rmtree(root / "out" / "lighthouse")
            publish.publish(root / "out", site, repo="https://e.org")
            self.assertFalse((site / "assets" / "lighthouse").exists())
            self.assertTrue((site / webapp.assets_dir(publish.MAIN) / "cut.mp4").exists())


class ShippedPageTests(unittest.TestCase):
    """The page in `docs/` is the one the checked-in run produced."""

    def test_docs_index_matches_what_publish_builds_from_out(self):
        out, docs = ROOT / "out", ROOT / "docs" / "index.html"
        if not (out / "score.json").exists() or not docs.exists():
            self.skipTest("no run on disk to compare against")
        expected = publish.page(publish.runs(out), publish.REPO)
        self.assertEqual(docs.read_text(), expected, "docs/index.html is stale — run `cinema publish`")


if __name__ == "__main__":
    unittest.main()
