"""The kinematic proxy exercises navigation logic only; it is not locomotion evidence."""

import math
import unittest

from duck_course.evaluation import EvaluationConfig
from duck_course.navigation import Action, PolicyConfig
from duck_course.proxy import (ProxyAssumptions, boxes, configs, geometry, proxy_episode,
                               ray_box, ray_distances, run_trial, sweep, tof_frame)
from duck_course.scenes import layout
from duck_course.sensing import sectors

ASSUME = ProxyAssumptions()


def episode(seed=None, strategy="clearance", **kwargs):
    return proxy_episode(layout(seed), strategy, PolicyConfig(), EvaluationConfig(),
                         ASSUME, **kwargs)


class RayTests(unittest.TestCase):
    box = ("b", 1.0, 2.0, -0.5, 0.5)

    def test_hit_miss_and_inside(self):
        self.assertAlmostEqual(ray_box(0, 0, 1, 0, self.box), 1.0)
        self.assertIsNone(ray_box(0, 0, -1, 0, self.box))
        self.assertIsNone(ray_box(0, 1, 1, 0, self.box))
        self.assertIsNone(ray_box(0, 0, 0, 1, self.box))  # parallel to the box, outside it
        self.assertEqual(ray_box(1.5, 0, 1, 0, self.box), 0.0)  # origin inside the box

    def test_columns_are_left_to_right(self):
        course = {"seed": None, "start": [0, 0], "goal_x": 2.8, "half_width": 0.9,
                  "obstacles": [{"x": 0.6, "y": 0.2, "half_size": [0.1, 0.1, 0.1]}]}
        rays = ray_distances(course, 0.0, 0.0, 0.0, ASSUME)
        self.assertLess(rays[0], 0.7)  # obstacle on the left, seen by the left column
        self.assertGreater(rays[7], 2.0)  # right column sees only the distant right wall
        frame = tof_frame(course, 0.0, 0.0, 0.0, ASSUME)
        self.assertEqual(frame["status"][0], 5)
        self.assertEqual(frame["distance_mm"][0], round(rays[0] * 1000))
        depth = sectors(frame)
        self.assertLess(depth.left, depth.right)
        self.assertTrue(depth.usable)

    def test_misses_are_reported_as_simulator_no_hit(self):
        course = layout() | {"obstacles": [], "half_width": 10.0}
        frame = tof_frame(course, 0.0, 0.0, 0.0, ASSUME)
        self.assertEqual(set(frame["status"]), {255})
        self.assertEqual(set(frame["distance_mm"]), {0})
        self.assertEqual(sectors(frame).forward, 4.0)


class GeometryTests(unittest.TestCase):
    def test_boxes_include_walls_and_obstacles(self):
        names = [name for name, *_ in boxes(layout())]
        self.assertEqual(names, ["obstacle_0", "obstacle_1", "wall_-1", "wall_1"])

    def test_fixed_course_gaps(self):
        report = geometry(layout())
        self.assertEqual(len(report["lateral_gaps"]), 2)
        self.assertAlmostEqual(report["longitudinal_spacing_m"][0], 0.6)
        self.assertGreater(report["min_widest_gap_m"], 0.9)

    def test_assumptions_are_validated(self):
        for kwargs in ({"dt_s": 0}, {"horizontal_fov_deg": 180}, {"max_range_m": math.nan}):
            with self.assertRaises(ValueError):
                ProxyAssumptions(**kwargs)
        policy, evaluation, assume = configs({"proxy": {"robot_radius_m": 0.1}})
        self.assertEqual(assume.robot_radius_m, 0.1)
        self.assertEqual(policy, PolicyConfig())
        self.assertEqual(evaluation, EvaluationConfig())


class EpisodeTests(unittest.TestCase):
    def test_fixed_course_succeeds_without_contact_for_both_strategies(self):
        for strategy in ("clearance", "right-hand"):
            with self.subTest(strategy=strategy):
                result = episode(strategy=strategy)
                self.assertEqual(result["status"], "success")
                self.assertEqual(result["collision_events"], 0)
                self.assertTrue(result["scored"])
                self.assertEqual(result["termination"], "episode")

    def test_deterministic(self):
        self.assertEqual(episode(3), episode(3))
        self.assertEqual(episode(3, record=True), episode(3, record=True))

    def test_recorded_frames_follow_the_action_trace(self):
        result = episode(record=True)
        frames = result["frames"]
        self.assertEqual(len(frames), result["steps"] + 1)
        self.assertEqual(frames[0]["t"], 0.0)
        self.assertEqual(frames[-1]["action"], Action.DONE.value)
        self.assertEqual(frames[-1]["status"], "success")
        self.assertEqual(sum(f["action"] == "forward" for f in frames[:-1]),
                         result["action_counts"]["forward"])
        for frame in frames:
            self.assertEqual(len(frame["rays"]), 8)
            self.assertIn(frame["sectors"]["usable"], (True, False))
        self.assertNotIn("frames", episode())

    def test_seed_48_corner_clip_is_a_known_stall(self):
        """Regression: a 45° cone looks past an obstacle corner the body clips.

        Both strategies push into obstacle 1 until the stall timer fires. If this
        starts passing, the navigation logic changed; update the README limitation.
        """
        for strategy in ("clearance", "right-hand"):
            with self.subTest(strategy=strategy):
                result = episode(48, strategy)
                self.assertEqual(result["status"], "stalled")
                self.assertEqual(result["collision_events"], 1)
                self.assertGreater(result["final_pose"][0], 1.4)
                self.assertLess(result["final_pose"][1], -0.5)

    def test_proxy_frames_are_always_usable(self):
        """The synthetic frame only emits valid hits or simulator no-hits, so the
        policy's fail-closed STOP branch is unreachable here; it is covered by the
        sensing and runtime tests against malformed frames instead."""
        for seed in (None, 0, 48):
            for frame in episode(seed, record=True)["frames"]:
                self.assertTrue(frame["sectors"]["usable"])


class ApiTests(unittest.TestCase):
    def test_run_trial_bundles_render_inputs(self):
        trial = run_trial(None, "clearance", {})
        self.assertEqual(trial["course"], layout())
        self.assertEqual(len(trial["boxes"]), 4)
        self.assertIn("frames", trial["result"])
        self.assertEqual(trial["config"]["policy"]["blocked_m"], 0.35)
        self.assertEqual(trial["assumptions"]["dt_s"], 0.1)

    def test_sweep_summarises_both_strategies(self):
        report = sweep([None, 0, 1], {})
        self.assertEqual(len(report["trials"]), 6)
        self.assertEqual(set(report["summary"]), {"clearance", "right-hand"})
        self.assertEqual(report["summary"]["clearance"]["layouts"], 3)
        self.assertNotIn("frames", report["trials"][0])

    def test_sweep_rejects_unknown_strategy(self):
        with self.assertRaises(ValueError):
            sweep([None, 0], {}, strategies=("teleport",))


if __name__ == "__main__":
    unittest.main()
