"""Bounded NDJSON transport and a 10 Hz, fail-closed simulation episode runner."""

from contextlib import ExitStack, suppress
from dataclasses import asdict
import json
import math
from pathlib import Path
import socket
import time

from duck_course.evaluation import Episode, EvaluationConfig
from duck_course.navigation import Action, PolicyConfig, ReactivePolicy
from duck_course.scenes import identity
from duck_course.sensing import sectors


class Connection:
    def __init__(self, address):
        self.socket = socket.socket(socket.AF_UNIX if isinstance(address, str)
                                    else socket.AF_INET, socket.SOCK_STREAM)
        self.socket.settimeout(0.2)
        try:
            self.socket.connect(address)
            self.file = self.socket.makefile("rb")
        except BaseException:
            self.socket.close()
            raise

    def __enter__(self):
        return self

    def __exit__(self, *args):
        with suppress(OSError):
            self.file.close()
        with suppress(OSError):
            self.socket.close()

    def send(self, message: dict):
        self.socket.sendall((json.dumps(message, allow_nan=False) + "\n").encode())

    def receive(self) -> dict:
        raw = self.file.readline(65537)
        if len(raw) > 65536 or not raw.endswith(b"\n"):
            raise ValueError("missing, truncated, or oversized protocol frame")
        response = json.loads(raw)
        if not isinstance(response, dict):
            raise ValueError("expected a protocol object")
        if "error" in response:
            raise ValueError(f"remote error: {response['error']}")
        return response

    def observe(self) -> dict:
        self.send({"op": "observe"})
        return self.receive()

    def move(self, velocity: dict):
        self.send({"jsonrpc": "2.0", "method": "robot.move", "params": velocity})

    def enable(self):
        self.send({"jsonrpc": "2.0", "id": 1, "method": "robot.enable",
                   "params": {"on": True}})
        response = self.receive()
        if response.get("id") != 1 or "result" not in response:
            raise ValueError("robot.enable was not acknowledged")

    def wait_ready(self, timeout_s: float):
        """Use a dedicated connection so unread subscriptions cannot queue during driving."""
        deadline = time.monotonic() + timeout_s
        self.send({"jsonrpc": "2.0", "id": 2, "method": "robot.subscribe",
                   "params": {"hz": 10}})
        accepted = False
        while time.monotonic() < deadline:
            self.socket.settimeout(min(0.2, max(0.001, deadline - time.monotonic())))
            response = self.receive()
            if response.get("id") == 2:
                result = response.get("result", {})
                if (result.get("accepted") is not True or not result.get("walk")
                        or result.get("unavailable")):
                    raise ValueError("robotd locomotion policy is unavailable")
                accepted = True
            elif accepted and response.get("method") == "robot.state":
                state = response.get("params", {})
                safety = state.get("safety", {})
                if (state.get("policy") in ("walk", "stand")
                        and safety.get("fallen") is False and safety.get("limp") is False):
                    return
        raise ValueError("robotd locomotion controller did not become ready")


def run_episode(course: dict, robot_socket: str, telemetry_port: int,
                strategy: str, config: dict) -> dict:
    policy_config = PolicyConfig(**config.get("policy", {}))
    evaluation_config = EvaluationConfig(**config.get("evaluation", {}))
    policy = ReactivePolicy(policy_config, strategy)
    episode = Episode(course, evaluation_config)
    course_id = identity(course)
    actions = []
    error = None
    began = time.monotonic()

    def validate_start(sample):
        if sample["course_id"] != course_id:
            raise ValueError("layout does not match the running simulator")
        if math.dist(sample["trunk"][:2], course["start"]) > 0.1:
            raise ValueError("restart simulator at the start before each episode")
        check = Episode(course, evaluation_config)
        check.update(sample)
        if check.status != "running" or not sectors(sample["depth"]).usable:
            raise ValueError("simulator is not ready for an episode")

    with ExitStack() as stack:
        robot = None
        try:
            with Connection(("127.0.0.1", telemetry_port)) as telemetry:
                validate_start(telemetry.observe())
            robot = stack.enter_context(Connection(str(Path(robot_socket).expanduser())))
            robot.enable()
            with Connection(str(Path(robot_socket).expanduser())) as monitor:
                monitor.wait_ready(evaluation_config.startup_s)
            # Reconnect after readiness: the read-only server expires idle clients.
            telemetry = stack.enter_context(Connection(("127.0.0.1", telemetry_port)))
            initial = telemetry.observe()
            validate_start(initial)
            episode.update(initial)
            run_began = time.monotonic()
            next_tick = time.monotonic() + 0.1
            while episode.status == "running":
                time.sleep(max(0.0, next_tick - time.monotonic()))
                next_tick = time.monotonic() + 0.1
                if time.monotonic() - run_began >= evaluation_config.timeout_s + 5:
                    episode.finish("wall_timeout")
                    break
                sample = telemetry.observe()
                if sample["course_id"] != course_id:
                    raise ValueError("simulator changed during the episode")
                override = episode.update(sample)
                if override is not None:
                    policy.turn = None
                    action = override
                else:
                    depth = sectors(sample["depth"])
                    if not depth.usable:
                        raise ValueError("invalid depth data")
                    action = policy.decide(depth)
                robot.move(policy.velocity(action))
                actions.append({"sim_time": sample["sim_time"], "action": action.value})
        except KeyboardInterrupt:
            episode.finish("interrupted")
        except (OSError, ValueError, KeyError, TypeError, OverflowError) as exc:
            episode.finish("sensor_or_runtime_failure")
            error = str(exc)
        finally:
            if robot is not None:
                # Zero velocity leaves the standing/recovery policy enabled; never drop torque.
                with suppress(OSError, ValueError):
                    robot.move(policy.velocity(Action.STOP))
    return episode.result() | {
        "schema_version": 1, "strategy": strategy, "course_id": course_id,
        "seed": course["seed"], "course": course,
        "config": {"policy": asdict(policy_config), "evaluation": asdict(evaluation_config)},
        "wall_elapsed_s": time.monotonic() - began, "actions": actions, "error": error,
    }
