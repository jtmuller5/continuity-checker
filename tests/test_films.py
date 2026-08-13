"""The second fixture film, and the thing that makes a second film possible.

One film with one pair of breaks is one example. A checker that has only ever
been run against a single example is indistinguishable from a checker with that
example's answer written into it, which is exactly the objection a judge should
raise — so `film-lighthouse.yaml` breaks in two ways `film.yaml` cannot, and
the tests here are about those two ways rather than about the checker again.

They also hold the line that lets the second film exist at all: the free
renderer and the free reader sort an attribute by the words it offers and never
by its name. Rename the subject and both keep working, or neither does.

Everything here runs offline and costs nothing.
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cinema import bible as bible_mod, spec, vocab  # noqa: E402
from cinema.backends import placeholder  # noqa: E402
from cinema.readers import pixels  # noqa: E402

FIRST = ROOT / "film.yaml"
SECOND = ROOT / "film-lighthouse.yaml"


def rgb(hexed: str) -> tuple:
    value = int(hexed.replace("0x", ""), 16)
    return ((value >> 16) & 255, (value >> 8) & 255, value & 255)


class TheSecondFilmTests(unittest.TestCase):
    """What it is here to prove, stated as the two rules it exercises."""

    @classmethod
    def setUpClass(cls):
        cls.film = spec.load(SECOND)

    def test_the_light_going_backwards_is_a_break_and_the_sunset_is_not(self):
        """A constant rule would flag the sunset and miss the mistake."""
        light = self.film.bible.attribute("light")
        self.assertEqual("progressive", light.rule)
        forward = [(s.id, s.continuity["light"]) for s in self.film.shots]
        self.assertIn(("s03", "night"), forward, "the light has to move for this to mean anything")
        found = [b for b in self.film.expected_breaks if b.attribute == "light"]
        self.assertEqual([("s05", "night", "dusk")], [(b.shot, b.before, b.after) for b in found])

    def test_a_change_the_bible_declared_is_not_reported(self):
        """The lamp is lit from s04 because the author said so. Silence is correct."""
        lamp = self.film.bible.attribute("lamp")
        self.assertEqual({"s04": "lit"}, lamp.changes_at)
        self.assertEqual("unlit", self.film.shot("s03").continuity["lamp"])
        self.assertEqual("lit", self.film.shot("s04").continuity["lamp"])
        self.assertEqual([], [b for b in self.film.expected_breaks if b.attribute == "lamp"])

    def test_the_answer_key_is_derived_from_the_shots_and_not_typed(self):
        """`spec.load` refuses a drifted key. Prove the derivation agrees here."""
        derived = bible_mod.derive_breaks(self.film.bible, self.film.states())
        self.assertEqual(
            [(b.shot, b.attribute, b.before, b.after) for b in derived],
            [(b.shot, b.attribute, b.before, b.after) for b in self.film.expected_breaks],
        )

    def test_it_breaks_differently_from_the_first_film(self):
        """Two films with the same two breaks would be one example twice over."""
        def broken(film):
            # The rule lives on the derived break, not on the key as written.
            return {
                (b.attribute, b.rule)
                for b in bible_mod.derive_breaks(film.bible, film.states())
            }

        first, second = broken(spec.load(FIRST)), broken(self.film)
        self.assertEqual(set(), first & second)
        self.assertIn("progressive", {rule for _, rule in second})


class VocabularyDispatchTests(unittest.TestCase):
    """The renderer draws, and the reader reads, by vocabulary — never by name."""

    def test_the_three_kinds_are_told_apart_by_the_words_on_offer(self):
        self.assertEqual("presence", vocab.kind(["lit", "unlit"]))
        self.assertEqual("presence", vocab.kind(["present", "absent"]))
        self.assertEqual("light", vocab.kind(["dawn", "day", "dusk", "night"]))
        self.assertEqual("colour", vocab.kind(["red", "blue", "green"]))
        self.assertEqual("", vocab.kind(["allegro", "andante"]))

    def test_a_yes_no_pair_needs_exactly_one_word_of_each(self):
        self.assertEqual(("lit", "unlit"), vocab.presence_pair(["lit", "unlit"]))
        self.assertIsNone(vocab.presence_pair(["yes", "present", "no"]))
        self.assertIsNone(vocab.presence_pair(["red", "blue"]))

    def test_the_second_films_shots_are_drawn_from_its_own_attribute_names(self):
        film = spec.load(SECOND)
        first = placeholder.drawing(film.shot("s01"), film)
        self.assertEqual(placeholder.BACKGROUND["dusk"], first["background"])
        self.assertEqual(placeholder.JACKET["green"], first["subject"])
        self.assertFalse(first["prop"], "the lamp is unlit in s01, so nothing is drawn")

        lamproom = placeholder.drawing(film.shot("s04"), film)
        self.assertEqual(placeholder.BACKGROUND["night"], lamproom["background"])
        self.assertTrue(lamproom["prop"], "the lamp is lit from s04")

        broken = placeholder.drawing(film.shot("s02"), film)
        self.assertEqual(placeholder.JACKET["yellow"], broken["subject"])

    def test_a_film_that_names_nothing_the_way_either_film_does_still_draws(self):
        """The dispatch is on the words, so invented names have to work."""
        raw = {
            "title": "Invented",
            "bible": {
                "attributes": [
                    {"name": "poncho", "canon": "red", "values": ["red", "blue"],
                     "question": "What colour is the poncho?",
                     "describe": "a {value} poncho"},
                    {"name": "umbrella", "canon": "yes", "values": ["yes", "no"],
                     "question": "Is the umbrella up?", "describe": {"yes": "up", "no": "down"}},
                    {"name": "sky", "rule": "progressive", "canon": "day",
                     "order": ["day", "dusk"], "question": "Day or dusk?",
                     "describe": "at {value}"},
                ]
            },
            "shots": [{
                "id": "s01", "seconds": 8, "prompt": "A street.",
                "continuity": {"poncho": "blue", "umbrella": "yes", "sky": "dusk"},
            }],
        }
        import tempfile

        import yaml
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invented.yaml"
            path.write_text(yaml.safe_dump(raw))
            film = spec.load(path)
        drawn = placeholder.drawing(film.shot("s01"), film)
        self.assertEqual(placeholder.BACKGROUND["dusk"], drawn["background"])
        self.assertEqual(placeholder.JACKET["blue"], drawn["subject"])
        self.assertTrue(drawn["prop"])

    def test_every_colour_the_renderer_draws_reads_back_as_itself(self):
        """The drawer and the reader keep their own swatches. They have to agree."""
        allowed = sorted(placeholder.JACKET)
        for word, hexed in sorted(placeholder.JACKET.items()):
            with self.subTest(colour=word):
                self.assertEqual(word, pixels._nearest(rgb(hexed), allowed))

    def test_the_light_ladder_reads_back_as_itself_too(self):
        allowed = sorted(placeholder.BACKGROUND)
        for word, hexed in sorted(placeholder.BACKGROUND.items()):
            with self.subTest(light=word):
                self.assertEqual(word, pixels._light_value(rgb(hexed), allowed))


if __name__ == "__main__":
    unittest.main()
