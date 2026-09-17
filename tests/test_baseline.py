import math
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET

from duck_course.evaluation import Episode, EvaluationConfig, summarize
from duck_course.navigation import Action, PolicyConfig, ReactivePolicy
from duck_course.scenes import identity, layout, write_scene
from duck_course.sensing import Sectors, sectors


def frame(distance=1000, status=5):
    return {"rows": 8, "cols": 8, "distance_mm": [distance] * 64,
            "status": [status] * 64}


def sample(t=0, x=0, y=0, z=0.12, up=1, contacts=0):
    return {"sim_time": t, "trunk": [x, y, z], "up_cos": up,
            "collision_events": contacts}


class SensingTests(unittest.TestCase):
    def test_mm_conversion_and_left_orientation(self):
        observation = frame()
        observation["distance_mm"][8] = 200
        self.assertEqual(sectors(observation), Sectors(0.2, 1.0, 1.0, True))

    def test_misses_are_simulator_max_range(self):
        self.assertEqual(sectors(frame(0, 255)), Sectors(4, 4, 4, True))

    def test_invalid_pixels_fail_closed(self):
        for distance, status in [(0, 5), (-1, 5), (math.nan, 5),
                                 (math.inf, 9), (100, 1), (5, 255)]:
            with self.subTest(distance=distance, status=status):
                self.assertFalse(sectors(frame(distance, status)).usable)
        self.assertTrue(sectors(frame(1000, 9)).usable)

    def test_noise_beyond_nominal_range_is_saturated(self):
        self.assertEqual(sectors(frame(4030, 5)), Sectors(4, 4, 4, True))

    def test_shape_validation(self):
        observation = frame()
        observation["distance_mm"].pop()
        with self.assertRaises(ValueError):
            sectors(observation)

    def test_lower_rows_excluded(self):
        observation = frame()
        observation["distance_mm"][56:] = [0] * 8
        self.assertTrue(sectors(observation).usable)


class PolicyTests(unittest.TestCase):
    def test_initial_rules(self):
        for depths, action in [
            ((1, 1, 1), Action.FORWARD),
            ((0.2, 1, 1), Action.RIGHT),
            ((1, 1, 0.2), Action.LEFT),
            ((1, 0.2, 0.5), Action.LEFT),
            ((0.5, 0.2, 1), Action.RIGHT),
            ((0.2, 0.2, 0.2), Action.RIGHT),
        ]:
            self.assertEqual(ReactivePolicy(PolicyConfig()).decide(
                Sectors(*depths, True)), action)

    def test_turn_hysteresis(self):
        policy = ReactivePolicy(PolicyConfig())
        self.assertEqual(policy.decide(Sectors(1, 0.2, 0.5, True)), Action.LEFT)
        self.assertEqual(policy.decide(Sectors(1, 0.4, 1, True)), Action.LEFT)
        self.assertEqual(policy.decide(Sectors(1, 0.5, 1, True)), Action.FORWARD)

    def test_right_hand_comparison(self):
        policy = ReactivePolicy(PolicyConfig(), "right-hand")
        self.assertEqual(policy.decide(Sectors(2, 0.2, 1, True)), Action.RIGHT)

    def test_invalid_stops_and_clears_latch(self):
        policy = ReactivePolicy(PolicyConfig())
        policy.decide(Sectors(1, 0.2, 1, True))
        self.assertEqual(policy.decide(Sectors(0, 0, 0, False)), Action.STOP)
        self.assertIsNone(policy.turn)

    def test_command_signs_and_safety(self):
        policy = ReactivePolicy(PolicyConfig())
        self.assertGreater(policy.velocity(Action.LEFT)["vyaw"], 0)
        self.assertLess(policy.velocity(Action.RIGHT)["vyaw"], 0)
        for action in (Action.STOP, Action.RECOVER, Action.DONE):
            self.assertEqual(policy.velocity(action), {"vx": 0, "vy": 0, "vyaw": 0})
        for kwargs in ({"clear_m": 0.2}, {"forward_m_s": 2}, {"turn_rad_s": math.nan}):
            with self.assertRaises(ValueError):
                PolicyConfig(**kwargs)


