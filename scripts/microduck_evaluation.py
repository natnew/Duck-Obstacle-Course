"""Offline, deterministic evaluation harness for the /microduck-evaluation workflow.

Imports the repository's navigation, sensing, scene and evaluation code read-only
and writes artefacts under results/ (git-ignored). It never modifies src/.

What it measures:
  * layout determinism and course-identity stability per seed;
  * course geometry per seed (lateral gaps, longitudinal spacing);
  * a 2-D KINEMATIC PROXY episode per (seed, strategy): see duck_course.proxy.
    This is NOT MicroDuck locomotion: there are no legs, balance, falls, slip,
    latency or upstream policies. Proxy outcomes describe the reactive
    navigation logic only.

Usage:
  PYTHONPATH=src python scripts/microduck_evaluation.py --seeds 0 1 2 3 4 \
      --output results/eval-YYYYMMDD-HHMMSS
"""

from __future__ import annotations

import argparse
from dataclasses import asdict
import hashlib
import json
from pathlib import Path
import platform
import subprocess
import sys

from duck_course.evaluation import summarize
from duck_course.proxy import STRATEGIES, configs, geometry, proxy_episode
from duck_course.scenes import identity, layout


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
    policy_cfg, eval_cfg, assume = configs(config)
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