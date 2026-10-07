# Duck Obstacle Course 🦆🚧

A small MicroDuck navigation experiment: **one duck, one course, reactive depth
control, no global map**. A simple baseline comes before learned navigation.

**Status:** baseline implementation and automated tests are available. A successful
end-to-end MicroDuck crossing has **not yet been demonstrated**. The tests validate
navigation logic, protocol handling, scene compilation, and contact detection—not
the trained locomotion policy's ability to finish a course.

## What it does

- Generates a fixed MuJoCo course with two boxes, side walls, and a finish marker;
  optional seeds perturb obstacle positions without blocking the entire corridor.
- Reduces the official simulated 8×8 ToF sensor to left/forward/right distances.
- Compares `clearance` (turn toward the clearer side) and `right-hand` (prefer a
  right turn when blocked ahead) reactive strategies.
- Sends forward/turn/stop commands to the official runtime. MuJoCo joint control
  and balance stay with MicroDuck's existing trained **locomotion** policies;
  there is no learned **navigation** controller here.
- Detects goal completion, obstacle/wall contacts, falls, stalls, timeout,
  out-of-bounds movement, and sensor/runtime failure. Writes per-trial JSON and
  aggregate strategy metrics.

```text
CLEAR             → FORWARD
BLOCKED LEFT      → TURN RIGHT
BLOCKED RIGHT     → TURN LEFT
BLOCKED AHEAD     → TURN toward clearance (or right-hand baseline)
INVALID DEPTH     → STOP / FAIL
FALLEN            → RECOVER (zero velocity, bounded wait)
GOAL REACHED      → DONE
```

Turns are latched until all sectors exceed the release threshold, reducing
left/right chatter. Navigation receives depth only. Simulator pose and contact
truth are reserved for evaluation and safety overrides, never goal steering.

## Local tests

Python 3.12+ is sufficient for the core; it has no third-party dependencies.
There is no package installation or build step. Set `COURSE` to this repository's
absolute path:

```sh
export COURSE=/home/runner/work/Duck-Obstacle-Course/Duck-Obstacle-Course
export PYTHONPATH="$COURSE/src${PYTHONPATH:+:$PYTHONPATH}"
python -m unittest discover -s "$COURSE/tests" -v
python -m duck_course --help
```

The optional engine test runs when MuJoCo is installed; otherwise it is explicitly
skipped. Run the same suite using the official RL environment's Python to include
it. It uses a tiny test body, not a substitute MicroDuck controller. There was no
existing lint/build configuration; no extra lint or test framework is required.

## Official simulator prerequisites

Follow the [official simulation guide][simulation] first and confirm that an
unmodified duck can stand and walk. You need separate, user-managed checkouts of:

1. [MicroDuck runtime][runtime], built with its ONNX locomotion policies.
2. [MicroDuck RL][rl], with its environment and
   `mjlab_microduck.sim.body_server` available.

The adapter was written against RL **develop**, commit
`cb70b792312d559a4da09064d92009079671815f`. The inspected `main` branch did not
provide this body server. Its Python classes are upstream implementation APIs,
not a stable public SDK; check compatibility when updating. No upstream assets,
weights, source, or environments are downloaded automatically or vendored here.

**Simulation only. Never point this runner at a physical robot's socket.**
It does not establish that a supplied robotd socket belongs to the body being
scored; the operator must start that daemon with the matching `--sim` endpoint.
Use a dedicated local runtime directory. Both simulator ports bind to loopback.

## Run one fixed course (Linux)

Use absolute paths for `RL` and `RUNTIME` below. Set these variables and
`PYTHONPATH` in each terminal, or use equivalent absolute arguments.

```sh
export RL=/absolute/path/to/microduck_rl
export RUNTIME=/absolute/path/to/microduck
export DUCK_SIM_RL="$RL"
export DUCK_SIM_STATE="$HOME/.cache/duck-course"
```

**Once, bootstrap the official runtime:** run `"$RUNTIME/scripts/duck-sim"` and
confirm its normal standing/walking behavior, then run
`"$RUNTIME/scripts/duck-sim" down`. This builds the daemons and leaves
`"$DUCK_SIM_STATE/robotd-duck-a.toml"` with the official policy paths.
Do not leave the stock body running: the instrumented body below replaces it.