class EvaluationTests(unittest.TestCase):
    def episode(self, **kwargs):
        episode = Episode(layout(), EvaluationConfig(**kwargs))
        episode.update(sample())
        return episode

    def test_goal_and_metrics(self):
        episode = self.episode()
        self.assertEqual(episode.update(sample(1, 2.8, contacts=2)), Action.DONE)
        self.assertEqual(episode.status, "success")
        self.assertEqual(episode.result()["collision_events"], 2)
        self.assertAlmostEqual(episode.distance, 2.8)

    def test_stall_and_timeout(self):
        episode = self.episode()
        self.assertEqual(episode.update(sample(11)), Action.STOP)
        self.assertEqual(episode.status, "stalled")
        episode = self.episode(timeout_s=1)
        episode.update(sample(1, 0.1))
        self.assertEqual(episode.status, "timeout")

    def test_fall_recovery_and_exhaustion(self):
        episode = self.episode()
        self.assertEqual(episode.update(sample(6, up=0)), Action.RECOVER)
        self.assertIsNone(episode.update(sample(7, x=0.1)))
        self.assertEqual(episode.falls, 1)
        episode.update(sample(8, up=0))
        episode.update(sample(12, up=0))
        self.assertEqual(episode.status, "fallen")
        self.assertEqual(episode.falls, 2)

    def test_startup_grace(self):
        episode = self.episode()
        self.assertEqual(episode.update(sample(1, z=0.07)), Action.RECOVER)
        self.assertEqual(episode.falls, 0)
        episode.update(sample(5, z=0.07))
        self.assertEqual(episode.falls, 1)

    def test_fallen_goal_is_not_success(self):
        episode = self.episode()
        self.assertEqual(episode.update(sample(6, 2.8, up=0)), Action.RECOVER)

    def test_out_of_bounds(self):
        episode = self.episode()
        episode.update(sample(1, 2.8, y=1))
        self.assertEqual(episode.status, "out_of_bounds")

    def test_invalid_and_stale_truth(self):
        for observation in (sample(), sample(-1), sample(1, x=math.nan),
                            sample(1, up=2), sample(1, contacts=-1)):
            with self.assertRaises(ValueError):
                self.episode().update(observation)

    def test_summary(self):
        result = self.episode().result() | {"strategy": "clearance", "course_id": "fixed",
                                           "scored": True}
        summary = summarize([result | {"status": "success"}, result | {"status": "stalled"}])
        self.assertEqual(summary["clearance"]["success_rate"], 0.5)
        self.assertEqual(summary["clearance"]["layouts"], 1)
        self.assertEqual(summarize([]), {})

    def test_no_telemetry_is_not_collision_free_evidence(self):
        episode = self.episode()
        episode.finish("sensor_or_runtime_failure")
        result = episode.result() | {"strategy": "clearance", "course_id": "fixed"}
        summary = summarize([result])["clearance"]
        self.assertEqual(summary["scored_episodes"], 0)
        self.assertIsNone(summary["collision_free_rate"])
        self.assertIsNone(summary["upright_rate"])


class SceneTests(unittest.TestCase):
    def test_layout_reproducibility_and_clearance(self):
        self.assertEqual(layout(42), layout(42))
        self.assertNotEqual(identity(layout(42)), identity(layout(43)))
        for seed in range(100):
            course = layout(seed)
            a, b = course["obstacles"]
            self.assertGreater(b["x"] - a["x"], 0.5)
            for obstacle in course["obstacles"]:
                self.assertLess(abs(obstacle["y"]) + obstacle["half_size"][1], 0.65)
                self.assertGreater(obstacle["x"] - obstacle["half_size"][0], 0.6)

    def test_scene_uses_external_assets_and_noncolliding_goal(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            robot = root / "robot_allcollisions.xml"
            robot.write_text('<mujoco><compiler meshdir="assets"/></mujoco>')
            scene = root / "generated" / "course.xml"
            manifest = write_scene(robot, scene, layout())
            self.assertTrue(manifest.exists())
            tree = ET.parse(scene)
            self.assertEqual(tree.find("include").get("file"), str(robot))
            self.assertEqual(tree.find("compiler").get("meshdir"), str(root / "assets"))
            self.assertEqual(tree.find("custom/text").get("data"), identity(layout()))
            self.assertIsNotNone(tree.find("worldbody/site[@name='finish']"))
            self.assertEqual(len(tree.findall("worldbody/geom")), 5)


if __name__ == "__main__":
    unittest.main()
