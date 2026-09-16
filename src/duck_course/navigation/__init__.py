"""Two deterministic reactive baselines. No pose, goal bearing, or map input."""

from dataclasses import dataclass
from enum import StrEnum
import math

from duck_course.sensing import Sectors


class Action(StrEnum):
    FORWARD = "forward"
    LEFT = "left"
    RIGHT = "right"
    STOP = "stop"
    RECOVER = "recover"
    DONE = "done"


@dataclass(frozen=True)
class PolicyConfig:
    blocked_m: float = 0.35
    clear_m: float = 0.50
    forward_m_s: float = 0.10
    turn_rad_s: float = 0.40

    def __post_init__(self):
        values = (self.blocked_m, self.clear_m, self.forward_m_s, self.turn_rad_s)
        if not all(math.isfinite(v) and v > 0 for v in values):
            raise ValueError("policy values must be finite and positive")
        if self.clear_m <= self.blocked_m:
            raise ValueError("clear_m must exceed blocked_m for hysteresis")
        if self.forward_m_s > 0.2 or self.turn_rad_s > 0.8:
            raise ValueError("velocity exceeds this experiment's conservative limits")


class ReactivePolicy:
    def __init__(self, config: PolicyConfig, strategy: str = "clearance"):
        if strategy not in ("clearance", "right-hand"):
            raise ValueError("unknown strategy")
        self.config = config
        self.strategy = strategy
        self.turn = None

    def decide(self, depth: Sectors) -> Action:
        if not depth.usable:
            self.turn = None
            return Action.STOP
        nearest = min(depth.left, depth.forward, depth.right)
        if self.turn is not None:
            if nearest < self.config.clear_m:
                return self.turn
            self.turn = None
        if nearest >= self.config.blocked_m:
            return Action.FORWARD
        if depth.forward < self.config.blocked_m:
            self.turn = (Action.RIGHT if self.strategy == "right-hand"
                         or depth.right >= depth.left else Action.LEFT)
        elif depth.left < self.config.blocked_m:
            self.turn = Action.RIGHT
        else:
            self.turn = Action.LEFT
        return self.turn

    def velocity(self, action: Action) -> dict:
        return {
            "vx": self.config.forward_m_s if action == Action.FORWARD else 0.0,
            "vy": 0.0,
            "vyaw": (self.config.turn_rad_s if action == Action.LEFT else
                     -self.config.turn_rad_s if action == Action.RIGHT else 0.0),
        }
