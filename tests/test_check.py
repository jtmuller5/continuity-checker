"""What the checker has to be true of, for a finding to mean anything.

Four claims, and every test here belongs to one of them:

  * **It is not told the answer.** A reader is handed a question and the words
    it may use, and never the canon, the shot's declared state, or the answer
    key. A checker given the answer finds it.
  * **It may say it cannot tell.** An answer outside the vocabulary becomes an
    unanswered question, not agreement — otherwise a model that ignored the
    frame would score as a clean film.
  * **Frames that disagree are reported, not resolved.** Picking a majority of
    two hides both the break inside a shot and the checker that cannot see.
  * **It finds the planted breaks.** The end-to-end case runs the whole thing
    over a freshly rendered cut, and it costs nothing to run.

The Gemini reader is asserted on the shape of the request it builds, which is
all that can be asserted before Vertex AI access exists (#1008). It is not a
test of the API, and it will not catch a wrong endpoint.
"""

from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cinema import backends, check, frames, pricing, render, spec  # noqa: E402
from cinema.readers import gemini, pixels  # noqa: E402


def quiet(*_args, **_kwargs):
    pass


class RecordingReader:
    """A reader that answers from a script and remembers what it was shown."""

    name = "recording"
    bills = False

    def __init__(self, answers):
        # {shot_id: [{attribute: answer}, ...]} — one entry per frame.
        self.answers = answers
        self.seen = []

    def read(self, frame, questions, *, log=print, **_options):
        self.seen.append((frame, questions))
        return dict(self.answers[frame.shot_id][frame.index])


class FakeFrame:
    def __init__(self, shot_id, index):
        self.shot_id = shot_id
        self.index = index
        self.at = 2.0
        self.path = Path(f"{shot_id}-{index}.png")

    @property
    def label(self):
        return f"{self.shot_id}#{self.index}"


class OffsetTests(unittest.TestCase):
    def test_frames_are_spread_and_never_at_the_ends(self):
        got = frames.offsets(8, 2)
        self.assertEqual([2.0, 6.0], got)
        # The first and last frames of a generated shot are the ones most
        # likely to be a dissolve or the reference the next shot chains from.
        self.assertTrue(all(0 < t < 8 for t in got))

    def test_one_frame_lands_in_the_middle(self):
        self.assertEqual([4.0], frames.offsets(8, 1))

    def test_no_frames_is_refused(self):
        with self.assertRaises(frames.FrameError):
            frames.offsets(8, 0)

    def test_a_crop_outside_the_frame_is_refused(self):
        self.assertIsNone(frames._crop_filter(None))
        self.assertIn("crop=", frames._crop_filter((0.1, 0.8)))
        with self.assertRaises(frames.FrameError):
            frames._crop_filter((0.5, 0.8))


class ReconcileTests(unittest.TestCase):
    TRACKED = ["jacket"]

    def reconcile(self, states, attributes=None):
        return check.reconcile(states, attributes or self.TRACKED)

    def test_frames_that_agree_give_the_value(self):
        state, unanswered, disputed = self.reconcile([{"jacket": "red"}, {"jacket": "red"}])
        self.assertEqual({"jacket": "red"}, state)
        self.assertEqual((), unanswered)
        self.assertEqual({}, disputed)

    def test_frames_that_disagree_are_disputed_and_not_judged(self):
        state, _, disputed = self.reconcile([{"jacket": "red"}, {"jacket": "blue"}])
        # Not in the state at all: a value two frames contradict is not
        # evidence, and a break derived from it is a coin toss reported as a
        # finding.
        self.assertNotIn("jacket", state)
        self.assertEqual(("blue", "red"), disputed["jacket"])

    def test_a_majority_settles_it(self):
        state, _, disputed = self.reconcile(
            [{"jacket": "red"}, {"jacket": "blue"}, {"jacket": "red"}]
        )
        self.assertEqual("red", state["jacket"])
        self.assertEqual({}, disputed)

    def test_an_attribute_no_frame_answered_is_unanswered(self):
        state, unanswered, _ = self.reconcile([{"jacket": "red"}, {}])
        # One frame answering is still an answer; nothing answering is not.
        self.assertEqual({"jacket": "red"}, state)
        self.assertEqual((), unanswered)
        state, unanswered, _ = self.reconcile([{}, {}])
        self.assertEqual({}, state)
        # Named, not silent: an attribute nothing could answer must appear in
        # the report, or an unreadable shot reads as a clean one.
        self.assertEqual(("jacket",), unanswered)


