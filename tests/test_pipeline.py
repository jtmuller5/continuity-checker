"""What the rendered file has to be, not what the spec says it should be.

The placeholder cut is the fixture the continuity checker is scored against, so
the two things it must get right are the two asserted here: the shot is video
and not a still, and the continuity state is visible in the pixels.

Both of these have already been wrong once. drawbox's `t` is thickness rather
than the timestamp, so the motion expression evaluated to the fill sentinel:
the figure froze at the left edge and the parcel went off-frame entirely. The
render succeeded, ffprobe reported 8 seconds and 192 frames, and every check
short of looking at a pixel passed.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cinema import assemble, spec  # noqa: E402
from cinema.backends import placeholder  # noqa: E402

def rgb(colour: str):
    """'0xc0392b' as a triple. Derived from the renderer's own table, never copied."""
    value = int(colour, 16)
    return (value >> 16 & 0xFF, value >> 8 & 0xFF, value & 0xFF)


PARCEL_RGB = rgb(placeholder.PARCEL)


def frame_rgb(path, at_seconds):
    """One frame as raw RGB triples."""
    raw = subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error",
            "-ss", str(at_seconds), "-i", str(path),
            "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-",
        ],
        check=True, capture_output=True,
    ).stdout
    return [tuple(raw[i:i + 3]) for i in range(0, len(raw), 3)]


def _matches(pixels, target, tolerance=12):
    return [
        i for i, p in enumerate(pixels)
        if all(abs(p[c] - target[c]) <= tolerance for c in range(3))
    ]


def count_near(pixels, target, tolerance=12):
    return len(_matches(pixels, target, tolerance))


def centroid_x(pixels, target, width, tolerance=12):
    """Mean column of the pixels matching `target`, or None if there are none."""
    hits = _matches(pixels, target, tolerance)
    if not hits:
        return None
    return sum(i % width for i in hits) / len(hits)


class SpecTests(unittest.TestCase):
    def test_the_shipped_spec_loads(self):
        film = spec.load(ROOT / "film.yaml")
        self.assertEqual(len(film.shots), 5)
        self.assertEqual(film.seconds, 40)
        self.assertEqual(len(film.expected_breaks), 2)

    def test_every_shot_is_eight_seconds(self):
        film = spec.load(ROOT / "film.yaml")
        for shot in film.shots:
            self.assertEqual(shot.seconds, spec.SHOT_SECONDS, shot.id)

    def test_a_shot_that_could_never_be_re_rendered_is_refused(self):
        # Veo reference-image-to-video is 8s only, so a 6s shot kills the demo.
        source = (ROOT / "film.yaml").read_text().replace(
            "    seconds: 8", "    seconds: 6", 1
        )
        with tempfile.NamedTemporaryFile("w", suffix=".yaml") as fh:
            fh.write(source)
            fh.flush()
            with self.assertRaises(spec.SpecError):
                spec.load(fh.name)

    def test_the_answer_key_cannot_name_a_shot_that_is_gone(self):
        source = (ROOT / "film.yaml").read_text().replace("shot: s03", "shot: s99", 1)
        with tempfile.NamedTemporaryFile("w", suffix=".yaml") as fh:
            fh.write(source)
            fh.flush()
            with self.assertRaises(spec.SpecError):
                spec.load(fh.name)

    def test_a_shot_key_follows_its_prompt(self):
        film = spec.load(ROOT / "film.yaml")
        first = film.shot("s01")
        same = spec.Shot(
            first.id, first.slug, first.seconds, first.prompt,
            dict(first.continuity), first.generation_prompt,
        )
        changed = spec.Shot(
            first.id, first.slug, first.seconds, "different",
            dict(first.continuity), "different, with its continuity",
        )
        self.assertEqual(first.key(), same.key())
        self.assertNotEqual(first.key(), changed.key())


