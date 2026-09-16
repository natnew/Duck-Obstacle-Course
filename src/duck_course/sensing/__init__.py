"""Conservative sector reduction of the simulator's 8×8 ToF observations."""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Sectors:
    left: float
    forward: float
    right: float
    usable: bool


def sectors(frame: dict) -> Sectors:
    """Distances in metres, using rows 1–4 to limit ground/self returns.

    Status 255 means a ray missed in this simulator, NOT on arbitrary hardware.
    Unknown/invalid pixels are obstacles. Never interpret a broken frame as clear.
    """
    if frame.get("rows") != 8 or frame.get("cols") != 8:
        raise ValueError("expected an 8x8 simulator ToF frame")
    distances, statuses = frame["distance_mm"], frame["status"]
    if len(distances) != 64 or len(statuses) != 64:
        raise ValueError("expected 64 distances and statuses")
    groups = [[], [], []]
    usable = True
    for row in range(1, 5):
        for col in range(8):
            index = row * 8 + col
            distance, status = distances[index], statuses[index]
            if status == 255 and distance == 0:
                value = 4.0
            elif (status in (5, 9) and isinstance(distance, (int, float))
                  and math.isfinite(distance) and distance > 0):
                # The official ray caster adds noise after its 4 m range cutoff.
                value = min(distance / 1000, 4.0)
            else:
                value = 0.0
                usable = False
            groups[0 if col < 3 else 1 if col < 5 else 2].append(value)
    return Sectors(*(min(group) for group in groups), usable)
