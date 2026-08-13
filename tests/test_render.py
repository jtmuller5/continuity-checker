"""What the render loop must do with money on the line.

Every test here uses a fake backend that writes a byte instead of a video, so
the loop's behaviour is measured rather than ffmpeg's. It counts calls, because
the whole claim of this module is about which renders do not happen: a cache
that quietly re-renders four good shots still produces a correct film, and on
Veo Standard it costs $12.80 to do it.
"""

from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from cinema import backends, cli, pricing, render, spec  # noqa: E402


class FakeBackend:
    """A backend that writes a file and remembers being asked to.

    `KEY_INPUTS` is the thing under test in several cases below, so it is a
    constructor argument rather than a module constant.
    """

    bills = False

    def __init__(self, key_inputs=(), name="fake"):
        self.name = name
        self.KEY_INPUTS = tuple(key_inputs)
        self.calls = []
        self.handed = []
        self.fail_on = set()
        self.payload = "a"

    def render(self, shot, film, out_path, *, log=print, config=None, reference_video=None):
        self.calls.append(shot.id)
        self.handed.append((shot.id, config, reference_video))
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        if shot.id in self.fail_on:
            # Write first, then blow up. A real renderer killed mid-way leaves
            # a short file behind, and that is the case worth testing — a
            # backend that fails cleanly proves nothing about the rename.
            Path(out_path).write_text("half a fi")
            raise RuntimeError(f"backend blew up on {shot.id}")
        Path(out_path).write_text(f"{shot.id}:{self.payload}")
        return out_path


def quiet(*_args, **_kwargs):
    pass


class RenderLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)
        self.film = spec.load(ROOT / "film.yaml")
        self.backend = FakeBackend()
        self.config = render.RenderConfig.build(self.film, "fake")

    def run_loop(self, **kwargs):
        kwargs.setdefault("log", quiet)
        return render.render_film(self.film, self.backend, self.config, self.out, **kwargs)

    def test_a_second_pass_renders_nothing(self):
        self.run_loop()
        self.assertEqual(len(self.backend.calls), 5)
        self.backend.calls.clear()
        results = self.run_loop()
        self.assertEqual(self.backend.calls, [], "a clean re-run paid for the whole film again")
        self.assertTrue(all(r.cached for r in results))

    def test_editing_one_shot_re_renders_only_that_shot(self):
        # The reason the cache exists. Change s03's continuity, as fixing a
        # caught break does, and the other four must survive it.
        self.run_loop()
        self.backend.calls.clear()
        # A fix is two edits, not one: the shot stops being wrong and the answer
        # key stops claiming it is. The spec refuses a key that disagrees with
        # the shots, which is what stops #1014 scoring against a stale film.
        source = (ROOT / "film.yaml").read_text().replace(
            "      jacket: blue", "      jacket: red", 1
        ).replace(
            "  - shot: s03\n    attribute: jacket\n    from: red\n    to: blue\n", "", 1
        )
        edited = self.out / "edited.yaml"
        edited.write_text(source)
        self.film = spec.load(edited)
        self.run_loop()
        self.assertEqual(self.backend.calls, ["s03"])

    def test_naming_a_shot_re_renders_it_even_when_it_is_cached(self):
        self.run_loop()
        self.backend.calls.clear()
        self.run_loop(only=["s03"])
        self.assertEqual(self.backend.calls, ["s03"])

    def test_naming_a_shot_that_does_not_exist_is_refused(self):
        with self.assertRaises(ValueError):
            self.run_loop(only=["s99"])

    def test_a_deleted_shot_comes_back(self):
        self.run_loop()
        self.backend.calls.clear()
        render.shot_path(self.out, self.film.shot("s02")).unlink()
        self.run_loop()
        self.assertEqual(self.backend.calls, ["s02"])

    def test_a_shot_whose_bytes_changed_is_not_trusted(self):
        # The ledger holds a digest, not just a path. A truncated or overwritten
        # file must not be served as the cached render of anything.
        self.run_loop()
        self.backend.calls.clear()
        render.shot_path(self.out, self.film.shot("s05")).write_text("rubbish")
        self.run_loop()
        self.assertEqual(self.backend.calls, ["s05"])

    def test_a_crash_costs_one_shot_and_not_the_pass(self):
        self.backend.fail_on = {"s03"}
        with self.assertRaises(RuntimeError):
            self.run_loop()
        self.assertEqual(self.backend.calls, ["s01", "s02", "s03"])
        self.backend.fail_on = set()
        self.backend.calls.clear()
        self.run_loop()
        self.assertEqual(
            self.backend.calls, ["s03", "s04", "s05"],
            "resuming re-rendered shots that had already succeeded",
        )

    def test_a_failed_render_leaves_nothing_that_could_be_cached(self):
        self.backend.fail_on = {"s01"}
        with self.assertRaises(RuntimeError):
            self.run_loop()
        # iterdir, not glob: the part file is deliberately hidden, and glob("*")
        # would not see it — the test would pass by not looking.
        stray = sorted((self.out / "shots").iterdir()) if (self.out / "shots").exists() else []
        self.assertEqual(stray, [], f"a half-written render survived: {stray}")

    def test_force_re_renders_everything(self):
        self.run_loop()
        self.backend.calls.clear()
        self.run_loop(force=True)
        self.assertEqual(len(self.backend.calls), 5)


