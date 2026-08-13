"""What the submission video is allowed to say, and how long it may say it for.

The video is the one artefact nobody re-runs and nobody can correct after it is
uploaded, so the two failures worth testing are a cut that states a result no
file backs, and a cut that overruns the three minutes Devpost judges.

The proof of the first is the same as the page's: change the files and watch the
video change. The proof of the second is that `storyboard` refuses before a
frame is encoded, and `build` re-reads the finished file rather than trusting
the panel lengths it asked for.

Everything here runs offline and costs nothing.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cinema import assemble, demo  # noqa: E402

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
    "film": "The Courier",
    "reader": "pixels",
    "model": None,
    "frames_per_shot": 2,
    "at": "2026-08-13T07:22:36+00:00",
    "cost_usd": 0.0,
    "shots": [{"shot": f"s0{n}"} for n in range(1, 6)],
    "breaks": [],
}

CONSOLES = {"check": "check: 5 shots, 2 frames each, on pixels", "score": "score: the grading ran"}


def storyboard(score=None, report=None, consoles=None, plates=None, cut_seconds=40.0, page=None):
    return demo.storyboard(
        json.loads(json.dumps(score or SCORE)),
        json.loads(json.dumps(report or REPORT)),
        plates if plates is not None else [("s03", Path("s03.png")), ("s04", Path("s04.png"))],
        Path("out/cut.mp4"),
        consoles or CONSOLES,
        cut_seconds=cut_seconds,
        page=page,
    )


def words(panels) -> str:
    return "\n".join(p.heading + "\n" + "\n".join(p.lines) + "\n" + p.caption for p in panels)


class FiguresComeFromTheFiles(unittest.TestCase):
    """Every number on a card is read, not written."""

    def test_the_headline_counts_are_the_scorers(self):
        self.assertIn("2 planted, 2 found", words(storyboard()))

    def test_a_worse_run_makes_a_worse_video(self):
        worse = json.loads(json.dumps(SCORE))
        worse["found_breaks"] = 1
        worse["misses"] = [{"shot": "s04", "attribute": "parcel", "expected": "present",
                            "found": "present", "sentence": "s04: parcel was present, is absent"}]
        worse["hits"] = worse["hits"][:1]
        text = words(storyboard(score=worse))
        self.assertIn("2 planted, 1 found", text)
        self.assertIn("MISSED", text)
        self.assertNotIn("2 planted, 2 found", text)

    def test_a_false_alarm_is_shown_and_not_quietly_dropped(self):
        noisy = json.loads(json.dumps(SCORE))
        noisy["false_alarms"] = [{"shot": "s02", "attribute": "jacket", "expected": "red",
                                  "found": "green", "sentence": "s02: jacket was red, is green"}]
        self.assertIn("FALSE ALARM", words(storyboard(score=noisy)))

    def test_the_cell_line_moves_with_the_cells(self):
        misread = json.loads(json.dumps(SCORE))
        misread["cells"] = {"total": 15, "agreed": 12, "misread": [], "disputed": [], "unanswered": []}
        self.assertIn("12 of 15 cells read as declared", words(storyboard(score=misread)))

    def test_the_reader_is_named_beside_the_score(self):
        gemini = json.loads(json.dumps(REPORT))
        gemini["reader"] = "gemini"
        text = words(storyboard(report=gemini))
        self.assertIn("reader: gemini", text)
        self.assertNotIn("reader: pixels", text)

    def test_the_cost_comparison_is_priced_not_asserted(self):
        """Five 8-second shots on Veo 3.1 standard 1080p with audio: $16.00."""
        self.assertIn("$16.00", words(storyboard()))

    def test_the_cost_comparison_follows_the_shot_count(self):
        two = json.loads(json.dumps(REPORT))
        two["shots"] = two["shots"][:2]
        text = words(storyboard(report=two))
        self.assertIn("$6.40", text)
        self.assertNotIn("$16.00", text)

    def test_the_console_panels_are_the_captured_output(self):
        text = words(storyboard(consoles={"check": "check: nothing was found", "score": "score: 0"}))
        self.assertIn("check: nothing was found", text)

    def test_one_panel_per_repaired_shot(self):
        # The before/after run is the stills after the score card. The opening
        # plate repeats the first of them on purpose, so it is counted out here
        # rather than allowed to hide a missing or a duplicated repair.
        panels = storyboard(plates=[("s03", Path("s03.png"))])
        start = next(i for i, p in enumerate(panels) if "planted," in p.heading)
        stills = [p for p in panels[start:] if p.kind == "still"]
        self.assertEqual([p.source.name for p in stills], ["s03.png"])


class TheOpening(unittest.TestCase):
    """A judge who stops at thirty seconds has to have seen the tool work."""

    def test_a_repaired_shot_is_on_screen_inside_the_first_thirty_seconds(self):
        at, seen = 0.0, []
        for panel in storyboard():
            if at >= 30:
                break
            seen.append(panel)
            at += panel.seconds
        stills = [p for p in seen if p.kind == "still"]
        self.assertTrue(stills, "the opening shows no result, only the problem")
        self.assertIn("s03", stills[0].caption)

    def test_the_opening_plate_carries_the_scorers_own_sentence(self):
        lead = [p for p in storyboard() if p.kind == "still"][0]
        self.assertIn("s03: jacket was red, is blue", lead.caption)

    def test_a_run_that_repaired_nothing_opens_on_the_film(self):
        panels = storyboard(plates=[])
        self.assertEqual([p.kind for p in panels[:2]], ["card", "clip"])


class TheHostedPage(unittest.TestCase):
    """Devpost wants a project that runs on the web, so the cut shows it running."""

    def test_the_page_is_on_screen_and_named(self):
        panels = storyboard(page=Path("out/demo/page.png"))
        showing = [p for p in panels if p.source == Path("out/demo/page.png")]
        self.assertEqual(len(showing), 1, "the hosted page is shown once, or not at all")
        self.assertIn("joemuller.com/continuity-checker", showing[0].caption)

    def test_the_page_follows_the_plates_it_is_the_inspector_for(self):
        panels = storyboard(page=Path("page.png"))
        kinds = [p.kind for p in panels]
        page_at = [i for i, p in enumerate(panels) if p.source == Path("page.png")][0]
        plates = [i for i, p in enumerate(panels) if p.kind == "still" and i != page_at]
        self.assertGreater(page_at, max(plates))
        self.assertEqual(kinds[page_at + 1], "card", "the cut has to explain the repair afterwards")

    def test_a_build_with_no_picture_of_the_page_still_cuts(self):
        panels = storyboard(page=None)
        self.assertNotIn("joemuller.com/continuity-checker", "\n".join(p.caption for p in panels))

    def test_the_page_beat_still_fits_the_three_minutes(self):
        panels = storyboard(page=Path("page.png"))
        self.assertLessEqual(sum(p.seconds for p in panels), demo.LIMIT_SECONDS)


class TheCaptions(unittest.TestCase):
    """The caption band draws one line and loses the rest without saying so."""

    def test_every_caption_fits_the_band(self):
        for panel in storyboard(page=Path("page.png")):
            self.assertLessEqual(len(panel.caption), demo.CAPTION_COLS, panel.caption)

    def test_a_caption_too_wide_for_the_band_is_a_refusal(self):
        long = json.loads(json.dumps(SCORE))
        long["hits"][0]["sentence"] = "s03: " + "the jacket was red and is now blue, " * 4
        with self.assertRaises(demo.DemoError) as caught:
            storyboard(score=long)
        self.assertIn("off the right edge", str(caught.exception))


class TheRunningTime(unittest.TestCase):
    """Devpost judges the first three minutes and truncates the rest."""

    def test_the_cut_fits_the_three_minutes(self):
        self.assertLessEqual(
            sum(p.seconds for p in storyboard(page=Path("page.png"))), demo.LIMIT_SECONDS
        )

    def test_a_longer_film_is_refused_rather_than_truncated(self):
        with self.assertRaises(demo.DemoError) as caught:
            storyboard(cut_seconds=300.0)
        self.assertIn("only the first", str(caught.exception))

    def test_the_film_itself_is_played_at_its_real_length(self):
        clip = [p for p in storyboard(cut_seconds=31.5) if p.kind == "clip"][0]
        self.assertEqual(clip.seconds, 31.5)


class TheConsolePanels(unittest.TestCase):
    """A line that does not fit is drawn off the frame, and ffmpeg exits 0."""

    def test_a_long_line_is_folded_rather_than_lost(self):
        line = "  pixels: " + "x" * 200
        folded = demo._console(line)
        self.assertGreater(len(folded), 1)
        self.assertTrue(all(len(f) <= demo.CONSOLE_COLS for f in folded))

    def test_a_short_line_is_left_exactly_as_printed(self):
        self.assertEqual(demo._console("  s01  jacket=red"), ("  s01  jacket=red",))

    def test_more_lines_than_the_panel_draws_is_a_refusal(self):
        with self.assertRaises(demo.DemoError) as caught:
            storyboard(consoles={"check": "\n".join(f"line {n}" for n in range(60)), "score": "ok"})
        self.assertIn("drawn off the bottom", str(caught.exception))


class TheSubtitles(unittest.TestCase):
    """The rules want English narration or English subtitles. There is no speech."""

    def test_every_panel_gets_a_cue_covering_its_own_seconds(self):
        panels = storyboard()
        srt = demo.subtitles(panels)
        self.assertEqual(srt.count("-->"), len(panels))
        self.assertTrue(srt.startswith("1\n00:00:00,000 --> "))

    def test_the_cues_run_to_the_length_of_the_cut(self):
        panels = storyboard()
        total = sum(p.seconds for p in panels)
        self.assertIn(demo._timestamp(total), demo.subtitles(panels))

    def test_a_picture_panel_is_captioned_rather_than_left_blank(self):
        clip = [p for p in storyboard() if p.kind == "clip"][0]
        self.assertIn("continuity breaks are in here", clip.subtitle)


class Refusals(unittest.TestCase):
    """A video with a hole in it is worse than no video."""

    def test_a_missing_artefact_stops_the_build(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(demo.DemoError) as caught:
                demo.build(Path(tmp), Path(tmp) / "demo.mp4")
            self.assertIn("score.json", str(caught.exception))

    def test_a_failing_command_is_not_shown_as_a_passing_one(self):
        with self.assertRaises(demo.DemoError) as caught:
            demo.capture(["score", "--no-such-flag"], cwd=ROOT)
        self.assertIn("exited", str(caught.exception))


class TheEncode(unittest.TestCase):
    """The panel lengths are an intention; the file is the fact."""

    def test_a_card_comes_out_at_the_size_and_length_it_asked_for(self):
        panel = demo.Panel("card", 1.0, "A heading", ("a line", "another"))
        with tempfile.TemporaryDirectory() as tmp:
            made = demo._panel(panel, 1, Path(tmp))
            probed = assemble.probe(made)
        self.assertEqual((probed["width"], probed["height"]), (demo.WIDTH, demo.HEIGHT))
        self.assertAlmostEqual(probed["seconds"], 1.0, places=1)

    def test_a_picture_panel_with_nothing_to_show_is_a_refusal(self):
        panel = demo.Panel("still", 1.0, "", caption="a caption", source=None)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(demo.DemoError):
                demo._panel(panel, 1, Path(tmp))


if __name__ == "__main__":
    unittest.main()
