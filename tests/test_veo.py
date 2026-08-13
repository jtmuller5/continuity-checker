"""What would be sent to Veo, asserted without sending it.

The Gen AI SDK is not installed here and Vertex AI access is task #1008, so
there is no call to make. What can be tested is everything that decides what the
call costs and whether the film comes out continuous: the model the tier picks,
the eight seconds, the prompt being the composed one rather than the author's
line, the seed, the reference frame, and the rewriter being off.

This is the same split `tests/test_check.py` makes for the Gemini reader. It is
a test of shape and of refusals, not of the API — the first real call is the
thing that proves the rest, and it has not happened.
"""

from __future__ import annotations

import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cinema import pricing, render, spec  # noqa: E402
from cinema.backends import veo  # noqa: E402


class RequestTests(unittest.TestCase):
    def setUp(self):
        self.film = spec.load(ROOT / "film.yaml")
        self.shot = self.film.shot("s03")

    def config(self, **overrides):
        return render.RenderConfig.build(self.film, "veo", **overrides)

    def body(self, **overrides):
        return veo.request(self.shot, self.film, self.config(**overrides))

    def test_the_tier_picks_the_model(self):
        self.assertEqual("veo-3.1-lite-generate-001", self.body(tier="lite")["model"])
        self.assertEqual("veo-3.1-generate-001", self.body(tier="standard")["model"])
        self.assertEqual("veo-3.1-fast-generate-001", self.body(tier="fast")["model"])

    def test_every_priced_tier_has_a_model(self):
        """A tier the pricing table sells and the backend cannot render would be
        priced, budgeted for, and then refused at the call."""
        self.assertEqual(set(pricing.TIERS), set(veo.MODELS))

    def test_the_prompt_is_the_composed_one(self):
        body = self.body()
        self.assertEqual(self.shot.text, body["prompt"])
        # The author's line alone would ask for a shot the checker was never
        # told about, so it must be a strict part of what is sent.
        self.assertNotEqual(self.shot.prompt, body["prompt"])
        self.assertIn(self.shot.prompt.split("\n")[0], body["prompt"])

    def test_a_shot_is_always_eight_seconds(self):
        self.assertEqual(veo.SECONDS, self.body()["config"]["duration_seconds"])
        self.assertEqual(spec.SHOT_SECONDS, veo.SECONDS)

    def test_a_shot_of_another_length_is_refused(self):
        odd = spec.Shot(id="sX", slug="odd", seconds=6, prompt="a", continuity={})
        with self.assertRaises(veo.VeoError) as caught:
            veo.request(odd, self.film, self.config())
        self.assertIn("8s", str(caught.exception))

    def test_the_prompt_rewriter_is_off(self):
        """Veo's rewriter would rewrite the bible's continuity clauses, and every
        break the checker then found would be the rewriter's."""
        self.assertIs(False, self.body()["config"]["enhance_prompt"])

    def test_the_seed_and_the_audio_flag_are_sent_as_configured(self):
        body = self.body(seed=7)
        self.assertEqual(7, body["config"]["seed"])
        self.assertEqual(self.config().audio, body["config"]["generate_audio"])

    def test_the_resolution_is_the_rung_the_price_was_read_off(self):
        for resolution in ("1280x720", "1920x1080"):
            body = self.body(resolution=resolution)
            self.assertEqual(
                pricing.resolution_class(resolution), body["config"]["resolution"]
            )

    def test_one_video_per_call(self):
        # Veo bills per second of output, so a second sample is a second bill.
        self.assertEqual(1, self.body()["config"]["number_of_videos"])

    def test_a_shape_veo_does_not_generate_is_refused(self):
        square = spec.load(ROOT / "film.yaml")
        object.__setattr__(square, "resolution", "512x512")
        with self.assertRaises(veo.VeoError) as caught:
            veo.request(self.shot, square, self.config())
        self.assertIn("16:9", str(caught.exception))

    def test_no_config_is_a_refusal_rather_than_a_default(self):
        """Defaulting the tier would pick a price on the caller's behalf."""
        with self.assertRaises(veo.VeoError):
            veo.request(self.shot, self.film, None)

    def test_the_reference_frame_is_only_sent_when_there_is_one(self):
        self.assertNotIn("image", self.body())
        chained = veo.request(self.shot, self.film, self.config(), Path("/tmp/prev.png"))
        self.assertEqual("/tmp/prev.png", chained["image"]["path"])
        self.assertEqual("image/png", chained["image"]["mime_type"])

    def test_the_quoted_cost_matches_the_pricing_table(self):
        config = self.config(tier="standard", resolution="1920x1080")
        self.assertEqual(
            pricing.shot_cost(8, "standard", "1920x1080", config.audio), veo.cost(config)
        )
        self.assertIn("$", veo.describe(config))


