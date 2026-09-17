import argparse
import json
from pathlib import Path

from duck_course.evaluation import summarize
from duck_course.runtime import run_episode
from duck_course.scenes import layout, write_scene


def main():
    parser = argparse.ArgumentParser(description="MicroDuck simulation-only depth baseline")
    commands = parser.add_subparsers(dest="command", required=True)
    scene = commands.add_parser("scene", help="generate MJCF and a matching JSON layout")
    scene.add_argument("--robot", type=Path, required=True)
    scene.add_argument("--output", type=Path, required=True)
    scene.add_argument("--seed", type=int, help="omit for the fixed milestone course")
    simulator = commands.add_parser("simulate", help="run the official body with contact telemetry")
    simulator.add_argument("--scene", type=Path, required=True)
    simulator.add_argument("--port", type=int, default=7801)
    simulator.add_argument("--telemetry-port", type=int, default=7802)
    simulator.add_argument("--headless", action="store_true")
    run = commands.add_parser("run", help="drive a SIMULATED robotd; never use a hardware socket")
    run.add_argument("--layout", type=Path, required=True)
    run.add_argument("--robot-socket", required=True)
    run.add_argument("--telemetry-port", type=int, default=7802)
    run.add_argument("--strategy", choices=["clearance", "right-hand"], default="clearance")
    run.add_argument("--config", type=Path)
    run.add_argument("--output", type=Path, required=True)
    summary = commands.add_parser("summarize", help="compare recorded episodes by strategy")
    summary.add_argument("results", type=Path, nargs="+")
    args = parser.parse_args()
    try:
        if args.command == "scene":
            print(write_scene(args.robot, args.output, layout(args.seed)))
        elif args.command == "simulate":
            from duck_course.simulator import serve
            serve(args.scene.resolve(), args.port, args.telemetry_port, args.headless)
        elif args.command == "run":
            config = json.loads(args.config.read_text()) if args.config else {}
            # Check the output before enabling locomotion; never silently overwrite a trial.
            args.output.parent.mkdir(parents=True, exist_ok=True)
            with args.output.open("x") as output:
                result = run_episode(json.loads(args.layout.read_text()), args.robot_socket,
                                     args.telemetry_port, args.strategy, config)
                json.dump(result, output, indent=2, allow_nan=False)
                output.write("\n")
            print(result["status"])
            return 0 if result["status"] == "success" else 1
        else:
            print(json.dumps(summarize([json.loads(p.read_text()) for p in args.results]),
                             indent=2, allow_nan=False))
    except (OSError, ValueError, RuntimeError, KeyError, TypeError) as error:
        parser.exit(2, f"error: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
