"""Optional engine-level checks; these do not substitute for a MicroDuck trial."""

import importlib.util
from pathlib import Path
import tempfile
import unittest

from duck_course.scenes import layout, write_scene
from duck_course.simulator import touching_obstacles


@unittest.skipUnless(importlib.util.find_spec("mujoco"), "requires upstream MuJoCo environment")
class MuJoCoTests(unittest.TestCase):
    def test_scene_compiles_resolves_meshes_and_has_real_contacts(self):
        import mujoco
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            assets = root / "assets"
            assets.mkdir()
            (assets / "tetra.obj").write_text(
                "v 0 0 0\nv 1 0 0\nv 0 1 0\nv 0 0 1\n"
                "f 1 3 2\nf 1 2 4\nf 1 4 3\nf 2 3 4\n")
            robot = root / "robot_allcollisions.xml"
            robot.write_text("""<mujoco>
              <compiler angle="radian" meshdir="assets"/>
              <asset><mesh name="test" file="tetra.obj" scale=".02 .02 .02"/></asset>
              <worldbody><body pos="0 0 .12"><freejoint/>
                <geom type="sphere" size=".05" mass="1"/>
                <geom type="mesh" mesh="test" contype="0" conaffinity="0"/>
              </body></worldbody>
            </mujoco>""")
            scene = root / "elsewhere" / "course.xml"
            write_scene(robot, scene, layout())
            model = mujoco.MjModel.from_xml_path(str(scene))
            data = mujoco.MjData(model)
            obstacle = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM,
                                        "course_obstacle_0")
            mujoco.mj_forward(model, data)
            self.assertEqual(touching_obstacles(model, data, {obstacle}), set())
            data.qpos[:3] = [0.9, 0.3, 0.18]
            mujoco.mj_forward(model, data)
            self.assertEqual(touching_obstacles(model, data, {obstacle}), {obstacle})
            self.assertEqual(model.nsite, 1)


if __name__ == "__main__":
    unittest.main()