class ResultTests(unittest.TestCase):
    """Reading the finished operation, which is where a silent empty file lives."""

    class FakeVideo:
        def __init__(self, video_bytes=None, uri=None):
            self.video_bytes = video_bytes
            self.uri = uri

    class FakeResult:
        def __init__(self, videos):
            self.generated_videos = videos

    class FakeOperation:
        def __init__(self, result):
            self.result = result

    def operation(self, *videos):
        return self.FakeOperation(self.FakeResult([type("G", (), {"video": v})() for v in videos]))

    def test_inline_bytes_are_taken_as_they_are(self):
        payload = veo._video_bytes(self.operation(self.FakeVideo(video_bytes=b"mp4")))
        self.assertEqual(b"mp4", payload)

    def test_base64_is_decoded(self):
        payload = veo._video_bytes(self.operation(self.FakeVideo(video_bytes="bXA0")))
        self.assertEqual(b"mp4", payload)

    def test_a_uri_says_what_to_do_rather_than_writing_nothing(self):
        with self.assertRaises(veo.VeoError) as caught:
            veo._video_bytes(self.operation(self.FakeVideo(uri="gs://bucket/shot.mp4")))
        self.assertIn("gs://bucket/shot.mp4", str(caught.exception))

    def test_success_with_no_video_is_an_error(self):
        with self.assertRaises(veo.VeoError):
            veo._video_bytes(self.operation())


class ReferenceFrameTests(unittest.TestCase):
    """The chain, rendered for real by the free backend and grabbed with ffmpeg.

    A reference image that came out empty or the wrong size would be sent as a
    first frame at full price, and the shot after it would not match the cut.
    """

    def test_the_last_frame_of_a_shot_is_a_full_size_picture(self):
        from cinema.backends import placeholder

        film = spec.load(ROOT / "film.yaml")
        shot = film.shots[0]
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "s01.mp4"
            placeholder.render(shot, film, video, log=lambda *_: None)
            frame = veo.last_frame(video, film, Path(tmp) / "ref.png")
            self.assertTrue(frame.exists())
            self.assertGreater(frame.stat().st_size, 0)
            probe = subprocess.run(
                ["ffprobe", "-v", "error", "-select_streams", "v:0",
                 "-show_entries", "stream=width,height", "-of", "csv=p=0", str(frame)],
                capture_output=True, text=True, check=True,
            )
            self.assertEqual(f"{film.width},{film.height}", probe.stdout.strip())


class ClientTests(unittest.TestCase):
    def test_a_missing_project_or_sdk_names_the_task_that_covers_it(self):
        with self.assertRaises(SystemExit) as caught:
            veo._client(project="")
        self.assertIn("#1008", str(caught.exception))


class LoopTests(unittest.TestCase):
    """The render loop hands a chaining backend the previous shot's file."""

    class Recorder:
        name = "veo"
        bills = False
        KEY_INPUTS = ("tier", "seed", "reference")

        def __init__(self):
            self.handed = []

        def render(self, shot, film, out_path, *, log=print, config=None, reference_video=None):
            self.handed.append((shot.id, config, reference_video))
            Path(out_path).parent.mkdir(parents=True, exist_ok=True)
            Path(out_path).write_text(shot.id)
            return out_path

    def test_each_shot_after_the_first_is_given_its_predecessors_file(self):
        film = spec.load(ROOT / "film.yaml")
        backend = self.Recorder()
        config = render.RenderConfig.build(film, "veo")
        with tempfile.TemporaryDirectory() as tmp:
            render.render_film(film, backend, config, tmp, log=lambda *_: None)
        shots = [s.id for s in film.shots]
        self.assertEqual(shots, [h[0] for h in backend.handed])
        self.assertIsNone(backend.handed[0][2])
        for (shot_id, handed_config, reference), previous in zip(backend.handed[1:], shots):
            self.assertEqual(config, handed_config, shot_id)
            self.assertIn(previous, Path(reference).name)


if __name__ == "__main__":
    unittest.main()