class WithholdingTests(unittest.TestCase):
    """The reader must not be able to see the answer it is being scored on."""

    def setUp(self):
        self.film = spec.load(ROOT / "film.yaml")

    def test_a_question_offers_every_value_and_singles_none_out(self):
        for question in self.film.bible.questions():
            attribute = self.film.bible.attribute(question.attribute)
            self.assertEqual(tuple(attribute.values), question.values)
            # The canon is one of the values and must be indistinguishable
            # among them. A question may list its values ("dawn, day, dusk or
            # night?") — what it may not do is name the right one and not the
            # others, which is the shape of a leak.
            named = [v for v in attribute.values if v in question.text]
            self.assertIn(len(named), (0, len(attribute.values)))

    def test_a_question_carries_no_canon_or_declared_state(self):
        payload = json.dumps([q.__dict__ for q in self.film.bible.questions()])
        for word in ("canon", "expected", "should"):
            self.assertNotIn(word, payload.lower())
        for shot in self.film.shots:
            self.assertNotIn(shot.id, payload)


class GeminiRequestTests(unittest.TestCase):
    """The request shape. Unrun against the API until #1008 lands."""

    def setUp(self):
        self.questions = spec.load(ROOT / "film.yaml").bible.questions()

    def test_every_attribute_is_a_required_enum(self):
        schema = gemini.response_schema(self.questions)
        self.assertEqual(
            sorted(q.attribute for q in self.questions), sorted(schema["required"])
        )
        for question in self.questions:
            enum = schema["properties"][question.attribute]["enum"]
            self.assertEqual(list(question.values) + [gemini.UNCLEAR], enum)

    def test_the_model_can_say_it_cannot_tell(self):
        # And the word it says it with is outside the bible, so it normalises
        # to nothing rather than to one of the values.
        bible = spec.load(ROOT / "film.yaml").bible
        for question in self.questions:
            self.assertIsNone(bible.attribute(question.attribute).normalise(gemini.UNCLEAR))
        self.assertIn(gemini.UNCLEAR, gemini.prompt_text(self.questions))

    def test_the_prompt_offers_the_words_and_withholds_the_answer(self):
        text = gemini.prompt_text(self.questions)
        for question in self.questions:
            for value in question.values:
                self.assertIn(value, text)
        for word in ("canon", "continuity break", "expected_breaks"):
            self.assertNotIn(word, text)

    def test_it_refuses_clearly_without_a_project(self):
        with self.assertRaises(SystemExit):
            gemini._client(project="")


class CostTests(unittest.TestCase):
    def test_checking_a_film_costs_a_fraction_of_rendering_one_shot(self):
        one_shot = pricing.shot_cost(8, "standard", "1920x1080", audio=True)
        whole_film = pricing.check_cost(10)
        # The entry's own argument: catching a break is cheaper than the
        # re-render it saves, by a wide enough margin that never checking is
        # the expensive habit.
        self.assertLess(whole_film * 10, one_shot)

    def test_an_unpriced_model_is_refused_rather_than_guessed(self):
        with self.assertRaises(pricing.PricingError):
            pricing.check_cost(10, "gemini-9-imaginary")