class CacheKeyTests(unittest.TestCase):
    """The key must move on exactly the inputs the backend actually reads."""

    def setUp(self):
        self.film = spec.load(ROOT / "film.yaml")
        self.shot = self.film.shot("s01")

    def key(self, backend, reference=None, **overrides):
        config = render.RenderConfig.build(self.film, backend.name, **overrides)
        return render.cache_key(self.shot, config, backend, reference)

    def test_a_backend_that_ignores_the_seed_keeps_its_cache(self):
        drawing = FakeBackend(key_inputs=())
        self.assertEqual(self.key(drawing, seed=1), self.key(drawing, seed=2))

    def test_a_backend_that_reads_the_seed_loses_its_cache(self):
        sampling = FakeBackend(key_inputs=("seed",))
        self.assertNotEqual(self.key(sampling, seed=1), self.key(sampling, seed=2))

    def test_the_tier_changes_the_key_for_a_backend_that_has_tiers(self):
        veo_like = FakeBackend(key_inputs=("tier", "seed", "reference"))
        self.assertNotEqual(self.key(veo_like, tier="lite"), self.key(veo_like, tier="standard"))

    def test_the_resolution_always_changes_the_key(self):
        # No backend can render two sizes into one file, so this one is not the
        # backend's to opt out of.
        drawing = FakeBackend(key_inputs=())
        self.assertNotEqual(
            self.key(drawing, resolution="320x180"),
            self.key(drawing, resolution="1280x720"),
        )

    def test_the_reference_frame_only_counts_where_it_is_used(self):
        chaining = FakeBackend(key_inputs=("reference",))
        standalone = FakeBackend(key_inputs=())
        self.assertNotEqual(self.key(chaining, reference="aaa"), self.key(chaining, reference="bbb"))
        self.assertEqual(self.key(standalone, reference="aaa"), self.key(standalone, reference="bbb"))

    def test_the_shipped_backends_declare_what_they_read(self):
        from cinema.backends import placeholder, veo

        self.assertEqual(render.key_inputs(placeholder), ())
        self.assertEqual(set(render.key_inputs(veo)), {"tier", "seed", "reference"})


