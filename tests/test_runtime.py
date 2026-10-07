from contextlib import contextmanager
import json
from pathlib import Path
import socketserver
import tempfile
import threading
import unittest
from unittest.mock import MagicMock, patch

from duck_course.runtime import Connection, run_episode
from duck_course.scenes import identity, layout
from duck_course.simulator import ContactCounter, touching_obstacles


def observation(t=0, x=0):
    return {"course_id": identity(layout()), "sim_time": t, "trunk": [x, 0, 0.12],
            "up_cos": 1.0, "collision_events": 0,
            "depth": {"rows": 8, "cols": 8, "distance_mm": [1000] * 64,
                      "status": [5] * 64}}


class RunnerTests(unittest.TestCase):
    def run_trial(self, observations, enable_error=None, readiness_error=None):
        telemetry, robot, monitor = MagicMock(), MagicMock(), MagicMock()
        telemetry.__enter__.return_value = telemetry
        robot.__enter__.return_value = robot
        monitor.__enter__.return_value = monitor
        telemetry.observe.side_effect = [observations[0], *observations]
        robot.enable.side_effect = enable_error
        monitor.wait_ready.side_effect = readiness_error
        with patch("duck_course.runtime.Connection",
                   side_effect=[telemetry, robot, monitor, telemetry]), \
                patch("duck_course.runtime.time.sleep"):
            result = run_episode(layout(), "/tmp/test-duck.sock", 7802, "clearance", {})
        return result, robot

    def test_success_and_stop(self):
        result, robot = self.run_trial([observation(), observation(1, 0.1), observation(2, 2.8)])
        self.assertEqual(result["status"], "success")
        self.assertGreater(robot.move.call_args_list[0].args[0]["vx"], 0)
        self.assertEqual(robot.move.call_args.args[0], {"vx": 0, "vy": 0, "vyaw": 0})

    def test_bad_depth_stops(self):
        bad = observation(2)
        bad["depth"]["status"][8] = 0
        result, robot = self.run_trial([observation(), observation(1, 0.1), bad])
        self.assertEqual(result["status"], "sensor_or_runtime_failure")
        self.assertEqual(robot.move.call_args.args[0]["vx"], 0)

    def test_io_failure_and_interrupt_stop(self):
        for error, status in [(TimeoutError("timeout"), "sensor_or_runtime_failure"),
                              (KeyboardInterrupt(), "interrupted")]:
            result, robot = self.run_trial([observation(), observation(1, 0.1), error])
            self.assertEqual(result["status"], status)
            self.assertEqual(robot.move.call_args.args[0]["vx"], 0)

    def test_enable_failure_stops(self):
        result, robot = self.run_trial([observation()], ValueError("not enabled"))
        self.assertEqual(result["status"], "sensor_or_runtime_failure")
        self.assertEqual(robot.move.call_args.args[0]["vx"], 0)

    def test_missing_controller_is_not_a_scored_stall(self):
        result, robot = self.run_trial([observation()],
                                       readiness_error=ValueError("no policy"))
        self.assertEqual(result["status"], "sensor_or_runtime_failure")
        self.assertFalse(result["scored"])
        self.assertEqual(robot.move.call_args.args[0]["vx"], 0)

    def test_stale_observation_stops(self):
        result, robot = self.run_trial([observation(), observation()])
        self.assertEqual(result["status"], "sensor_or_runtime_failure")
        self.assertEqual(robot.move.call_args.args[0]["vx"], 0)

    def test_wrong_scene_never_enables(self):
        initial = observation()
        initial["course_id"] = "wrong"
        result, robot = self.run_trial([initial])
        self.assertEqual(result["status"], "sensor_or_runtime_failure")
        robot.enable.assert_not_called()

    def test_non_start_position_never_enables(self):
        result, robot = self.run_trial([observation(x=1)])
        self.assertEqual(result["status"], "sensor_or_runtime_failure")
        robot.enable.assert_not_called()

    def test_recovery_never_commands_motion(self):
        fallen = observation(6)
        fallen["up_cos"] = 0
        exhausted = fallen | {"sim_time": 10}
        result, robot = self.run_trial([observation(), fallen, exhausted])
        self.assertEqual(result["status"], "fallen")
        for call in robot.move.call_args_list:
            self.assertEqual(call.args[0], {"vx": 0, "vy": 0, "vyaw": 0})


