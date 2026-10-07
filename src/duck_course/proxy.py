"""Deterministic 2-D kinematic proxy for the reactive navigation logic.

The proxy drives the real ``ReactivePolicy``, ``sectors()`` and ``Episode`` code
with a point-robot unicycle and a synthetic ray-cast 8x8 ToF frame. It is NOT
MicroDuck locomotion: there are no legs, balance, falls, slip, latency or upstream
policies. Proxy outcomes describe the navigation logic only. The same code serves
the offline evaluation harness and the browser demo so that both exercise exactly
the package that the unit tests cover.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import asdict, dataclass
import hashlib
import math

from duck_course.evaluation import Episode, EvaluationConfig, summarize
from duck_course.navigation import Action, PolicyConfig, ReactivePolicy
from duck_course.scenes import identity, layout
from duck_course.sensing import Sectors, sectors

STRATEGIES = ("clearance", "right-hand")
WALL_HALF_THICKNESS = 0.025  # scenes.write_scene: wall size "1.9 0.025 0.2"
WALL_X = (1.4 - 1.9, 1.4 + 1.9)

Box = tuple[str, float, float, float, float]


@dataclass(frozen=True)
class ProxyAssumptions:
    """Explicit, inspectable assumptions of the kinematic proxy."""

    dt_s: float = 0.1  # runtime.py commands at 10 Hz
    robot_radius_m: float = 0.08
    sensor_offset_m: float = 0.08
    horizontal_fov_deg: float = 45.0
    max_range_m: float = 4.0
    trunk_height_m: float = 0.12

    def __post_init__(self):
        values = (self.dt_s, self.robot_radius_m, self.sensor_offset_m,
                  self.horizontal_fov_deg, self.max_range_m, self.trunk_height_m)
        if not all(math.isfinite(v) and v > 0 for v in values):
            raise ValueError("proxy assumptions must be finite and positive")
        if self.horizontal_fov_deg >= 180:
            raise ValueError("horizontal_fov_deg must be below 180")


def boxes(course: dict) -> list[Box]:
    """Axis-aligned (name, xmin, xmax, ymin, ymax) for obstacles and walls."""
    result: list[Box] = []
    for index, obstacle in enumerate(course["obstacles"]):
        hx, hy, _ = obstacle["half_size"]
        result.append((f"obstacle_{index}", obstacle["x"] - hx, obstacle["x"] + hx,
                       obstacle["y"] - hy, obstacle["y"] + hy))
    for side in (-1, 1):
        y = side * course["half_width"]
        result.append((f"wall_{side}", WALL_X[0], WALL_X[1],
                       y - WALL_HALF_THICKNESS, y + WALL_HALF_THICKNESS))
    return result


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


def ray_box(ox: float, oy: float, dx: float, dy: float, box: Box) -> float | None:
    """Distance along the ray to an axis-aligned box, or None when it misses.

    Slab test, unrolled for the hot loop. Keep the divisions: replacing them with
    a reciprocal multiply changes rounding and therefore recorded action traces.
    """
    _, xmin, xmax, ymin, ymax = box
    if -1e-12 < dx < 1e-12:
        if not xmin <= ox <= xmax:
            return None
        tmin, tmax = -math.inf, math.inf
    else:
        tmin, tmax = (xmin - ox) / dx, (xmax - ox) / dx
        if tmin > tmax:
            tmin, tmax = tmax, tmin
    if -1e-12 < dy < 1e-12:
        if not ymin <= oy <= ymax:
            return None
    else:
        t1, t2 = (ymin - oy) / dy, (ymax - oy) / dy
        if t1 > t2:
            t1, t2 = t2, t1
        if t1 > tmin:
            tmin = t1
        if t2 < tmax:
            tmax = t2
    if tmax < tmin or tmax < 0.0:
        return None
    return tmin if tmin >= 0 else 0.0


def ray_distances(course: dict, x: float, y: float, heading: float,
                  assume: ProxyAssumptions, course_boxes: list[Box] | None = None
                  ) -> list[float | None]:
    """Nearest hit per column in metres, column 0 leftmost; None is a miss."""
    ox = x + assume.sensor_offset_m * math.cos(heading)
    oy = y + assume.sensor_offset_m * math.sin(heading)
    fov = math.radians(assume.horizontal_fov_deg)
    course_boxes = boxes(course) if course_boxes is None else course_boxes
    columns: list[float | None] = []
    for col in range(8):
        angle = heading + fov / 2 - (col + 0.5) * fov / 8
        dx, dy = math.cos(angle), math.sin(angle)
        nearest = None
        for box in course_boxes:
            t = ray_box(ox, oy, dx, dy, box)
            if t is not None and (nearest is None or t < nearest):
                nearest = t
        columns.append(None if nearest is None or nearest > assume.max_range_m
                       else nearest)
    return columns


def frame_from_rays(rays: list[float | None]) -> dict:
    """Synthetic 8x8 frame; identical across rows. Column 0 is left (README)."""
    columns = []
    for nearest in rays:
        if nearest is None:
            columns.append((0, 255))  # simulator no-hit convention
        else:
            columns.append((max(1, round(nearest * 1000)), 5))
    return {"rows": 8, "cols": 8,
            "distance_mm": [d for _ in range(8) for d, _ in columns],
            "status": [s for _ in range(8) for _, s in columns]}


def tof_frame(course: dict, x: float, y: float, heading: float,
              assume: ProxyAssumptions) -> dict:
    return frame_from_rays(ray_distances(course, x, y, heading, assume))


def touching(course: dict, x: float, y: float, radius: float,
             course_boxes: list[Box] | None = None) -> list[str]:
    """Names of course boxes the robot disc overlaps."""
    result = []
    for name, xmin, xmax, ymin, ymax in (boxes(course) if course_boxes is None
                                         else course_boxes):
        cx, cy = min(max(x, xmin), xmax), min(max(y, ymin), ymax)
        if math.hypot(x - cx, y - cy) < radius:
            result.append(name)
    return result


def _frame(t: float, x: float, y: float, heading: float, depth: Sectors,
           rays: list[float | None], action: Action | None, latched: Action | None,
           collisions: int, status: str) -> dict:
    return {"t": round(t, 6), "x": round(x, 5), "y": round(y, 5),
            "heading": round(heading, 5),
            "sectors": {"left": round(depth.left, 4), "forward": round(depth.forward, 4),
                        "right": round(depth.right, 4), "usable": depth.usable},
            "rays": [None if r is None else round(r, 4) for r in rays],
            "action": None if action is None else action.value,
            "latched": None if latched is None else latched.value,
            "collisions": collisions, "status": status}


def proxy_episode(course: dict, strategy: str, policy_cfg: PolicyConfig,
                  eval_cfg: EvaluationConfig, assume: ProxyAssumptions,
                  record: bool = False) -> dict:
    """Run one proxy episode; with ``record`` the result carries per-step frames."""
    policy = ReactivePolicy(policy_cfg, strategy)
    episode = Episode(course, eval_cfg)
    course_boxes = boxes(course)
    x, y = course["start"]
    heading, t = 0.0, 0.0
    collisions, in_contact = 0, False
    actions: list[str] = []
    frames: list[dict] = []
    termination = None
    while True:
        override = episode.update({"sim_time": t, "trunk": [x, y, assume.trunk_height_m],
                                   "up_cos": 1.0, "collision_events": collisions})
        rays = ray_distances(course, x, y, heading, assume, course_boxes)
        depth = sectors(frame_from_rays(rays))
        if override in (Action.DONE, Action.STOP):
            termination = "episode"
            if record:
                frames.append(_frame(t, x, y, heading, depth, rays, override,
                                     None, collisions, episode.status))
            break
        action = policy.decide(depth)
        actions.append(action.value)
        if record:
            frames.append(_frame(t, x, y, heading, depth, rays, action, policy.turn,
                                 collisions, episode.status))
        if action == Action.STOP:
            termination = "policy_stop"
            break
        command = policy.velocity(action)
        heading += command["vyaw"] * assume.dt_s
        nx = x + command["vx"] * math.cos(heading) * assume.dt_s
        ny = y + command["vx"] * math.sin(heading) * assume.dt_s
        if touching(course, nx, ny, assume.robot_radius_m, course_boxes):
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
    if record:
        result["frames"] = frames
    return result


def configs(config: dict) -> tuple[PolicyConfig, EvaluationConfig, ProxyAssumptions]:
    """Validated configuration objects from a ``configs/*.json``-shaped mapping."""
    return (PolicyConfig(**config.get("policy", {})),
            EvaluationConfig(**config.get("evaluation", {})),
            ProxyAssumptions(**config.get("proxy", {})))


def run_trial(seed: int | None, strategy: str, config: dict) -> dict:
    """One recorded proxy trial plus everything a renderer needs to draw it."""
    policy_cfg, eval_cfg, assume = configs(config)
    course = layout(seed)
    result = proxy_episode(course, strategy, policy_cfg, eval_cfg, assume, record=True)
    return {"course": course, "boxes": boxes(course), "geometry": geometry(course),
            "assumptions": asdict(assume),
            "config": {"policy": asdict(policy_cfg), "evaluation": asdict(eval_cfg)},
            "result": result}


def sweep(seeds: Iterable[int | None], config: dict,
          strategies: Iterable[str] = STRATEGIES) -> dict:
    """Unrecorded proxy trials for every (seed, strategy) with a summary."""
    policy_cfg, eval_cfg, assume = configs(config)
    trials = [proxy_episode(layout(seed), strategy, policy_cfg, eval_cfg, assume)
              for seed in seeds for strategy in strategies]
    return {"trials": trials, "summary": summarize(trials)}