Generate the course and matching layout manifest:

```sh
python -m duck_course scene \
  --robot "$RL/src/mjlab_microduck/robot/microduck/robot_allcollisions.xml" \
  --output "$COURSE/results/fixed.xml"
```

**Terminal 1 — physics:** run our adapter in the existing RL environment:

```sh
"$RL/.venv/bin/python" -m duck_course simulate \
  --scene "$COURSE/results/fixed.xml" --headless
```

Omit `--headless` for the viewer. This uses the official `World`, `Body`, body
protocol server, and real-time stepping loop, with a contact counter and a
read-only telemetry endpoint added. Start is the official `HOME` pose at `(0, 0)`;
the body is held until the daemon enables it.

**Terminal 2 — locomotion:** start only the official robot daemon against that
body. `ORT_DYLIB_PATH` must name your RL environment's actual ONNX runtime library,
as described in the official guide:

```sh
export ORT_DYLIB_PATH=/absolute/path/to/libonnxruntime.so
DUCK_RUNTIME_DIR="$DUCK_SIM_STATE" \
  "$RUNTIME/target/debug/robotd" --sim 127.0.0.1:7801 \
  --params "$DUCK_SIM_STATE/robotd-duck-a.toml" \
  --socket "$DUCK_SIM_STATE/duck-a.sock"
```

**Terminal 3 — navigation and scoring:**

```sh
python -m duck_course run \
  --layout "$COURSE/results/fixed.json" \
  --robot-socket "$DUCK_SIM_STATE/duck-a.sock" \
  --config "$COURSE/configs/baseline.json" \
  --strategy clearance --output "$COURSE/results/trial-fixed-clearance.json"
```

The runner enables the policy through `robot.enable`, verifies policy availability
and live standing/walking controller execution through `robot.subscribe`, then sends
`robot.move` at 10 Hz (`vx` m/s, `vyaw` left-positive rad/s). Missing policies or a
controller that fails to become ready within `startup_s` are runtime failures,
not scored navigation stalls. Depth comes from the **same official
ToF ray caster** used by simulated `tofd`, via the telemetry endpoint; running
`tofd` separately is not required. Stock `duck-body` alone does not expose
collision counters and cannot replace the instrumented adapter for scoring.

A result file is never overwritten. Exit codes: `0` success, `1` recorded
unsuccessful trial, `2` setup/argument error. Stop the manually launched daemon
and simulator with Ctrl-C after a trial. `duck-sim down` does not manage them.

## Evaluation across layouts

Preserve the fixed course as the regression baseline. Generate randomized courses
with `scene --seed N`, using a different output name for each seed. The XML and
JSON files are a pair; the runner checks their layout identity against telemetry.

For each of seeds `0` through `9`, run both `clearance` and `right-hand` using the
same configuration and official locomotion policies. **Restart both simulator
and robotd before every trial**, including strategy changes: the official body
protocol has no reset operation. Generation and aggregation are automated;
process restarts and launching each trial are currently manual.

Save each result with a unique `trial-*.json` name, then compare:

```sh
python -m duck_course summarize "$COURSE"/results/trial-*.json
```

Reports include success rate, collision-free rate, upright rate, mean elapsed
time, mean collision onsets, terminal-state counts, and distinct layout count.
Success rate includes all attempts. Collision/upright/time metrics include only
completed scored episodes, not interrupted trials or failed telemetry connections;
those rates are `null` when nothing was scored. Do not mix configurations or
upstream policy versions in a comparison.

Individual results preserve the layout, seed, configuration, action trace,
elapsed simulated/wall time, distance travelled, fall count, contact count, and
failure reason. Results are local and git-ignored; no fabricated benchmark
numbers or claims of successful locomotion are included.

## Agent-driven evaluation workflow

`/microduck-evaluation` ([prompt file](.github/prompts/microduck-evaluation.prompt.md))
is a VS Code Copilot workflow that runs the test suite and a seeded evaluation
(at least 5 seeds; default `0`–`9` plus the fixed course). Parallel subagents then
audit the implementation and analyse the results, and a final agent reconciles
their findings. The result is a dated report in `reports/`. The workflow does not
modify `src/`, `tests/` or `configs/`, and it reports experiments it cannot run
as not executed rather than estimating them.

