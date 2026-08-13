"""The four steps of the loop, and the ADK graph that runs them.

`cinema fix` and `cinema agent` do the same work in the same order — the first
in this process, the second as a `google.adk.workflow.Workflow` whose nodes are
the same four functions. So the claims here are:

  * **Each step does its own job and nothing else.** Perceiving re-reads the
    film when the last report no longer describes it, judging reads the repair
    off the finding, acting keeps the broken frame before it overwrites it, and
    verifying reads the film again rather than declaring it fixed.
  * **The graph runs the same functions, in the same order.** The nodes are
    named for the steps and chained one to the next, so a step added to the loop
    and not to the graph is visible rather than silent.
  * **The graph really runs.** The ADK test drives a whole turn through ADK's
    own runner with stand-in stages: no model, no credential, no network.

Everything is driven with recorders in a temporary directory. Nothing renders,
nothing is read by a model, and nothing is billed.
"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from dataclasses import dataclass, field
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from cinema import agent, fixes as fixes_mod  # noqa: E402
from cinema.bible import Break  # noqa: E402
from cinema.check import Report  # noqa: E402

try:  # the graph half of this file, and the only thing that needs the SDK
    import google.adk  # noqa: F401

    HAS_ADK = True
except ImportError:  # pragma: no cover - depends on what is installed
    HAS_ADK = False


@dataclass
class FakeShot:
    id: str
    slug: str = "shot"
    seconds: int = 8


@dataclass
class FakeFilm:
    shots: list = field(default_factory=lambda: [FakeShot("s03"), FakeShot("s04")])

    def shot(self, shot_id):
        return next(s for s in self.shots if s.id == shot_id)


def report(*breaks, at="2026-08-13T12:00:00+00:00", reader="pixels") -> Report:
    return Report(
        film="a film",
        reader=reader,
        model=None,
        frames_per_shot=2,
        readings=(),
        breaks=tuple(breaks),
        cost=0.0,
        at=at,
    )


JACKET = Break(shot="s03", attribute="jacket", before="red", after="blue", rule="constant")
PARCEL = Break(shot="s04", attribute="parcel", before="present", after="absent", rule="constant")


class JobHarness(unittest.TestCase):
    """A job whose four stages are recorders, in a temporary directory."""

    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.dir, ignore_errors=True)
        self.said = []
        self.calls = []
        self.codes = {}
        self.report = report(JACKET, PARCEL)
        self.job = agent.Job(
            out=self.dir,
            load=lambda: FakeFilm(),
            read_report=self.read_report,
            check=lambda: self.stage("check"),
            render=lambda: self.stage("render"),
            assemble=lambda: self.stage("assemble"),
            score=lambda: self.stage("score"),
            say=self.said.append,
        )

    def read_report(self):
        self.calls.append("read_report")
        if self.report is None:
            raise ValueError("no report at out/continuity.json: run check first")
        return self.report

    def stage(self, name):
        self.calls.append(name)
        return self.codes.get(name, 0)

    def spoke(self) -> str:
        return "\n".join(self.said)


class TestPerceive(JobHarness):
    def test_a_fresh_report_is_used_as_it_stands(self):
        """Nothing is re-read when the reading still describes the film."""
        summary = agent.perceive(self.job)

        self.assertNotIn("check", self.calls)
        self.assertFalse(summary["re_read"])
        self.assertEqual(2, len(summary["breaks"]))
        self.assertIs(self.report, self.job.report)

    def test_no_report_means_the_film_is_read(self):
        self.report = None

        def check():
            self.calls.append("check")
            self.report = report(JACKET)
            return 0

        self.job.check = check
        summary = agent.perceive(self.job)

        self.assertIn("check", self.calls)
        self.assertTrue(summary["re_read"])
        self.assertEqual(1, len(summary["breaks"]))

    def test_a_report_older_than_the_film_is_thrown_away(self):
        """The guard the demo needs: a stale reading describes a film that is gone.

        Acting on it would repair shots that were already repaired, and report a
        clean film without having looked at it.
        """
        with mock.patch.object(agent.score_mod, "stale_shots", return_value=("s03",)):
            fresh = report(JACKET)

            def check():
                self.calls.append("check")
                self.report = fresh
                return 0

            self.job.check = check
            summary = agent.perceive(self.job)

        self.assertIn("check", self.calls)
        self.assertTrue(summary["re_read"])
        self.assertIn("older than s03", self.spoke())
        self.assertIs(fresh, self.job.report)

    def test_a_check_that_fails_stops_the_turn(self):
        self.report = None
        self.codes["check"] = 1
        with self.assertRaises(agent.AgentError):
            agent.perceive(self.job)


class TestJudge(JobHarness):
    def test_the_repair_is_the_value_the_bible_declared(self):
        agent.perceive(self.job)
        summary = agent.judge(self.job)

        self.assertEqual({"s03": {"jacket": "red"}, "s04": {"parcel": "present"}}, summary["repairs"])
        self.assertIn("s03 jacket -> red", self.spoke())

    def test_nothing_to_repair_is_said_rather_than_assumed(self):
        self.report = report()
        agent.perceive(self.job)

        self.assertEqual({}, agent.judge(self.job)["repairs"])
        self.assertIn("nothing to repair", self.spoke())

    def test_judging_before_perceiving_is_refused(self):
        with self.assertRaises(agent.AgentError):
            agent.judge(self.job)


class RenderHarness(JobHarness):
    """The same job, with the two things that shell out to ffmpeg recorded."""

    def setUp(self):
        super().setUp()
        self.grabbed = []
        self.plates = []
        for module, name, side_effect in (
            (agent.frames_mod, "grab", self.grab),
            (agent.compare_mod, "plate", self.plate),
        ):
            patch = mock.patch.object(module, name, side_effect=side_effect)
            patch.start()
            self.addCleanup(patch.stop)

    def grab(self, video, at, dest):
        self.grabbed.append(Path(dest).name)
        return Path(dest)

    def plate(self, before, after, dest, *, left, right):
        self.plates.append((Path(dest).name, left, right))
        return Path(dest)

    def run_to_act(self):
        agent.perceive(self.job)
        agent.judge(self.job)
        return agent.act(self.job)


class TestAct(RenderHarness):
    def test_the_broken_frame_is_kept_before_the_shot_is_overwritten(self):
        """A re-rendered shot replaces its own file, so this is the only chance."""
        summary = self.run_to_act()

        self.assertEqual(["s03-before.png", "s04-before.png"], self.grabbed)
        self.assertLess(self.calls.index("read_report"), self.calls.index("render"))
        self.assertEqual(["s03", "s04"], summary["repaired"])

    def test_the_repair_is_a_layer_and_not_an_edit_to_the_spec(self):
        self.run_to_act()

        self.assertEqual(
            {"s03": {"jacket": "red"}, "s04": {"parcel": "present"}},
            fixes_mod.load(self.dir),
        )

    def test_the_film_is_rendered_and_then_assembled(self):
        self.run_to_act()

        self.assertEqual(["render", "assemble"], self.calls[-2:])

    def test_a_render_that_fails_stops_the_turn(self):
        self.codes["render"] = 1
        agent.perceive(self.job)
        agent.judge(self.job)
        with self.assertRaises(agent.AgentError):
            agent.act(self.job)

    def test_nothing_is_touched_when_there_is_nothing_to_repair(self):
        self.report = report()
        agent.perceive(self.job)
        agent.judge(self.job)
        summary = agent.act(self.job)

        self.assertEqual([], summary["repaired"])
        self.assertEqual([], self.grabbed)
        self.assertNotIn("render", self.calls)
        self.assertFalse(fixes_mod.path(self.dir).exists())


class TestVerify(RenderHarness):
    def test_the_film_is_read_again_rather_than_declared_fixed(self):
        self.run_to_act()
        self.calls.clear()
        summary = agent.verify(self.job)

        self.assertEqual(["check", "score"], self.calls)
        self.assertTrue(summary["verified"])

    def test_the_plate_labels_each_side_with_what_it_shows(self):
        """The broken frame is captioned with the break, not with the repair."""
        self.run_to_act()
        agent.verify(self.job)

        names = [p[0] for p in self.plates]
        self.assertEqual(["s03.png", "s04.png"], names)
        self.assertIn("jacket=blue", self.plates[0][1])
        self.assertIn("jacket=red", self.plates[0][2])

    def test_the_scorer_decides_the_exit_code(self):
        self.codes["score"] = 1
        self.run_to_act()

        self.assertEqual(1, agent.verify(self.job)["exit"])
        self.assertEqual(1, self.job.exit_code)

    def test_nothing_repaired_means_nothing_verified(self):
        self.report = report()
        agent.perceive(self.job)
        agent.judge(self.job)
        agent.act(self.job)
        summary = agent.verify(self.job)

        self.assertFalse(summary["verified"])
        self.assertNotIn("score", self.calls)


class TestRunSteps(RenderHarness):
    def test_the_whole_turn_runs_in_order(self):
        summaries = agent.run_steps(self.job)

        self.assertEqual(list(agent.STEPS), [s["step"] for s in summaries])
        self.assertEqual(["render", "assemble", "check", "score"],
                         [c for c in self.calls if c != "read_report"])


@unittest.skipUnless(HAS_ADK, "google-adk is not installed")
class TestWorkflow(RenderHarness):
    """The graph, run through ADK's own runner. No model, no credential."""

    def test_the_graph_is_the_four_steps_chained_in_order(self):
        workflow = agent.build_workflow(self.job)
        graph = workflow.graph

        chained = [(edge.from_node.name, edge.to_node.name) for edge in graph.edges]
        names = [name for _, name in chained]
        self.assertEqual(list(agent.STEPS), names)
        self.assertEqual(list(agent.STEPS[:-1]), [source for source, _ in chained[1:]])

    def test_running_the_graph_runs_the_whole_turn(self):
        outputs = agent.run_workflow(self.job)

        self.assertEqual(list(agent.STEPS), sorted(outputs, key=agent.STEPS.index))
        self.assertEqual(["s03", "s04"], outputs["act"]["repaired"])
        self.assertTrue(outputs["verify"]["verified"])
        self.assertEqual(["render", "assemble", "check", "score"],
                         [c for c in self.calls if c != "read_report"])

    def test_the_graph_carries_what_each_step_found(self):
        """What a resumed or inspected run reads, rather than the console."""
        outputs = agent.run_workflow(self.job)

        self.assertEqual(2, len(outputs["perceive"]["breaks"]))
        self.assertEqual({"s03": {"jacket": "red"}, "s04": {"parcel": "present"}},
                         outputs["judge"]["repairs"])


if __name__ == "__main__":
    unittest.main()