class RenderTests(unittest.TestCase):
    """These render for real. It is ffmpeg drawing boxes, so it is free and fast."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name)
        cls.film = spec.load(ROOT / "film.yaml")
        cls.shots = {}
        for shot_id in ("s01", "s04"):
            shot = cls.film.shot(shot_id)
            path = cls.out / f"{shot_id}.mp4"
            placeholder.render(shot, cls.film, path, log=lambda *_: None)
            cls.shots[shot_id] = path

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_figure_travels_across_the_frame(self):
        # Not "the frames differ": the parcel moving on its own satisfies that
        # even with the figure frozen at the left edge, which is exactly the
        # bug. Track where the jacket colour actually is.
        jacket = rgb(placeholder.JACKET[self.film.shot("s01").continuity["jacket"]])
        width = self.film.width
        early = centroid_x(frame_rgb(self.shots["s01"], 0.5), jacket, width)
        late = centroid_x(frame_rgb(self.shots["s01"], 7.0), jacket, width)
        self.assertIsNotNone(early, "no jacket-coloured pixels at 0.5s")
        self.assertIsNotNone(late, "no jacket-coloured pixels at 7.0s")
        self.assertGreater(
            late - early, width * 0.4,
            f"the figure sat at {early:.0f}px and {late:.0f}px of {width} — "
            "the overlay is not evaluating its x per frame",
        )

    def test_the_parcel_is_in_frame_when_the_spec_says_present(self):
        self.assertEqual(self.film.shot("s01").continuity["parcel"], "present")
        pixels = frame_rgb(self.shots["s01"], 4.0)
        self.assertGreater(
            count_near(pixels, PARCEL_RGB), 20,
            "no parcel-coloured pixels in a shot that carries the parcel",
        )

    def test_the_parcel_is_gone_when_the_spec_says_absent(self):
        self.assertEqual(self.film.shot("s04").continuity["parcel"], "absent")
        pixels = frame_rgb(self.shots["s04"], 4.0)
        self.assertLess(
            count_near(pixels, PARCEL_RGB), 20,
            "the planted parcel break is not visible: the checker fixture has no break to catch",
        )

    def test_the_jacket_break_is_a_different_colour_on_screen(self):
        # s03 is the planted jacket break. It has to differ in pixels, or the
        # checker is being scored against a break that was never drawn.
        s03 = self.out / "s03.mp4"
        placeholder.render(self.film.shot("s03"), self.film, s03, log=lambda *_: None)
        red = frame_rgb(self.shots["s01"], 4.0)
        blue = frame_rgb(s03, 4.0)
        differing = sum(1 for a, b in zip(red, blue) if a != b)
        self.assertGreater(differing, len(red) * 0.02, "s03 looks the same as s01")

    def test_the_assembled_cut_is_the_length_the_spec_promises(self):
        paths = []
        for shot in self.film.shots:
            path = self.out / f"cut-{shot.id}.mp4"
            placeholder.render(shot, self.film, path, log=lambda *_: None)
            paths.append(path)
        cut = assemble.concat(paths, self.out / "cut.mp4", log=lambda *_: None)
        facts = assemble.probe(cut)
        self.assertAlmostEqual(facts["seconds"], self.film.seconds, delta=0.5)
        self.assertEqual(facts["width"], self.film.width)
        self.assertEqual(facts["frames"], self.film.fps * self.film.seconds)


class BillingTests(unittest.TestCase):
    def test_the_backend_that_spends_money_refuses_to_run(self):
        from cinema.backends import veo

        self.assertTrue(veo.bills)
        self.assertFalse(placeholder.bills)
        with self.assertRaises(NotImplementedError):
            veo.render(None, None, None)

    def test_the_cli_will_not_reach_a_billing_backend_without_the_flag(self):
        from cinema import cli

        with self.assertRaises(SystemExit) as caught:
            cli.main(["--spec", str(ROOT / "film.yaml"), "render", "--backend", "veo"])
        self.assertIn("$0.00", str(caught.exception))


if __name__ == "__main__":
    unittest.main()
