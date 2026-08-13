"""The whole path the demo walks, run through the CLI in one workspace.

Every other test file holds one stage still and pokes at it with fakes. This
one types the commands. A judge, or Joe on the day, runs `build`, `check`,
`score`, `publish`, `demo`, `fix`, and then puts the film back the way the
submission shows it — and until now nothing proved that sequence works, because
`cmd_build`, `cmd_fix` and `cmd_demo` were never once executed.

The sequence runs once in `setUpClass`, against the real `film.yaml`, the
placeholder backend and the pixel reader. Every step's stdout and every JSON
artefact is snapshotted as it is produced, so a later step cannot quietly
repair an earlier assertion. A non-zero exit anywhere fails the class with that
command's stderr attached.

It costs $0.00, needs no credential and no network, and takes about fifteen
seconds — most of it the video.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cinema import assemble, demo, fixes, pageshot, spec  # noqa: E402


def chrome_available() -> bool:
    """The demo photographs the hosted page, so it needs a browser."""
    try:
        pageshot.browser()
    except pageshot.PageshotError:
        return False
    return True


class TheDemoPath(unittest.TestCase):
    """Every command the walkthrough runs, in the order it runs them."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.work = Path(cls.tmp.name)
        shutil.copy(ROOT / "film.yaml", cls.work / "film.yaml")
        cls.env = dict(os.environ, PYTHONPATH=str(ROOT))
        cls.out = cls.work / "out"
        cls.site = cls.work / "docs"
        cls.film = spec.load(ROOT / "film.yaml")
        cls.said = {}

        cls.said["build"] = cls.cli("build")
        cls.said["rebuild"] = cls.cli("build")
        cls.said["check"] = cls.cli("check")
        cls.report = cls.read("continuity.json")
        cls.said["score"] = cls.cli("score")
        cls.score = cls.read("score.json")

        # The repair, and then the way back. `publish` and `demo` both refuse a
        # run with no before/after plates, so `fix` comes before them — and the
        # submission shows the planted film, so a `fix` that could not be undone
        # would cost the entry its own fixture.
        cls.said["fix"] = cls.cli("fix")
        cls.fixed = cls.read("score.json")
        cls.said["revert"] = cls.cli("fix", "--revert")
        cls.said["restore"] = cls.cli("build")
        cls.said["recheck"] = cls.cli("check")
        cls.said["rescore"] = cls.cli("score")
        cls.restored = cls.read("score.json")

        cls.said["publish"] = cls.cli("publish")
        cls.page = (cls.site / "index.html").read_text()

        cls.demo = cls.cli("demo") if chrome_available() else None

        # Last, because it re-renders a shot and leaves the report behind it.
        cls.said["one-shot"] = cls.cli("build", "--shot", "s03")
        cls.said["stale"] = cls.cli("score", expect=2)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    @classmethod
    def cli(cls, *argv: str, expect: int = 0) -> str:
        proc = subprocess.run(
            [sys.executable, "-m", "cinema", *argv],
            cwd=cls.work, env=cls.env, capture_output=True, text=True,
        )
        if proc.returncode != expect:
            raise AssertionError(
                f"`cinema {' '.join(argv)}` exited {proc.returncode}, wanted {expect}\n"
                f"--- stdout ---\n{proc.stdout}\n--- stderr ---\n{proc.stderr}"
            )
        return proc.stdout

    @classmethod
    def read(cls, name: str) -> dict:
        return json.loads((cls.out / name).read_text())

    # --- build -----------------------------------------------------------

    def test_the_build_renders_every_shot_and_assembles_the_cut(self):
        for shot in self.film.shots:
            path = self.out / "shots" / f"{shot.id}-{shot.slug}.mp4"
            self.assertTrue(path.exists(), f"{path} was not rendered")
        self.assertTrue((self.out / "cut.mp4").exists())
        self.assertIn(f"{len(self.film.shots)} rendered, 0 cached", self.said["build"])

    def test_a_second_build_renders_nothing(self):
        """The cache is what makes iterating on Veo affordable. Prove it holds."""
        self.assertIn(f"0 rendered, {len(self.film.shots)} cached", self.said["rebuild"])
        self.assertEqual(0.0, sum(
            float(e.get("cost_usd", 0))
            for e in self.read("renders.json")["shots"].values()
        ))

    # --- check -----------------------------------------------------------

    def test_the_checker_finds_exactly_the_planted_breaks(self):
        self.assertEqual(
            [(b.shot, b.attribute, b.before, b.after) for b in self.film.expected_breaks],
            [(b["shot"], b["attribute"], b["expected"], b["found"])
             for b in self.report["breaks"]],
        )

    def test_the_report_carries_the_questions_the_page_needs(self):
        """A version 1 report is refused by `publish`, so the run must write 2."""
        self.assertEqual(2, self.report["version"])
        self.assertEqual(
            sorted(q["attribute"] for q in self.report["questions"]),
            sorted(self.film.bible.names),
        )

    def test_the_free_reader_is_named_in_the_report_and_cost_nothing(self):
        """Never let a `pixels` run be quoted as detection. It says so itself."""
        self.assertEqual("pixels", self.report["reader"])
        self.assertEqual(0.0, self.report["cost_usd"])

    # --- score -----------------------------------------------------------

    def test_the_score_confirms_every_planted_break_and_flags_nothing_else(self):
        self.assertTrue(self.score["perfect"])
        self.assertEqual(len(self.film.expected_breaks), self.score["expected_breaks"])
        self.assertEqual(len(self.film.expected_breaks), self.score["found_breaks"])
        self.assertEqual([], self.score["false_alarms"])
        self.assertEqual([], self.score["misses"])
        self.assertEqual([], self.score["near_misses"])

    def test_every_cell_was_read_as_declared(self):
        cells = self.score["cells"]
        self.assertEqual(cells["total"], cells["agreed"])
        self.assertEqual(([], [], []),
                         (cells["misread"], cells["disputed"], cells["unanswered"]))

    def test_a_report_older_than_the_film_is_refused(self):
        """Scoring the pre-fix report after a re-render is how the demo lies."""
        self.assertIn("the report is older than s03", self.said["stale"])
        self.assertIn("Run `check` again", self.said["stale"])

    # --- publish ---------------------------------------------------------

    def test_the_page_says_what_this_run_said(self):
        for hit in self.restored["hits"]:
            self.assertIn(hit["sentence"], self.page)
        self.assertIn("pixels", self.page)
        for name in ("cut.mp4", "s03.png", "s04.png"):
            self.assertTrue((self.site / "assets" / name).exists(), name)

    # --- demo ------------------------------------------------------------

    def test_the_video_is_cut_and_fits_devposts_three_minutes(self):
        if self.demo is None:
            self.skipTest("no headless browser, so the page beat cannot be shot")
        video = self.out / "demo.mp4"
        self.assertTrue(video.exists())
        self.assertLessEqual(assemble.probe(video)["seconds"], 180.0)
        self.assertTrue((self.out / "demo.srt").read_text().strip())

    def test_the_video_reports_this_runs_own_figures(self):
        if self.demo is None:
            self.skipTest("no headless browser, so the page beat cannot be shot")
        planted = len(self.film.expected_breaks)
        self.assertIn(f"{planted} planted, {planted} found", self.demo)

    # --- fix, and the way back -------------------------------------------

    def test_the_repair_re_renders_only_the_shots_whose_keys_moved(self):
        broken = {b.shot for b in self.film.expected_breaks}
        for shot_id in sorted(broken):
            self.assertIn(f"{shot_id} ", self.said["fix"])
            self.assertTrue((self.out / "before-after" / f"{shot_id}.png").exists())
        self.assertNotIn(f"{len(self.film.shots)} rendered", self.said["fix"])
        self.assertIn("cached", self.said["fix"])

    def test_the_repaired_film_has_nothing_left_to_find(self):
        self.assertEqual(0, self.fixed["expected_breaks"])
        self.assertEqual(0, self.fixed["found_breaks"])
        self.assertTrue(self.fixed["perfect"])
        self.assertIn("declares no breaks", self.said["fix"])

    def test_reverting_puts_the_planted_film_back(self):
        """The submission shows the broken film. `fix` must not be one-way."""
        self.assertIn("dropped the repairs", self.said["revert"])
        self.assertFalse((self.out / "fixes.json").exists())
        self.assertEqual(self.score["expected_breaks"], self.restored["expected_breaks"])
        self.assertEqual(self.score["found_breaks"], self.restored["found_breaks"])
        self.assertTrue(self.restored["perfect"])


