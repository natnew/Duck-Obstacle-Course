"""Truth-based scoring is isolated from depth-only navigation."""

from collections import Counter
from dataclasses import dataclass
import math

from duck_course.navigation import Action


@dataclass(frozen=True)
class EvaluationConfig:
    timeout_s: float = 90.0
    stall_s: float = 10.0
    progress_m: float = 0.05
    recovery_s: float = 4.0
    startup_s: float = 5.0
    minimum_height_m: float = 0.075
    minimum_up_cos: float = 0.5

    def __post_init__(self):
        if not all(math.isfinite(v) and v > 0 for v in vars(self).values()):
            raise ValueError("evaluation values must be finite and positive")
        if self.minimum_up_cos > 1:
            raise ValueError("minimum_up_cos must be at most 1")


class Episode:
    def __init__(self, course: dict, config: EvaluationConfig):
        self.course, self.config = course, config
        self.start = self.previous_time = None
        self.previous_position = self.anchor = None
        self.progress_time = None
        self.fallen_since = None
        self.status = "running"
        self.falls = self.collisions = 0
        self.initial_collisions = None
        self.distance = self.elapsed = 0.0

    def update(self, sample: dict) -> Action | None:
        if self.status != "running":
            return Action.DONE if self.status == "success" else Action.STOP
        now = sample["sim_time"]
        x, y, z = sample["trunk"]
        up = sample["up_cos"]
        collisions = sample["collision_events"]
        if (not all(math.isfinite(v) for v in (now, x, y, z, up))
                or not -1.001 <= up <= 1.001 or now < 0
                or not isinstance(collisions, int) or collisions < 0):
            raise ValueError("invalid simulator telemetry")
        if self.start is None:
            self.start = self.progress_time = now
            self.anchor = (x, y)
            self.initial_collisions = collisions
        elif now <= self.previous_time:
            raise ValueError("simulator time did not advance")
        if collisions < self.initial_collisions + self.collisions:
            raise ValueError("simulator collision counter went backwards")
        self.collisions = collisions - self.initial_collisions
        if self.previous_position is not None:
            self.distance += math.dist((x, y), self.previous_position)
        self.previous_position = (x, y)
        self.previous_time = now
        self.elapsed = now - self.start
        if self.elapsed >= self.config.timeout_s:
            return self.finish("timeout")
        if abs(y) >= self.course["half_width"] - 0.025 or x < -0.4:
            return self.finish("out_of_bounds")
        fallen = z < self.config.minimum_height_m or up < self.config.minimum_up_cos
        if fallen:
            if self.elapsed < self.config.startup_s:
                return Action.RECOVER
            if self.fallen_since is None:
                self.fallen_since = now
                self.falls += 1
            if now - self.fallen_since >= self.config.recovery_s:
                return self.finish("fallen")
            return Action.RECOVER
        if self.fallen_since is not None:
            self.fallen_since = None
            self.progress_time, self.anchor = now, (x, y)
        if x >= self.course["goal_x"]:
            return self.finish("success")
        if math.dist((x, y), self.anchor) >= self.config.progress_m:
            self.anchor, self.progress_time = (x, y), now
        if (self.elapsed >= self.config.startup_s
                and now - self.progress_time >= self.config.stall_s):
            return self.finish("stalled")
        return None

    def finish(self, status: str) -> Action:
        self.status = status
        return Action.DONE if status == "success" else Action.STOP

    def result(self) -> dict:
        return {"status": self.status, "elapsed_s": self.elapsed,
                "distance_m": self.distance, "collision_events": self.collisions,
                "falls": self.falls, "upright": self.falls == 0,
                "scored": self.status in
                ("success", "timeout", "stalled", "fallen", "out_of_bounds")}


def summarize(results: list[dict]) -> dict:
    groups = {}
    for strategy in sorted({result["strategy"] for result in results}):
        runs = [result for result in results if result["strategy"] == strategy]
        count = len(runs)
        scored = [r for r in runs if r["scored"]]
        measured = len(scored)
        groups[strategy] = {
            "episodes": count,
            "scored_episodes": measured,
            "layouts": len({r["course_id"] for r in runs}),
            "statuses": dict(Counter(r["status"] for r in runs)),
            "success_rate": sum(r["status"] == "success" for r in runs) / count,
            "collision_free_rate": (sum(r["collision_events"] == 0 for r in scored)
                                    / measured if measured else None),
            "upright_rate": (sum(r["upright"] for r in scored)
                             / measured if measured else None),
            "mean_elapsed_s": (sum(r["elapsed_s"] for r in scored)
                               / measured if measured else None),
            "mean_collision_events": (sum(r["collision_events"] for r in scored)
                                      / measured if measured else None),
        }
    return groups
