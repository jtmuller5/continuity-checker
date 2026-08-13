"""What proving the checker has to mean, and what repairing a film may not do.

Three claims, and every test here belongs to one of them:

  * **The score is honest about failure.** A missed break, an invented one and a
    break found in the right place with the wrong values all have to be visible
    and separate. A scorer that only counts hits will report a perfect run on a
    checker that flags everything.
  * **A repair does not touch the answer key.** Fixes are a layer over the spec.
    The planted breaks stay in `film.yaml`, so the fixture cannot be quietly
    graded easier — and a repair that creates a new break has to be caught.
  * **The report survives a round trip.** `score` and `fix` both read the report
    off disk rather than re-running the check, which is what keeps the reader
    and the answer key in separate processes.

Everything here runs offline and costs nothing.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cinema import check, compare, fixes, score, spec  # noqa: E402
from cinema.bible import Break  # noqa: E402


def reading(shot_id, state, *, unanswered=(), disputed=None):
    return check.ShotReading(shot_id, dict(state), tuple(unanswered), dict(disputed or {}))


def report(readings, breaks, *, at="2026-08-13T12:00:00+00:00"):
    return check.Report(
        film="The Courier",
        reader="pixels",
        model=None,
        frames_per_shot=2,
        readings=tuple(readings),
        breaks=tuple(breaks),
        cost=0.0,
        at=at,
    )


class ScoreTests(unittest.TestCase):
    """The film on disk, judged against reports that get it right and wrong."""

    @classmethod
    def setUpClass(cls):
        cls.film = spec.load(ROOT / "film.yaml")

    def declared(self, **overrides):
        """Readings that agree with the spec, minus whatever is overridden."""
        out = []
        for shot in self.film.shots:
            state = dict(shot.continuity)
            state.update(overrides.get(shot.id, {}))
            out.append(reading(shot.id, state))
        return out

    def test_a_reader_that_saw_the_film_scores_perfect(self):
        result = score.score(self.film, report(self.declared(), self.film.expected_breaks))
        self.assertTrue(result.perfect)
        self.assertEqual(2, len(result.hits))
        self.assertEqual((), result.misses)
        self.assertEqual((), result.false_alarms)
        self.assertEqual(15, len(result.counted(score.AGREED)))

    def test_a_missed_break_is_a_miss_and_not_a_pass(self):
        found = [b for b in self.film.expected_breaks if b.attribute == "jacket"]
        result = score.score(self.film, report(self.declared(), found))
        self.assertFalse(result.perfect)
        self.assertEqual(1, len(result.hits))
        self.assertEqual(["parcel"], [b.attribute for b in result.misses])

    def test_an_invented_break_is_a_false_alarm(self):
        invented = Break(shot="s02", attribute="jacket", before="red", after="green")
        result = score.score(self.film, report(self.declared(), list(self.film.expected_breaks) + [invented]))
        self.assertFalse(result.perfect)
        self.assertEqual(2, len(result.hits))
        self.assertEqual(["s02"], [b.shot for b in result.false_alarms])

    def test_the_right_shot_with_the_wrong_values_is_a_near_miss(self):
        # Right place, wrong reading. Counted against both totals and named on
        # its own, because "saw something here" and "read it correctly" fail for
        # different reasons and are fixed in different places.
        wrong = Break(shot="s03", attribute="jacket", before="red", after="green")
        keep = [b for b in self.film.expected_breaks if b.attribute != "jacket"]
        result = score.score(self.film, report(self.declared(), keep + [wrong]))
        self.assertFalse(result.perfect)
        self.assertEqual(1, len(result.near_misses))
        self.assertEqual("blue", result.near_misses[0].expected.after)
        self.assertEqual("green", result.near_misses[0].found.after)
        # Not double-counted anywhere else.
        self.assertEqual((), result.misses)
        self.assertEqual((), result.false_alarms)
        self.assertEqual(2, result.expected)
        self.assertEqual(2, result.found)

    def test_a_cell_read_wrongly_is_named_even_with_the_breaks_right(self):
        readings = self.declared(s05={"time_of_day": "dusk"})
        result = score.score(self.film, report(readings, self.film.expected_breaks))
        self.assertFalse(result.perfect)
        misread = result.counted(score.MISREAD)
        self.assertEqual([("s05", "time_of_day", "night", "dusk")],
                         [(c.shot, c.attribute, c.declared, c.read) for c in misread])

    def test_a_checker_that_goes_quiet_does_not_score_as_clean(self):
        # The stated risk on this idea is detection quality on subtle breaks. A
        # checker that declines to answer must not be graded as though it did.
        readings = list(self.declared())
        readings[1] = reading("s02", {"jacket": "red"}, unanswered=["parcel"],
                              disputed={"time_of_day": ("dusk", "night")})
        result = score.score(self.film, report(readings, self.film.expected_breaks))
        self.assertFalse(result.perfect)
        self.assertEqual([("s02", "parcel")], [(c.shot, c.attribute) for c in result.counted(score.UNANSWERED)])
        self.assertEqual([("s02", "time_of_day")], [(c.shot, c.attribute) for c in result.counted(score.DISPUTED)])

    def test_the_legitimate_change_is_not_scored_as_a_break(self):
        # dusk -> night at s04 is the story. It is in every reading above and
        # never appears as a finding, which is the "flags nothing it should not"
        # half of the claim.
        result = score.score(self.film, report(self.declared(), self.film.expected_breaks))
        self.assertNotIn("time_of_day", [b.attribute for b in result.hits])
        self.assertEqual((), result.false_alarms)

    def test_the_written_score_names_what_went_wrong(self):
        invented = Break(shot="s02", attribute="jacket", before="red", after="green")
        data = score.score(self.film, report(self.declared(), [invented])).to_dict()
        self.assertFalse(data["perfect"])
        self.assertEqual(2, len(data["misses"]))
        self.assertEqual("s02", data["false_alarms"][0]["shot"])


class StalenessTests(unittest.TestCase):
    """A report can outlive the film it judged, and that is exactly the demo."""

    def test_a_shot_rendered_after_the_report_is_reported_stale(self):
        film = spec.load(ROOT / "film.yaml")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "shots").mkdir()
            for shot in film.shots:
                (out / "shots" / f"{shot.id}-{shot.slug}.mp4").write_bytes(b"")
            # The report predates every file above.
            old = report([], [], at="2020-01-01T00:00:00+00:00")
            self.assertEqual(tuple(s.id for s in film.shots), score.stale_shots(film, out, old))

    def test_a_report_newer_than_the_film_is_not_stale(self):
        film = spec.load(ROOT / "film.yaml")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            (out / "shots").mkdir()
            for shot in film.shots:
                (out / "shots" / f"{shot.id}-{shot.slug}.mp4").write_bytes(b"")
            fresh = report([], [], at="2099-01-01T00:00:00+00:00")
            self.assertEqual((), score.stale_shots(film, out, fresh))


class FixesTests(unittest.TestCase):
    """A repair is a layer over the spec, and the spec keeps its planted breaks."""

    def setUp(self):
        self.film = spec.load(ROOT / "film.yaml")

    def test_a_repair_is_read_off_the_finding(self):
        # `before` is what the bible asked for, so the repair needs no second
        # source of truth — which is why the checker must name it.
        self.assertEqual(
            {"s03": {"jacket": "red"}, "s04": {"parcel": "present"}},
            fixes.corrections(self.film.expected_breaks),
        )

    def test_fixes_survive_a_round_trip_and_can_be_undone(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual({}, fixes.load(tmp))
            self.assertFalse(fixes.clear(tmp))
            fixes.save(tmp, {"s03": {"jacket": "red"}}, note="from a test")
            self.assertEqual({"s03": {"jacket": "red"}}, fixes.load(tmp))
            self.assertTrue(fixes.clear(tmp))
            self.assertEqual({}, fixes.load(tmp))

    def test_merging_keeps_earlier_repairs_on_other_cells(self):
        merged = fixes.merge({"s03": {"jacket": "red"}}, {"s03": {"parcel": "present"}, "s04": {"parcel": "present"}})
        self.assertEqual({"jacket": "red", "parcel": "present"}, merged["s03"])
        self.assertEqual({"s04": {"parcel": "present"}}, {"s04": merged["s04"]})

    def test_a_fixed_film_has_the_repair_and_no_answer_key_entry(self):
        fixed = spec.load(ROOT / "film.yaml", fixes={"s03": {"jacket": "red"}})
        self.assertEqual("red", fixed.shot("s03").continuity["jacket"])
        self.assertEqual(["parcel"], [b.attribute for b in fixed.expected_breaks])
        # The file on disk is untouched: the fixture keeps its planted breaks.
        self.assertEqual("blue", spec.load(ROOT / "film.yaml").shot("s03").continuity["jacket"])

    def test_repairing_everything_leaves_a_clean_film(self):
        fixed = spec.load(ROOT / "film.yaml", fixes=fixes.corrections(self.film.expected_breaks))
        self.assertEqual([], fixed.expected_breaks)

    def test_a_repair_that_moves_the_shot_re_renders_only_that_shot(self):
        fixed = spec.load(ROOT / "film.yaml", fixes={"s03": {"jacket": "red"}})
        before = {s.id: s.key() for s in self.film.shots}
        after = {s.id: s.key() for s in fixed.shots}
        self.assertNotEqual(before["s03"], after["s03"])
        self.assertEqual(
            [s for s in before if s != "s03"],
            [s for s in before if before[s] == after[s]],
        )

    def test_a_repair_that_creates_a_new_break_is_refused(self):
        # Fixing s03 to green would satisfy nothing: the loader derives the
        # breaks again over the repaired film and finds one the key does not
        # have. Without this, a fix could make a film worse in silence.
        with self.assertRaises(spec.SpecError) as caught:
            spec.load(ROOT / "film.yaml", fixes={"s03": {"jacket": "green"}})
        self.assertIn("expected_breaks does not match", str(caught.exception))

    def test_a_repair_naming_something_that_is_not_there_is_refused(self):
        for bad, message in (
            ({"s99": {"jacket": "red"}}, "not a shot"),
            ({"s03": {"hat": "red"}}, "not tracked"),
            ({"s03": {"jacket": "tartan"}}, "not one of"),
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(spec.SpecError) as caught:
                    spec.load(ROOT / "film.yaml", fixes=bad)
                self.assertIn(message, str(caught.exception))

    def test_a_fixes_file_that_is_not_one_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            fixes.path(tmp).write_text('{"shots": "s03"}')
            with self.assertRaises(ValueError):
                fixes.load(tmp)


class ReportRoundTripTests(unittest.TestCase):
    """`score` and `fix` read the report off disk, so it has to come back whole."""

    def test_a_written_report_reads_back_the_same(self):
        original = report(
            [
                reading("s01", {"jacket": "red"}),
                reading("s02", {}, unanswered=["jacket"], disputed={"parcel": ("present", "absent")}),
            ],
            [Break(shot="s03", attribute="jacket", before="red", after="blue", rule="constant")],
        )
        with tempfile.TemporaryDirectory() as tmp:
            original.write(tmp)
            back = check.read(tmp)
        self.assertEqual(original.breaks, back.breaks)
        self.assertEqual("constant", back.breaks[0].rule)
        self.assertEqual(("jacket",), back.readings[1].unanswered)
        self.assertEqual(("present", "absent"), back.readings[1].disputed["parcel"])
        self.assertEqual(original.at, back.at)

    def test_a_missing_report_says_which_command_to_run(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(ValueError) as caught:
                check.read(tmp)
        self.assertIn("cinema check", str(caught.exception))


class PlateTests(unittest.TestCase):
    """The before/after picture Joe asked for."""

    def still(self, path, colour):
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi",
             "-i", f"color=c={colour}:s=160x90", "-frames:v", "1", str(path)],
            check=True,
        )
        return path

    def test_the_plate_is_both_frames_side_by_side(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            before = self.still(tmp / "before.png", "blue")
            after = self.still(tmp / "after.png", "red")
            made = compare.plate(before, after, tmp / "plate.png", left="before", right="after")
            self.assertTrue(made.exists())
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height", "-of", "csv=p=0", str(made)],
                capture_output=True, text=True, check=True,
            )
            width, height = (int(n) for n in probe.stdout.strip().split(","))
            # Two frames wide, plus the gutter, and taller than one by the label bar.
            self.assertGreater(width, height)
            self.assertEqual(2 * (compare.PLATE_HEIGHT * 16 // 9) + 2 * compare.GUTTER, width)

    def test_a_frame_that_is_not_there_is_refused(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            before = self.still(tmp / "before.png", "blue")
            with self.assertRaises(compare.PlateError):
                compare.plate(before, tmp / "gone.png", tmp / "plate.png", left="a", right="b")


if __name__ == "__main__":
    unittest.main()
