"""Offline, deterministic evaluation harness for the /microduck-evaluation workflow.

Imports the repository's navigation, sensing, scene and evaluation code read-only
and writes artefacts under results/ (git-ignored). It never modifies src/.

What it measures:
  * layout determinism and course-identity stability per seed;
  * course geometry per seed (lateral gaps, longitudinal spacing);
  * a 2-D KINEMATIC PROXY episode per (seed, strategy): a point-robot unicycle
    with a synthetic ray-cast 8x8 ToF frame, driven by the real ReactivePolicy and
    scored by the real Episode. This is NOT MicroDuck locomotion: there are no
    legs, balance, falls, slip, latency or upstream policies. Proxy outcomes
    describe the reactive navigation logic only.

Usage:
  PYTHONPATH=src python scripts/microduck_evaluation.py --seeds 0 1 2 3 4 \
      --output results/eval-YYYYMMDD-HHMMSS
"""

from __future__ import annotations

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import platform
import subprocess
import sys

from duck_course.evaluation import Episode, EvaluationConfig, summarize
from duck_course.navigation import Action, PolicyConfig, ReactivePolicy
from duck_course.scenes import identity, layout
from duck_course.sensing import sectors

STRATEGIES = ("clearance", "right-hand")
WALL_HALF_THICKNESS = 0.025  # scenes.write_scene: wall size "1.9 0.025 0.2"
WALL_X = (1.4 - 1.9, 1.4 + 1.9)


@dataclass(frozen=True)
class ProxyAssumptions:
    """Explicit, inspectable assumptions of the kinematic proxy."""

    dt_s: float = 0.1  # runtime.py commands at 10 Hz
    robot_radius_m: float = 0.08
    sensor_offset_m: float = 0.08
    horizontal_fov_deg: float = 45.0
    max_range_m: float = 4.0
    trunk_height_m: float = 0.12


def _boxes(course: dict) -> list[tuple[str, float, float, float, float]]:
    """Axis-aligned (name, xmin, xmax, ymin, ymax) for obstacles and walls."""
    boxes = []
    for index, obstacle in enumerate(course["obstacles"]):
        hx, hy, _ = obstacle["half_size"]
        boxes.append((f"obstacle_{index}", obstacle["x"] - hx, obstacle["x"] + hx,
                      obstacle["y"] - hy, obstacle["y"] + hy))
    for side in (-1, 1):
        y = side * course["half_width"]
        boxes.append((f"wall_{side}", WALL_X[0], WALL_X[1],
                      y - WALL_HALF_THICKNESS, y + WALL_HALF_THICKNESS))
    return boxes


def geometry(course: dict) -> dict:
    """Free lateral gaps beside each obstacle and longitudinal spacing."""
    inner = course["half_width"] - WALL_HALF_THICKNESS
    gaps = []
    for index, obstacle in enumerate(course["obstacles"]):
        hy = obstacle["half_size"][1]
        gaps.append({"obstacle": index,
                     "left_gap_m": round(inner - (obstacle["y"] + hy), 4),
                     "right_gap_m": round((obstacle["y"] - hy) + inner, 4)})
    ordered = sorted(course["obstacles"], key=lambda o: o["x"])
    spacing = [round((b["x"] - b["half_size"][0]) - (a["x"] + a["half_size"][0]), 4)
               for a, b in zip(ordered, ordered[1:])]
    widest = [max(g["left_gap_m"], g["right_gap_m"]) for g in gaps]
    return {"lateral_gaps": gaps, "longitudinal_spacing_m": spacing,
            "min_widest_gap_m": min(widest) if widest else None}


def _ray_box(ox: float, oy: float, dx: float, dy: float, box: tuple) -> float | None:
    _, xmin, xmax, ymin, ymax = box
    tmin, tmax = -math.inf, math.inf
    for o, d, lo, hi in ((ox, dx, xmin, xmax), (oy, dy, ymin, ymax)):
        if abs(d) < 1e-12:
            if not lo <= o <= hi:
                return None
            continue
        t1, t2 = (lo - o) / d, (hi - o) / d
        tmin, tmax = max(tmin, min(t1, t2)), min(tmax, max(t1, t2))
    if tmax < max(tmin, 0.0):
        return None
    return tmin if tmin >= 0 else 0.0


def tof_frame(course: dict, x: float, y: float, heading: float,
              assume: ProxyAssumptions) -> dict:
    """Synthetic 8x8 frame; identical across rows. Column 0 is left (README)."""
    ox = x + assume.sensor_offset_m * math.cos(heading)
    oy = y + assume.sensor_offset_m * math.sin(heading)
    fov = math.radians(assume.horizontal_fov_deg)
    columns = []
    for col in range(8):
        angle = heading + fov / 2 - (col + 0.5) * fov / 8
        dx, dy = math.cos(angle), math.sin(angle)
        hits = [t for box in _boxes(course)
                if (t := _ray_box(ox, oy, dx, dy, box)) is not None]
        nearest = min(hits, default=None)
        if nearest is None or nearest > assume.max_range_m:
            columns.append((0, 255))  # simulator no-hit convention
        else:
            columns.append((max(1, round(nearest * 1000)), 5))
    return {"rows": 8, "cols": 8,
            "distance_mm": [d for _ in range(8) for d, _ in columns],
            "status": [s for _ in range(8) for _, s in columns]}


