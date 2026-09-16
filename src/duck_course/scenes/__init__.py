"""Generate small, reproducible MJCF courses around an external official robot."""

import hashlib
import json
from pathlib import Path
import random
import xml.etree.ElementTree as ET


def layout(seed: int | None = None) -> dict:
    rng = random.Random(seed)
    obstacles = [
        {"x": 0.9, "y": 0.30, "half_size": [0.10, 0.18, 0.18]},
        {"x": 1.7, "y": -0.30, "half_size": [0.10, 0.18, 0.18]},
    ]
    if seed is not None:
        for obstacle in obstacles:
            obstacle["x"] = round(obstacle["x"] + rng.uniform(-0.12, 0.12), 4)
            obstacle["y"] = round(obstacle["y"] + rng.uniform(-0.12, 0.12), 4)
    return {"seed": seed, "start": [0.0, 0.0], "goal_x": 2.8,
            "half_width": 0.9, "obstacles": obstacles}


def identity(course: dict) -> str:
    return hashlib.sha256(json.dumps(course, sort_keys=True).encode()).hexdigest()


def write_scene(robot: Path, output: Path, course: dict) -> Path:
    """Use an absolute include and meshdir; never copy or modify upstream assets."""
    robot = robot.resolve(strict=True)
    if robot.name != "robot_allcollisions.xml":
        raise ValueError("use the official robot_allcollisions.xml for contact scoring")
    compiler = ET.parse(robot).getroot().find("compiler")
    meshdir = compiler.get("meshdir", ".") if compiler is not None else "."
    root = ET.Element("mujoco", model="duck_obstacle_course")
    ET.SubElement(root, "include", file=str(robot))
    ET.SubElement(root, "compiler", angle="radian",
                  meshdir=str((robot.parent / meshdir).resolve()))
    custom = ET.SubElement(root, "custom")
    ET.SubElement(custom, "text", name="course_id", data=identity(course))
    world = ET.SubElement(root, "worldbody")
    ET.SubElement(world, "light", pos="0 0 3", dir="0 0 -1", directional="true")
    ET.SubElement(world, "geom", name="floor", type="plane", size="5 5 0.1",
                  rgba="0.7 0.7 0.7 1", contype="1", conaffinity="1")
    for index, obstacle in enumerate(course["obstacles"]):
        size = obstacle["half_size"]
        ET.SubElement(world, "geom", name=f"course_obstacle_{index}", type="box",
                      pos=f'{obstacle["x"]} {obstacle["y"]} {size[2]}',
                      size=" ".join(map(str, size)), rgba="0.9 0.4 0.1 1",
                      contype="1", conaffinity="1")
    for side in (-1, 1):
        ET.SubElement(world, "geom", name=f"course_wall_{side}", type="box",
                      pos=f'1.4 {side * course["half_width"]} 0.2',
                      size="1.9 0.025 0.2", rgba="0.4 0.5 0.6 1",
                      contype="1", conaffinity="1")
    # A site is visible but neither collides nor intercepts the depth rays.
    ET.SubElement(world, "site", name="finish", type="box",
                  pos=f'{course["goal_x"]} 0 0.005',
                  size=f'0.02 {course["half_width"] - 0.1} 0.005',
                  rgba="0.1 0.8 0.2 0.5")
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root)
    ET.ElementTree(root).write(output, encoding="utf-8", xml_declaration=True)
    manifest = output.with_suffix(".json")
    manifest.write_text(json.dumps(course, indent=2) + "\n")
    return manifest
