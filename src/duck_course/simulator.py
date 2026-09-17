"""Adapter for microduck_rl's develop-branch body server (one simulated duck)."""

import json
from pathlib import Path
import socketserver
import threading
import xml.etree.ElementTree as ET


class ContactCounter:
    """Count each obstacle contact onset, not every physics tick or contact point."""

    def __init__(self):
        self.active = set()
        self.events = 0

    def update(self, obstacles: set[int]):
        self.events += len(obstacles - self.active)
        self.active = set(obstacles)


def touching_obstacles(model, data, obstacle_ids: set[int]) -> set[int]:
    touching = set()
    for contact in data.contact[:data.ncon]:
        if contact.dist > 0:
            continue
        a, b = int(contact.geom1), int(contact.geom2)
        for obstacle, other in ((a, b), (b, a)):
            if obstacle in obstacle_ids and model.geom_bodyid[other] != 0:
                touching.add(obstacle)
    return touching


def serve(scene: Path, port: int, telemetry_port: int, headless: bool):
    # The official environment owns MuJoCo, numpy, and the trained locomotion stack.
    try:
        import mujoco
        from mjlab_microduck.sim import body_server as official
    except ImportError as error:
        raise RuntimeError(
            "Run simulate with the microduck_rl develop environment; "
            "it must provide mjlab_microduck.sim.body_server."
        ) from error
    tag = ET.parse(scene).find("custom/text[@name='course_id']")
    if tag is None:
        raise ValueError("generate a scene with the scene command first")
    course_id = tag.get("data")

    class CourseWorld(official.World):
        def __init__(self):
            super().__init__(scene, 1)
            self.counter = ContactCounter()
            self.obstacles = {
                i for i in range(self.model.ngeom)
                if (mujoco.mj_id2name(self.model, mujoco.mjtObj.mjOBJ_GEOM, i)
                    or "").startswith("course_")
            }

        def step(self, times=1):
            for _ in range(times):
                super().step(1)
                with self.lock:
                    self.counter.update(touching_obstacles(
                        self.model, self.data, self.obstacles))

    world = CourseWorld()
    body = official.Body(world, 0)
    body.place(None, official.HOME_TRUNK_Z, offset_y=0.0)
    world.bodies.append(body)
    mujoco.mj_forward(world.model, world.data)

    class Telemetry(socketserver.StreamRequestHandler):
        def handle(self):
            self.connection.settimeout(2.0)
            try:
                while raw := self.rfile.readline(4097):
                    if len(raw) > 4096 or not raw.endswith(b"\n"):
                        return
                    if json.loads(raw) != {"op": "observe"}:
                        return
                    with world.lock:
                        position = world.data.qpos[body.trunk:body.trunk + 3].tolist()
                        quat = world.data.qpos[body.trunk + 3:body.trunk + 7]
                        distances, statuses = body.tof.frame(world.data)
                        sample = {
                            "course_id": course_id,
                            "sim_time": float(world.data.time),
                            "trunk": position,
                            "up_cos": float(1 - 2 * (quat[1] ** 2 + quat[2] ** 2)),
                            "collision_events": world.counter.events,
                            "depth": {"rows": 8, "cols": 8, "distance_mm": distances,
                                      "status": statuses},
                        }
                    self.wfile.write((json.dumps(sample) + "\n").encode())
                    self.wfile.flush()
            except (OSError, ValueError):
                return

    servers, started = [], []
    try:
        server = official.Server(("127.0.0.1", port), official.Handler)
        servers.append(server)
        server.body = body
        telemetry = official.Server(("127.0.0.1", telemetry_port), Telemetry)
        servers.append(telemetry)
        for server in servers:
            threading.Thread(target=server.serve_forever, daemon=True).start()
            started.append(server)
        print(f"Body: 127.0.0.1:{port}; read-only telemetry: {telemetry_port}", flush=True)
        official.run(world, headless=headless)
    finally:
        for server in servers:
            # shutdown must only be called after serve_forever has started.
            if server in started:
                server.shutdown()
            server.server_close()