requires_unix_sockets = unittest.skipUnless(
    hasattr(socketserver, "UnixStreamServer"), "robotd speaks over AF_UNIX sockets (POSIX only)")


@contextmanager
def rpc_server(reply):
    messages = []

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            for raw in self.rfile:
                message = json.loads(raw)
                messages.append(message)
                if "id" in message or message.get("op") == "observe":
                    self.wfile.write(reply)
                    self.wfile.flush()

    with tempfile.TemporaryDirectory() as directory:
        address = str(Path(directory) / "robot.sock")
        with socketserver.UnixStreamServer(address, Handler) as server:
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                yield address, messages
            finally:
                server.shutdown()
                worker.join(timeout=2)


class TransportTests(unittest.TestCase):
    def test_cleanup_failure_still_closes_socket(self):
        connection = Connection.__new__(Connection)
        connection.file, connection.socket = MagicMock(), MagicMock()
        connection.file.close.side_effect = OSError("broken pipe")
        connection.__exit__(None, None, None)
        connection.socket.close.assert_called_once()

    @requires_unix_sockets
    def test_controller_readiness_wire_format(self):
        reply = (b'{"id":2,"result":{"accepted":true,"walk":"walking.onnx"}}\n'
                 b'{"method":"robot.state","params":{"policy":"held"}}\n'
                 b'{"method":"robot.state","params":{"policy":"stand",'
                 b'"safety":{"fallen":false,"limp":false}}}\n')
        with rpc_server(reply) as (address, messages):
            with Connection(address) as connection:
                connection.wait_ready(1)
        self.assertEqual(messages, [{"jsonrpc": "2.0", "id": 2, "method": "robot.subscribe",
                                     "params": {"hz": 10}}])

    @requires_unix_sockets
    def test_policy_unavailable_fails_readiness(self):
        reply = b'{"id":2,"result":{"accepted":true,"unavailable":"no policy configured"}}\n'
        with rpc_server(reply) as (address, _), Connection(address) as connection:
            with self.assertRaisesRegex(ValueError, "unavailable"):
                connection.wait_ready(1)

    @requires_unix_sockets
    def test_official_enable_and_move_wire_format(self):
        with rpc_server(b'{"jsonrpc":"2.0","id":1,"result":{}}\n') as (address, messages):
            with Connection(address) as connection:
                connection.enable()
                connection.move({"vx": 0.1, "vy": 0, "vyaw": -0.4})
        self.assertEqual(messages, [
            {"jsonrpc": "2.0", "id": 1, "method": "robot.enable", "params": {"on": True}},
            {"jsonrpc": "2.0", "method": "robot.move",
             "params": {"vx": 0.1, "vy": 0, "vyaw": -0.4}},
        ])

    @requires_unix_sockets
    def test_reject_errors_and_missing_acknowledgements(self):
        for response in (b'{"error":"no"}\n', b'{"id":2,"result":{}}\n',
                         b'[]\n', b'{}\n', b'x' * 65537 + b'\n'):
            with rpc_server(response) as (address, _), Connection(address) as connection:
                with self.assertRaises(ValueError):
                    connection.enable()

    @requires_unix_sockets
    def test_observation_request(self):
        with rpc_server(b'{"sim_time":1}\n') as (address, messages):
            with Connection(address) as connection:
                self.assertEqual(connection.observe(), {"sim_time": 1})
        self.assertEqual(messages, [{"op": "observe"}])


class ContactTests(unittest.TestCase):
    def test_onsets_not_contact_points_or_frames(self):
        counter = ContactCounter()
        for active in ({1}, {1}, {1, 2}, set(), {1}):
            counter.update(active)
        self.assertEqual(counter.events, 3)

    def test_only_robot_obstacle_contacts_count(self):
        from types import SimpleNamespace
        model = SimpleNamespace(geom_bodyid=[0, 0, 1, 2])
        data = SimpleNamespace(ncon=5, contact=[
            SimpleNamespace(geom1=0, geom2=2, dist=-0.001),  # floor
            SimpleNamespace(geom1=1, geom2=2, dist=-0.001),  # obstacle
            SimpleNamespace(geom1=3, geom2=1, dist=0),       # same obstacle
            SimpleNamespace(geom1=0, geom2=1, dist=-0.001),  # static scenery
            SimpleNamespace(geom1=1, geom2=2, dist=0.01),    # contact margin only
        ])
        self.assertEqual(touching_obstacles(model, data, {1}), {1})


if __name__ == "__main__":
    unittest.main()