Without the official simulator stack, the evaluation uses
[`scripts/microduck_evaluation.py`](scripts/microduck_evaluation.py). This is a
deterministic **2-D kinematic proxy**: it drives the real `ReactivePolicy`,
`sectors()` and `Episode` code with synthetic ray-cast depth. It checks layout
determinism, course geometry and navigation logic. It is **not** evidence of
MicroDuck locomotion, balance or contact behaviour.

```sh
PYTHONPATH="$COURSE/src" python scripts/microduck_evaluation.py \
  --seeds 0 1 2 3 4 --output "$COURSE/results/eval-manual"
```

Reports and results are git-ignored.

## Definitions and limitations

- **Depth:** millimetres, row-major 8×8; column zero is left. Statuses 5 and 9
  are valid; noisy valid hits beyond the nominal range are saturated at 4 m.
  In this simulator only, status 255 with distance zero is a no-hit
  ray, represented as 4 m. Other invalid samples fail closed. Rows 1–4 limit
  ground/self returns; this heuristic needs tuning against actual head posture.
  Do not reuse the no-hit interpretation for real hardware.
- **Collision:** an onset of contact between any robot geometry and a course
  obstacle/wall, counted at each physics step; persistent contact counts once.
  Floor contacts, robot self-contacts, and positive-distance contact margins are
  excluded. Separation followed by recontact counts again. Use the official
  `robot_allcollisions.xml`, not the ground-contact-only model.
- **Fall/recovery:** trunk height below 0.075 m or trunk-up cosine below 0.5.
  A startup grace period allows standing. Recovery sends zero velocity while
  leaving the official standing policy enabled; if it cannot recover within the
  configured window, the episode fails. There is no invented get-up RPC or
  guaranteed self-righting behavior.
- **Stall:** no 5 cm displacement from the last progress anchor for 10 seconds,
  including spinning in place. A separate episode timeout bounds loops.
- **Goal:** upright trunk crosses `x = 2.8 m` inside the side-wall bounds.
  A successful crossing can still have recorded collisions or recovered falls;
  evaluate all metrics, not just success.
- **Safety:** malformed/stale telemetry, transport timeouts, and Ctrl-C attempt a
  final zero command. Reads are bounded to 0.2 s; loss of the socket relies on
  robotd's default 500 ms velocity deadman. Keep that deadman enabled.
- **Fidelity:** this is a narrow-field reactive experiment, not a path planner.
  It can turn away from the finish, get stuck, miss low obstacles, or fail to
  balance. Random layouts maintain geometric room, not a proof of navigability.
  Real-time simulator pacing and upstream policy compatibility matter.

## Repository

```text
src/duck_course/
  sensing/       depth validation and sector reduction
  navigation/    deterministic reactive strategies and velocity commands
  scenes/        fixed/seeded layouts and MJCF generation
  evaluation/    terminal states and strategy summaries
  simulator.py   official body integration and contact telemetry
  runtime.py     fail-safe runtime client and episode execution
configs/         conservative baseline settings
scripts/         offline seeded evaluation harness (kinematic proxy)
.github/prompts/ /microduck-evaluation agent workflow
reports/         ignored dated evaluation reports
tests/           standard-library unit, protocol, and optional MuJoCo tests
results/         ignored generated courses and evaluation records
```

## Resources and licence

- [MicroDuck product and ecosystem](https://pollen-robotics.com/microduck/)
- [MicroDuck runtime][runtime] · [MicroDuck RL][rl]
- [Simulation guide][simulation] · [MicroDuck documentation][docs]

MIT. See [LICENSE](LICENSE). Upstream assets and policies retain their own licences.

Independent community project built on the open-source MicroDuck ecosystem.
Not an official Pollen Robotics project.

[runtime]: https://github.com/pollen-robotics/microduck
[rl]: https://github.com/pollen-robotics/microduck_rl
[simulation]: https://github.com/pollen-robotics/microduck/blob/main/docs/robot/simulation.md
[docs]: https://github.com/pollen-robotics/microduck/tree/main/docs