class ChainingTests(unittest.TestCase):
    """Veo's re-render feeds the previous shot's last frame in as a reference.

    So a fixed shot 3 makes shots 4 and 5 stale, and a backend without that
    dependency must not pay for the cascade.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)
        self.film = spec.load(ROOT / "film.yaml")

    def render_with(self, backend, **kwargs):
        config = render.RenderConfig.build(self.film, backend.name)
        return render.render_film(self.film, backend, config, self.out, log=quiet, **kwargs)

    def test_a_chaining_backend_re_renders_what_came_after(self):
        backend = FakeBackend(key_inputs=("reference",))
        self.render_with(backend)
        backend.calls.clear()
        backend.payload = "b"  # the re-render of s03 comes out different
        self.render_with(backend, only=["s03"])
        self.assertEqual(
            backend.calls, ["s03", "s04", "s05"],
            "shot 3's new last frame is shot 4's reference image, so 4 and 5 are stale",
        )

    def test_a_standalone_backend_does_not_cascade(self):
        backend = FakeBackend(key_inputs=())
        self.render_with(backend)
        backend.calls.clear()
        backend.payload = "b"
        self.render_with(backend, only=["s03"])
        self.assertEqual(backend.calls, ["s03"])

    def test_a_re_render_that_comes_out_identical_costs_nothing_downstream(self):
        backend = FakeBackend(key_inputs=("reference",))
        self.render_with(backend)
        backend.calls.clear()
        self.render_with(backend, only=["s03"])
        self.assertEqual(
            backend.calls, ["s03"],
            "s03's bytes did not change, so nothing downstream depended on anything new",
        )


class BudgetTests(unittest.TestCase):
    """The ceiling, which is the only thing standing between a typo and $100.

    The backend bills and writes a byte, so the money is real arithmetic over
    the published table and no second is ever bought. At the spec's 320x180 a
    standard shot lands on the 720p rung: $0.20 a second, 8 seconds, $1.60 a
    shot and $8.00 for the film.
    """

    SHOT = 1.60
    FILM = 8.00

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)
        self.film = spec.load(ROOT / "film.yaml")
        self.backend = FakeBackend()
        self.backend.bills = True

    def config(self, ceiling, **overrides):
        return render.RenderConfig.build(
            self.film, self.backend.name, tier="standard", max_spend_usd=ceiling, **overrides
        )

    def run_loop(self, ceiling, **kwargs):
        return render.render_film(
            self.film, self.backend, self.config(ceiling), self.out, log=quiet, **kwargs
        )

    def test_the_price_of_a_shot_is_read_from_the_table_and_not_from_here(self):
        # Everything below compares against these two, so they are derived once
        # rather than trusted five times.
        self.assertAlmostEqual(
            pricing.shot_cost(8, "standard", self.film.resolution, False), self.SHOT
        )
        self.assertAlmostEqual(self.SHOT * len(self.film.shots), self.FILM)

    def test_a_pass_over_the_ceiling_renders_nothing_at_all(self):
        with self.assertRaises(render.BudgetError) as caught:
            self.run_loop(self.FILM - 0.01)
        self.assertEqual(self.backend.calls, [], "it priced the pass and bought it anyway")
        self.assertFalse((self.out / "shots").exists())
        self.assertIn("$8.00", str(caught.exception))

    def test_a_pass_exactly_on_the_ceiling_is_allowed(self):
        # A ceiling of $8.00 that refuses an $8.00 pass is a rounding bug, and
        # it would read as the ledger being wrong rather than the comparison.
        self.run_loop(self.FILM)
        self.assertEqual(len(self.backend.calls), 5)
        self.assertAlmostEqual(render.spent(render.load_ledger(self.out)), self.FILM)

    def test_the_projection_is_what_the_pass_then_charges(self):
        plan = render.plan_spend(self.film, self.backend, self.config(None), self.out)
        self.assertEqual(plan.rendering, 5)
        self.assertAlmostEqual(plan.projected, self.FILM)
        results = self.run_loop(None)
        self.assertAlmostEqual(sum(r.cost for r in results), plan.projected)

    def test_the_projection_prices_the_cascade_a_chaining_backend_will_have(self):
        backend = FakeBackend(key_inputs=("reference",))
        backend.bills = True
        config = render.RenderConfig.build(self.film, backend.name, tier="standard")
        render.render_film(self.film, backend, config, self.out, log=quiet)
        backend.payload = "b"  # the re-render of s03 will come out different
        plan = render.plan_spend(self.film, backend, config, self.out, only=["s03"])
        self.assertEqual([s.shot_id for s in plan.shots if s.rendering], ["s03", "s04", "s05"])
        self.assertAlmostEqual(plan.projected, self.SHOT * 3)

    def test_no_ceiling_means_no_ceiling(self):
        self.run_loop(None)
        self.assertEqual(len(self.backend.calls), 5)

    def test_a_ceiling_of_nothing_is_a_real_ceiling_and_not_an_absent_one(self):
        with self.assertRaises(render.BudgetError):
            self.run_loop(0.0)
        self.assertEqual(self.backend.calls, [])

    def test_a_free_backend_is_never_stopped_by_a_ceiling_of_nothing(self):
        free = FakeBackend()
        config = render.RenderConfig.build(self.film, free.name, max_spend_usd=0.0)
        render.render_film(self.film, free, config, self.out, log=quiet)
        self.assertEqual(len(free.calls), 5)

    def test_a_negative_ceiling_is_refused_before_anything_is_priced(self):
        with self.assertRaises(ValueError):
            self.config(-1.0)

    def test_what_was_already_spent_counts_against_the_ceiling(self):
        self.run_loop(self.FILM)  # $8.00 spent, film complete
        self.backend.calls.clear()
        self.backend.payload = "b"
        with self.assertRaises(render.BudgetError) as caught:
            self.run_loop(self.FILM, only=["s01"])
        self.assertEqual(self.backend.calls, [])
        self.assertIn("$8.00 already recorded", str(caught.exception))

    def test_the_lifetime_total_does_not_forget_a_replaced_render(self):
        self.run_loop(None)
        self.backend.payload = "b"
        self.run_loop(None, only=["s01"])
        ledger = render.load_ledger(self.out)
        # s01's entry has been overwritten, so the rows account for one film
        # while the money spent is one film and one shot.
        self.assertAlmostEqual(render.spent_on_disk(ledger), self.FILM)
        self.assertAlmostEqual(render.spent(ledger), self.FILM + self.SHOT)

    def test_an_old_ledger_with_no_total_is_read_as_what_its_shots_cost(self):
        self.run_loop(None)
        path = self.out / render.LEDGER_NAME
        aged = json.loads(path.read_text())
        del aged["spent_usd"]
        path.write_text(json.dumps(aged))
        self.assertAlmostEqual(render.spent(render.load_ledger(self.out)), self.FILM)

    def test_an_optimistic_projection_still_stops_the_pass_part_way(self):
        """The second check, and the reason there are two.

        A plan is priced by reading the cache, and the cache can go stale
        between the pricing and the render. This hands the loop a plan that
        claims the film is free — the shape of that failure — and asserts it
        stops at the shot that crosses rather than finishing the pass.
        """
        ceiling = self.SHOT * 2
        lying = render.Plan(
            [render.PlannedShot(s.id, 0.0, False) for s in self.film.shots], 0.0, ceiling
        )
        self.assertFalse(lying.over)
        with self.assertRaises(render.BudgetError) as caught:
            self.run_loop(ceiling, plan=lying)
        self.assertEqual(self.backend.calls, ["s01", "s02"], "it spent past the ceiling")
        self.assertIn("s03", str(caught.exception))
        # Stopped, not lost: the two shots are on disk and paid for in the
        # ledger, so the next run resumes rather than repeats.
        ledger = render.load_ledger(self.out)
        self.assertAlmostEqual(render.spent(ledger), ceiling)
        self.assertEqual(sorted(ledger["shots"]), ["s01", "s02"])

    def test_a_stopped_pass_finishes_when_the_ceiling_is_raised(self):
        ceiling = self.SHOT * 2
        lying = render.Plan(
            [render.PlannedShot(s.id, 0.0, False) for s in self.film.shots], 0.0, ceiling
        )
        with self.assertRaises(render.BudgetError):
            self.run_loop(ceiling, plan=lying)
        self.backend.calls.clear()
        self.run_loop(self.FILM)
        self.assertEqual(self.backend.calls, ["s03", "s04", "s05"], "it paid for s01 twice")
        self.assertAlmostEqual(render.spent(render.load_ledger(self.out)), self.FILM)


class BudgetCommandTests(unittest.TestCase):
    """The ceiling as a person meets it: through the command line.

    The backend is registered under a name of its own for the length of one
    test and writes a byte, so `--i-will-pay` here authorises nothing — there
    is no account, no credential and no second of video. What it proves is the
    order: the flag opens the door, and the ceiling is the next thing behind
    it.
    """

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)
        self.backend = FakeBackend(name="fakepaid")
        self.backend.bills = True
        backends.BACKENDS[self.backend.name] = self.backend
        self.addCleanup(backends.BACKENDS.pop, self.backend.name, None)

    def run_cli(self, *extra):
        argv = [
            "--spec", str(ROOT / "film.yaml"), "--out", str(self.out),
            "render", "--backend", self.backend.name, "--tier", "standard",
            "--i-will-pay", *extra,
        ]
        said = io.StringIO()
        with contextlib.redirect_stdout(said):
            code = cli.main(argv)
        return code, said.getvalue()

    def test_the_projected_spend_is_printed_before_the_first_call(self):
        code, said = self.run_cli("--max-spend", "8.00")
        self.assertEqual(0, code)
        self.assertIn("$8.00 projected", said)
        self.assertIn("ceiling $8.00", said)

    def test_the_command_line_ceiling_refuses_the_pass(self):
        with self.assertRaises(SystemExit) as caught:
            self.run_cli("--max-spend", "1.00")
        self.assertIn("budget:", str(caught.exception))
        self.assertEqual(self.backend.calls, [])

    def test_the_spec_supplies_the_ceiling_when_the_flag_does_not(self):
        # film.yaml's own number, so a run that forgets the flag is still bounded.
        ceiling = spec.load(ROOT / "film.yaml").render["max_spend_usd"]
        code, said = self.run_cli()
        self.assertEqual(0, code)
        self.assertIn(f"ceiling ${float(ceiling):.2f}", said)


class PricingTests(unittest.TestCase):
    def test_one_standard_shot_matches_the_published_price(self):
        # $0.40 per second of 1080p with audio, 8 seconds. notes/render-cost.md.
        self.assertAlmostEqual(pricing.shot_cost(8, "standard", "1920x1080", True), 3.20)

    def test_the_cheap_tier_is_the_one_to_iterate_on(self):
        self.assertAlmostEqual(pricing.shot_cost(8, "lite", "1280x720", False), 0.24)

    def test_lite_cannot_sell_4k(self):
        with self.assertRaises(pricing.PricingError):
            pricing.shot_cost(8, "lite", "3840x2160", False)

    def test_the_placeholder_backend_is_priced_at_nothing(self):
        from cinema.backends import placeholder

        film = spec.load(ROOT / "film.yaml")
        config = render.RenderConfig.build(film, placeholder.name)
        self.assertEqual(render._cost(film.shot("s01"), config, placeholder), 0.0)

    def test_a_full_pass_is_what_the_budget_note_says(self):
        film = spec.load(ROOT / "film.yaml")
        pass_cost = sum(
            pricing.shot_cost(s.seconds, "standard", "1920x1080", True) for s in film.shots
        )
        self.assertAlmostEqual(pass_cost, 16.00)


class LedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.out = Path(self.tmp.name)
        self.film = spec.load(ROOT / "film.yaml")

    def test_wall_clock_is_recorded_for_every_shot(self):
        # The one number notes/render-cost.md still calls unmeasured. It is
        # recorded by the loop rather than by whoever remembers to time it.
        backend = FakeBackend()
        config = render.RenderConfig.build(self.film, backend.name)
        render.render_film(self.film, backend, config, self.out, log=quiet)
        entries = render.load_ledger(self.out)["shots"]
        self.assertEqual(set(entries), {s.id for s in self.film.shots})
        for shot_id, entry in entries.items():
            self.assertIn("wall_clock", entry, shot_id)
            self.assertGreaterEqual(entry["wall_clock"], 0.0)
        groups = render.timings(self.out)
        self.assertEqual(len(groups), 1)
        self.assertEqual(len(next(iter(groups.values())).samples), 5)

    def test_a_corrupt_ledger_is_a_cold_cache_and_not_a_crash(self):
        (self.out / render.LEDGER_NAME).write_text("{not json")
        self.assertEqual(render.load_ledger(self.out)["shots"], {})

    def test_the_ledger_records_what_a_shot_cost(self):
        backend = FakeBackend()
        backend.bills = True
        config = render.RenderConfig.build(self.film, backend.name, tier="standard")
        render.render_film(self.film, backend, config, self.out, log=quiet)
        entry = render.load_ledger(self.out)["shots"]["s01"]
        shot = self.film.shot("s01")
        # Derived from the same table the loop bills against, never a copied
        # number: the spec's resolution is what was rendered.
        expected = pricing.shot_cost(shot.seconds, "standard", self.film.resolution, False)
        self.assertAlmostEqual(entry["cost_usd"], expected)
        self.assertEqual(entry["tier"], "standard")
        self.assertEqual(entry["resolution"], self.film.resolution)


class ConfigTests(unittest.TestCase):
    def test_the_spec_supplies_the_defaults(self):
        film = spec.load(ROOT / "film.yaml")
        config = render.RenderConfig.build(film, "placeholder")
        self.assertEqual(config.tier, film.render["tier"])
        self.assertEqual(config.seed, int(film.render["seed"]))
        self.assertEqual(config.resolution, film.resolution)

    def test_the_command_line_wins(self):
        film = spec.load(ROOT / "film.yaml")
        config = render.RenderConfig.build(film, "placeholder", tier="standard", seed=7)
        self.assertEqual(config.tier, "standard")
        self.assertEqual(config.seed, 7)

    def test_an_unknown_tier_is_refused_before_anything_renders(self):
        film = spec.load(ROOT / "film.yaml")
        with self.assertRaises(ValueError):
            render.RenderConfig.build(film, "placeholder", tier="ultra")


if __name__ == "__main__":
    unittest.main()