class CheckerTests(unittest.TestCase):
    """The checker over a scripted reader: no ffmpeg, no film on disk."""

    def setUp(self):
        self.film = spec.load(ROOT / "film.yaml")
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)

    def run_check(self, answers, per_shot=2):
        reader = RecordingReader(answers)
        stills = [
            FakeFrame(shot.id, i) for shot in self.film.shots for i in range(per_shot)
        ]
        original = check.frames_mod.sample
        check.frames_mod.sample = lambda *a, **k: stills
        try:
            return reader, check.check_film(
                self.film, self.out, reader, per_shot=per_shot, log=quiet
            )
        finally:
            check.frames_mod.sample = original

    def truth(self, **overrides):
        """Every shot read exactly as it was declared, then edited."""
        answers = {
            shot.id: [dict(shot.continuity), dict(shot.continuity)]
            for shot in self.film.shots
        }
        for (shot_id, index), state in overrides.items():
            answers[shot_id][index].update(state)
        return answers

    def test_a_film_read_as_declared_finds_the_planted_breaks(self):
        _, report = self.run_check(self.truth())
        self.assertEqual(
            [(b.shot, b.attribute) for b in report.breaks],
            [(b.shot, b.attribute) for b in self.film.expected_breaks],
        )

    def test_a_synonym_is_the_same_value(self):
        # 'crimson' is what a model says; 'red' is what the bible calls it.
        answers = self.truth()
        answers["s01"] = [{"jacket": "crimson", "parcel": "yes", "time_of_day": "twilight"}] * 2
        _, report = self.run_check(answers)
        self.assertEqual("red", report.readings[0].state["jacket"])
        self.assertEqual("present", report.readings[0].state["parcel"])

    def test_a_word_outside_the_vocabulary_is_unanswered_not_agreement(self):
        answers = self.truth()
        answers["s03"] = [dict(a, jacket="unclear") for a in answers["s03"]]
        _, report = self.run_check(answers)
        s03 = report.readings[2]
        self.assertNotIn("jacket", s03.state)
        self.assertIn("jacket", s03.unanswered)
        # And it is not reported as a break: not knowing is not a finding.
        self.assertNotIn(("s03", "jacket"), [(b.shot, b.attribute) for b in report.breaks])

    def test_frames_of_one_shot_that_disagree_are_reported(self):
        answers = self.truth()
        answers["s02"][1]["jacket"] = "blue"
        _, report = self.run_check(answers)
        self.assertEqual(("blue", "red"), report.readings[1].disputed["jacket"])

    def test_the_sunset_is_the_story_and_not_a_break(self):
        # time_of_day is progressive: dusk -> night is what the film asks for,
        # and a checker that flags it reports nothing anyone can act on.
        _, report = self.run_check(self.truth())
        self.assertNotIn("time_of_day", [b.attribute for b in report.breaks])

    def test_the_light_going_backwards_is_a_break(self):
        answers = self.truth()
        answers["s05"] = [dict(a, time_of_day="dusk") for a in answers["s05"]]
        _, report = self.run_check(answers)
        self.assertIn(("s05", "time_of_day"), [(b.shot, b.attribute) for b in report.breaks])

    def test_the_reader_only_ever_sees_a_frame_and_the_questions(self):
        reader, _ = self.run_check(self.truth())
        names = [a.name for a in self.film.bible.attributes]
        for frame, questions in reader.seen:
            self.assertEqual(names, [q.attribute for q in questions])
            self.assertFalse(hasattr(frame, "continuity"))
            self.assertFalse(any(hasattr(q, "canon") for q in questions))

    def test_a_clean_film_reports_nothing(self):
        answers = {
            shot.id: [
                {"jacket": "red", "parcel": "present", "time_of_day": shot.continuity["time_of_day"]}
            ] * 2
            for shot in self.film.shots
        }
        _, report = self.run_check(answers)
        self.assertEqual([], list(report.breaks))

    def test_the_report_writes_what_a_score_needs(self):
        _, report = self.run_check(self.truth())
        path = report.write(self.out)
        data = json.loads(path.read_text())
        self.assertEqual("recording", data["reader"])
        self.assertEqual(0.0, data["cost_usd"])
        self.assertEqual(len(self.film.shots), len(data["shots"]))
        self.assertEqual(
            [("s03", "jacket"), ("s04", "parcel")],
            [(b["shot"], b["attribute"]) for b in data["breaks"]],
        )
        self.assertEqual(["red", "present"], [b["expected"] for b in data["breaks"]])

    def test_a_spec_with_no_bible_cannot_be_checked(self):
        film = spec.load(ROOT / "film.yaml")
        object.__setattr__(film, "bible", type(film.bible)())
        with self.assertRaises(ValueError):
            check.check_film(film, self.out, RecordingReader({}), log=quiet)


class EndToEndTests(unittest.TestCase):
    """Render the cut and read it back, with no credential and no network."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        cls.film = spec.load(ROOT / "film.yaml")
        backend = backends.get("placeholder")
        config = render.RenderConfig.build(cls.film, backend.name)
        render.render_film(cls.film, backend, config, cls.out, log=quiet)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_pixel_reader_finds_both_planted_breaks_and_nothing_else(self):
        report = check.check_film(self.film, self.out, pixels, log=quiet)
        self.assertEqual(
            [(b.shot, b.attribute, b.before, b.after) for b in report.breaks],
            [(b.shot, b.attribute, b.before, b.after) for b in self.film.expected_breaks],
        )

    def test_every_question_was_answered_by_the_frames(self):
        report = check.check_film(self.film, self.out, pixels, log=quiet)
        for reading in report.readings:
            self.assertEqual((), reading.unanswered)
            self.assertEqual({}, reading.disputed)

    def test_reading_a_shot_that_was_never_rendered_says_so(self):
        with tempfile.TemporaryDirectory() as empty:
            with self.assertRaises(frames.FrameError) as caught:
                check.check_film(self.film, empty, pixels, log=quiet)
            self.assertIn("build", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