class TheRepairedFilmIsCalledOut(unittest.TestCase):
    """A cut made while `fix` is applied reports a film with no breaks in it.

    Every command in that run exits 0 and the video still shows the plates, so
    nothing else in this repo would notice. `cinema demo` says it out loud.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.work = Path(self.tmp.name)
        shutil.copy(ROOT / "film.yaml", self.work / "film.yaml")
        self.out = self.work / "out"
        self.out.mkdir()
        self.addCleanup(self.tmp.cleanup)

    def test_a_run_with_no_repairs_says_nothing(self):
        self.assertIsNone(demo.repaired_warning(self.out))

    def test_the_repaired_shots_are_named_with_the_way_back(self):
        fixes.save(self.out, {"s03": {"jacket": "blue"}}, note="a test")
        said = demo.repaired_warning(self.out)
        self.assertIn("s03", said)
        self.assertIn("fix --revert", said)

    def test_the_command_prints_it_before_it_cuts_anything(self):
        fixes.save(self.out, {"s03": {"jacket": "blue"}}, note="a test")
        proc = subprocess.run(
            [sys.executable, "-m", "cinema", "demo"],
            cwd=self.work, env=dict(os.environ, PYTHONPATH=str(ROOT)),
            capture_output=True, text=True,
        )
        # It refuses for want of a rendered film, which is what keeps this test
        # cheap. The warning is what has to arrive first.
        self.assertEqual(1, proc.returncode, proc.stdout)
        self.assertLess(proc.stdout.index("still applied"), proc.stdout.index("missing"))


class TheCommandsAroundIt(unittest.TestCase):
    """The read-only commands, which nothing else runs at all."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.work = Path(cls.tmp.name)
        shutil.copy(ROOT / "film.yaml", cls.work / "film.yaml")
        cls.env = dict(os.environ, PYTHONPATH=str(ROOT))

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def cli(self, *argv: str, expect: int = 0) -> str:
        proc = subprocess.run(
            [sys.executable, "-m", "cinema", *argv],
            cwd=self.work, env=self.env, capture_output=True, text=True,
        )
        self.assertEqual(expect, proc.returncode, proc.stdout + proc.stderr)
        return proc.stdout

    def test_info_describes_the_film(self):
        said = self.cli("info")
        self.assertIn(spec.load(ROOT / "film.yaml").title, said)

    def test_the_bible_prints_the_prompt_a_shot_is_generated_from(self):
        said = self.cli("bible", "--prompts")
        film = spec.load(ROOT / "film.yaml")
        self.assertIn(film.shots[0].text.split("\n")[0], said)

    def test_timings_says_so_when_nothing_has_been_rendered(self):
        self.assertIn("nothing rendered yet", self.cli("timings"))

    def test_a_billing_backend_is_refused_without_the_flag(self):
        """The loop may not pass `--i-will-pay`, so the guard is load-bearing."""
        proc = subprocess.run(
            [sys.executable, "-m", "cinema", "build", "--backend", "veo"],
            cwd=self.work, env=self.env, capture_output=True, text=True,
        )
        self.assertNotEqual(0, proc.returncode)
        self.assertIn("i-will-pay", (proc.stdout + proc.stderr).lower())


if __name__ == "__main__":
    unittest.main()