def _touching(course: dict, x: float, y: float, radius: float) -> list[str]:
    touching = []
    for name, xmin, xmax, ymin, ymax in _boxes(course):
        cx, cy = min(max(x, xmin), xmax), min(max(y, ymin), ymax)
        if math.hypot(x - cx, y - cy) < radius:
            touching.append(name)
    return touching


def proxy_episode(course: dict, strategy: str, policy_cfg: PolicyConfig,
                  eval_cfg: EvaluationConfig, assume: ProxyAssumptions) -> dict:
    policy = ReactivePolicy(policy_cfg, strategy)
    episode = Episode(course, eval_cfg)
    x, y = course["start"]
    heading, t = 0.0, 0.0
    collisions, in_contact = 0, False
    actions: list[str] = []
    termination = None
    while True:
        override = episode.update({"sim_time": t, "trunk": [x, y, assume.trunk_height_m],
                                   "up_cos": 1.0, "collision_events": collisions})
        if override in (Action.DONE, Action.STOP):
            termination = "episode"
            break
        action = policy.decide(sectors(tof_frame(course, x, y, heading, assume)))
        actions.append(action.value)
        if action == Action.STOP:
            termination = "policy_stop"
            break
        command = policy.velocity(action)
        heading += command["vyaw"] * assume.dt_s
        nx = x + command["vx"] * math.cos(heading) * assume.dt_s
        ny = y + command["vx"] * math.sin(heading) * assume.dt_s
        if _touching(course, nx, ny, assume.robot_radius_m):
            if not in_contact:
                collisions += 1  # onset only; persistent contact counts once
            in_contact = True  # blocked: the proxy body does not penetrate
        else:
            in_contact = False
            x, y = nx, ny
        t = round(t + assume.dt_s, 6)
    result = episode.result()
    result.update({
        "strategy": strategy, "seed": course["seed"], "course_id": identity(course),
        "termination": termination,
        "final_pose": [round(x, 4), round(y, 4), round(heading, 4)],
        "action_counts": {a: actions.count(a) for a in sorted(set(actions))},
        "action_trace_sha256": hashlib.sha256(",".join(actions).encode()).hexdigest(),
        "steps": len(actions),
    })
    if termination == "policy_stop":
        result.update({"status": "policy_stop", "scored": False})
    return result


def _git(*args: str) -> str | None:
    try:
        return subprocess.run(["git", *args], capture_output=True, text=True,
                              check=True).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="MicroDuck offline seeded evaluation")
    parser.add_argument("--seeds", type=int, nargs="+", default=list(range(10)))
    parser.add_argument("--config", type=Path, default=Path("configs/baseline.json"))
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--no-fixed", action="store_true",
                        help="omit the fixed (seed=None) regression course")
    args = parser.parse_args()
    if len(set(args.seeds)) < 5:
        parser.error("at least 5 distinct seeds are required")
    if args.output.exists():
        parser.error(f"{args.output} already exists; evaluation runs are never overwritten")
    args.output.mkdir(parents=True)

    config = json.loads(args.config.read_text())
    policy_cfg = PolicyConfig(**config.get("policy", {}))
    eval_cfg = EvaluationConfig(**config.get("evaluation", {}))
    assume = ProxyAssumptions()
    seeds: list[int | None] = ([] if args.no_fixed else [None]) + sorted(set(args.seeds))

    layouts, geometries, determinism, trials = {}, {}, [], []
    for seed in seeds:
        key = "fixed" if seed is None else str(seed)
        course = layout(seed)
        layouts[key] = {"course": course, "course_id": identity(course)}
        geometries[key] = geometry(course)
        repeat = layout(seed)
        determinism.append({"seed": key, "layout_identical": repeat == course,
                            "identity_identical": identity(repeat) == identity(course)})
        for strategy in STRATEGIES:
            first = proxy_episode(course, strategy, policy_cfg, eval_cfg, assume)
            second = proxy_episode(course, strategy, policy_cfg, eval_cfg, assume)
            determinism.append({"seed": key, "strategy": strategy,
                                "proxy_episode_identical": first == second})
            trials.append(first)

    ids = [v["course_id"] for v in layouts.values()]
    checks_passed = all(all(v for k, v in c.items() if k not in ("seed", "strategy"))
                        for c in determinism)
    payloads = {
        "environment.json": {
            "python": sys.version, "platform": platform.platform(),
            "git_head": _git("rev-parse", "HEAD"),
            "git_dirty_paths": (_git("status", "--porcelain") or "").splitlines(),
            "config_path": str(args.config), "config_sha256": _sha256(args.config),
            "config": config, "seeds": ["fixed" if s is None else s for s in seeds],
            "strategies": list(STRATEGIES), "proxy_assumptions": asdict(assume),
            "argv": sys.argv,
        },
        "layouts.json": layouts,
        "geometry.json": geometries,
        "determinism.json": {"checks": determinism, "all_passed": checks_passed,
                             "distinct_course_ids": len(set(ids)), "courses": len(ids)},
        "proxy-trials.json": trials,
        "proxy-summary.json": summarize(trials),
    }
    for name, payload in payloads.items():
        (args.output / name).write_text(json.dumps(payload, indent=2, allow_nan=False)
                                        + "\n")
    manifest = {name: _sha256(args.output / name) for name in sorted(payloads)}
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    print(json.dumps({"output": str(args.output), "determinism_passed": checks_passed,
                      "summary": payloads["proxy-summary.json"]}, indent=2))
    return 0 if checks_passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
