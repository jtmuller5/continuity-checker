"""What the shot bible has to guarantee before the checker is worth writing.

Three things, and they are the three the checker depends on:

  * a rule that tells a story change from a mistake — the light going from dusk
    to night is not a continuity break, and a checker that says it is finds
    nothing useful in a film where the sun sets;
  * a vocabulary, so 'crimson' and 'red' are one value rather than two;
  * one judgement function, run over the declared state to make the answer key
    and over the observed state to make the finding. If those were two
    functions, the score would measure the difference between them.
"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cinema import bible as bible_mod, spec  # noqa: E402


def load_variant(old: str, new: str):
    """The shipped spec with one piece of text swapped, loaded."""
    source = (ROOT / "film.yaml").read_text()
    assert old in source, f"the spec no longer contains {old!r}"
    source = source.replace(old, new, 1)
    with tempfile.NamedTemporaryFile("w", suffix=".yaml") as fh:
        fh.write(source)
        fh.flush()
        return spec.load(fh.name)


def bible_of(attributes, characters=None, props=None):
    return bible_mod.load(
        {
            "characters": characters or [],
            "props": props or [],
            "attributes": attributes,
        }
    )


JACKET = {
    "name": "jacket",
    "rule": "constant",
    "canon": "red",
    "values": ["red", "blue"],
    "question": "What colour is the jacket?",
    "describe": "a {value} jacket",
    "synonyms": {"red": ["crimson"]},
}

LIGHT = {
    "name": "light",
    "rule": "progressive",
    "canon": "dusk",
    "order": ["day", "dusk", "night"],
    "question": "Dawn, day, dusk or night?",
    "describe": "shot at {value}",
}


class ShippedBibleTests(unittest.TestCase):
    def setUp(self):
        self.film = spec.load(ROOT / "film.yaml")

    def test_the_bible_names_the_attributes(self):
        self.assertEqual(self.film.continuity_attributes, self.film.bible.names)
        for shot in self.film.shots:
            for name in self.film.bible.names:
                self.assertIn(name, shot.continuity, shot.id)

    def test_the_answer_key_is_what_the_shots_declare(self):
        derived = bible_mod.derive_breaks(self.film.bible, self.film.states())
        self.assertEqual(derived, self.film.expected_breaks)

    def test_the_sunset_is_not_a_break(self):
        # s03 -> s04 goes dusk to night. A constant rule would report it, and a
        # checker that reports the story is worse than none.
        found = [b.attribute for b in bible_mod.derive_breaks(self.film.bible, self.film.states())]
        self.assertNotIn("time_of_day", found)

    def test_a_drifted_answer_key_is_refused(self):
        # Un-plant the jacket break and leave the key claiming it. Nothing else
        # in the pipeline would notice, and the checker would be scored against
        # a film that is not on disk.
        with self.assertRaises(spec.SpecError) as caught:
            load_variant("jacket: blue", "jacket: red")
        self.assertIn("expected_breaks", str(caught.exception))

    def test_the_prompt_carries_the_continuity_it_will_be_checked_on(self):
        s03 = self.film.shot("s03")
        self.assertIn("blue", s03.text)
        self.assertIn(self.film.shot("s03").prompt, s03.text)

    def test_a_subject_that_is_not_in_the_shot_is_not_described(self):
        # s04 asks for no parcel. Describing the parcel in the same prompt is
        # how you get a parcel.
        self.assertNotIn("tied once with pale string", self.film.shot("s04").text)
        self.assertIn("tied once with pale string", self.film.shot("s05").text)

    def test_the_shot_key_follows_the_bible_and_not_only_the_author_line(self):
        before = self.film.shot("s01").key()
        after = load_variant(
            "the courier wears a zipped {value} cycling jacket",
            "the courier wears a {value} anorak",
        ).shot("s01").key()
        self.assertNotEqual(before, after)


class VocabularyTests(unittest.TestCase):
    def test_a_synonym_and_stray_punctuation_reach_the_same_value(self):
        jacket = bible_of([JACKET]).attribute("jacket")
        for answer in ("red", "Red", " CRIMSON. ", "crimson"):
            self.assertEqual(jacket.normalise(answer), "red", answer)

    def test_a_word_the_bible_never_offered_is_not_an_answer(self):
        # None means "the frame was described in words we did not plan for",
        # which is a question for the author. Reading it as agreement would
        # silently pass every frame the model was unsure about.
        jacket = bible_of([JACKET]).attribute("jacket")
        self.assertIsNone(jacket.normalise("teal"))
        self.assertIsNone(jacket.normalise(None))
        self.assertEqual(bible_of([JACKET]).read({"jacket": "teal"}), {})

    def test_a_word_that_would_mean_two_things_is_refused(self):
        entry = dict(JACKET, synonyms={"red": ["dark"], "blue": ["dark"]})
        with self.assertRaises(bible_mod.BibleError):
            bible_of([entry])


class RuleTests(unittest.TestCase):
    def states(self, *values, name="jacket"):
        return [(f"s{i:02d}", {name: v}) for i, v in enumerate(values, start=1)]

    def test_a_constant_attribute_breaks_against_canon_and_not_its_neighbour(self):
        # Two wrong shots in a row are two breaks, not one. Both were rendered
        # wrong and both have to be re-rendered.
        found = bible_mod.derive_breaks(bible_of([JACKET]), self.states("red", "blue", "blue"))
        self.assertEqual([b.shot for b in found], ["s02", "s03"])
        self.assertEqual((found[0].before, found[0].after), ("red", "blue"))

    def test_a_progressive_attribute_may_advance_but_not_go_back(self):
        forward = bible_mod.derive_breaks(bible_of([LIGHT]), self.states("dusk", "night", name="light"))
        self.assertEqual(forward, [])
        backward = bible_mod.derive_breaks(
            bible_of([LIGHT]), self.states("dusk", "night", "dusk", name="light")
        )
        self.assertEqual([(b.shot, b.before, b.after) for b in backward], [("s03", "night", "dusk")])

    def test_a_declared_change_is_the_story_and_what_follows_it_is_the_new_truth(self):
        entry = dict(JACKET, rule="declared", changes_at={"s02": "blue"})
        found = bible_mod.derive_breaks(bible_of([entry]), self.states("red", "blue", "blue", "red"))
        self.assertEqual([(b.shot, b.before, b.after) for b in found], [("s04", "blue", "red")])

    def test_an_unanswered_question_is_not_a_break(self):
        found = bible_mod.derive_breaks(bible_of([JACKET]), [("s01", {}), ("s02", {"jacket": "red"})])
        self.assertEqual(found, [])

    def test_a_value_outside_the_vocabulary_raises_rather_than_reporting(self):
        with self.assertRaises(bible_mod.BibleError):
            bible_mod.derive_breaks(bible_of([JACKET]), self.states("red", "teal"))

    def test_the_same_function_judges_what_gemini_says(self):
        # The checker's path: prose answers -> read() -> derive_breaks. It has
        # to reach the same verdict as the declared state does.
        bible = bible_of([JACKET])
        observed = [
            ("s01", bible.read({"jacket": "Crimson"})),
            ("s02", bible.read({"jacket": "navy blue"})),
        ]
        self.assertEqual(observed[1][1], {})  # 'navy blue' is not a synonym here
        observed[1] = ("s02", bible.read({"jacket": "blue"}))
        found = bible_mod.derive_breaks(bible, observed)
        self.assertEqual([b.sentence() for b in found], ["s02: jacket was red, is blue"])


class MalformedBibleTests(unittest.TestCase):
    """Each of these would produce a check that runs and means nothing."""

    def refuses(self, entry):
        with self.assertRaises(bible_mod.BibleError):
            bible_of([entry])

    def test_an_attribute_with_no_question_cannot_be_asked_about(self):
        self.refuses({k: v for k, v in JACKET.items() if k != "question"})

    def test_an_attribute_with_no_description_cannot_reach_the_prompt(self):
        self.refuses({k: v for k, v in JACKET.items() if k != "describe"})

    def test_a_template_that_describes_every_value_the_same_way_is_refused(self):
        self.refuses(dict(JACKET, describe="a jacket"))

    def test_a_per_value_description_must_cover_every_value(self):
        self.refuses(dict(JACKET, describe={"red": "a red jacket"}))

    def test_a_canon_outside_the_values_is_refused(self):
        self.refuses(dict(JACKET, canon="green"))

    def test_a_single_valued_attribute_can_never_break(self):
        self.refuses(dict(JACKET, values=["red"], canon="red", synonyms={}))

    def test_a_progressive_attribute_needs_an_order(self):
        self.refuses({k: v for k, v in LIGHT.items() if k != "order"})

    def test_changes_at_belongs_only_to_a_declared_attribute(self):
        self.refuses(dict(JACKET, changes_at={"s02": "blue"}))

    def test_an_attribute_cannot_belong_to_a_subject_that_does_not_exist(self):
        self.refuses(dict(JACKET, subject="ghost"))

    def test_a_spec_whose_two_attribute_lists_disagree_is_refused(self):
        source = (ROOT / "film.yaml").read_text() + "\ncontinuity_attributes: [jacket]\n"
        with tempfile.NamedTemporaryFile("w", suffix=".yaml") as fh:
            fh.write(source)
            fh.flush()
            with self.assertRaises(spec.SpecError):
                spec.load(fh.name)


if __name__ == "__main__":
    unittest.main()
