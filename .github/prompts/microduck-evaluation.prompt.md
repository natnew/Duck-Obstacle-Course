---
name: "microduck-evaluation"
description: "Use when: evaluating the MicroDuck obstacle-course baseline end to end. Runs tests and a seeded (>=5 seeds) deterministic evaluation, audits the implementation and results with parallel and sequential subagents, reconciles findings and writes a dated report in reports/. Read-only with respect to production code."
argument-hint: "Optional: seeds (default 0-9), e.g. seeds=0 1 2 3 4"
agent: "agent"
---

# MicroDuck evaluation workflow

You are the **orchestrator** of a multi-stage experimental evaluation of this
repository's MicroDuck navigation baseline. Run the stages below in order,
running stages in parallel where the dependency graph allows it, and finish with
one dated Markdown report.

The repository implements the **MicroDuck obstacle course**: reactive depth
navigation with the `clearance` and `right-hand` strategies. It has **no Sumo
variant**. Name the system accurately everywhere. If a later revision does add a
Sumo implementation, evaluate what exists and say what changed.

## Non-negotiable rules

1. **No production changes.** Do not edit, create or delete anything under
   `src/`, `tests/`, `configs/`, `pyproject.toml` or `README.md`. The only
   writes allowed are `results/eval-*/` (git-ignored artefacts) and the final
   report under `reports/`.
2. **No fabrication.** Every number in the report must trace to a file under
   `results/eval-<stamp>/` or to verbatim command output you captured. If a
   stage cannot run, report it as **not executed**, with the exact command and
   error. Do not estimate, substitute or back-fill values.
3. **Label the evidence.** Tag every finding **[Observed]** (it comes directly
   from command output or an artefact) or **[Inferred]** (it is reasoning from
   observations). Say which observations each inference rests on.
4. **Proxy is not locomotion.** `scripts/microduck_evaluation.py` runs a 2-D
   kinematic proxy that drives the real `ReactivePolicy`, `sectors()` and
   `Episode` code. It contains no legs, balance, falls, slip, latency or
   upstream ONNX policies. Never present proxy outcomes as MicroDuck crossing
   results.
5. **No overwrites.** Never overwrite an existing `results/eval-*` directory or
   report.

## Stage graph

```text
S0 Preflight ──► S1 Recon ──┬─► S2a Tests ────────┐
                            ├─► S2b Seeded eval ──┼─► S3b Results analyst ─┐
                            └─► S3a Implementation auditor ─────────────────┼─► S4 Reconciler ─► S5 Report + guard
```

- S2a, S2b and S3a are mutually independent: **launch them in parallel**.
- S3b waits for S2a **and** S2b. S4 waits for S3a **and** S3b. S5 waits for S4.
- S3a must **not** receive any test or evaluation results, so that its audit
  stays independent of the outcomes.

Subagents: in Copilot CLI and agent-host sessions, use the `task` tool with the
`agent_type` named below. In native VS Code chat, use the subagent tool
(`#tool:agent`/`runSubagent`). If a named custom agent is unavailable, fall back
to `general-purpose` and record the substitution in the report. Give every
subagent the full context it needs; subagents do not share your memory.

---

## S0 — Preflight (orchestrator)

Record verbatim:

- `git rev-parse HEAD`, `git branch --show-current`, `git status --porcelain`,
  and `git log --oneline -5`.
- A protected-path snapshot taken before any work. Store
  `git status --porcelain -- src tests configs pyproject.toml README.md` and the
  SHA-256 of every file under those paths in
  `results/eval-<stamp>/preflight-snapshot.json`.
- The OS and shell, plus `python --version` (3.12 or later is required).
- Whether `mujoco` imports.
- Whether a live simulator stack is reachable. That needs the `RL`, `RUNTIME` and
  `DUCK_SIM_STATE` environment variables plus an existing robotd socket. Do not
  start or download upstream components.

Use one UTC timestamp, `<stamp>` = `YYYYMMDD-HHMMSS`, for every artefact in the
run.

## S1 — Recon (orchestrator)

Read `README.md`, `AGENTS.md` (note it if absent), `pyproject.toml`,
`configs/baseline.json`, everything under `src/duck_course/`, `tests/` and
`scripts/microduck_evaluation.py`. Establish and write down:

- **Experimental baseline:** the strategies, the policy and evaluation
  parameters from `configs/baseline.json` with their SHA-256, the fixed course
  plus seeded layouts, and the goal, collision, fall and stall definitions.
- **Exact commands** for this machine's shell:
  - Tests, POSIX: `PYTHONPATH="$PWD/src" python -m unittest discover -s tests -v`
  - Tests, PowerShell: `$env:PYTHONPATH="$PWD\src"; python -m unittest discover -s tests -v`
  - Seeded evaluation:
    `python scripts/microduck_evaluation.py --seeds <seeds> --output results/eval-<stamp>/offline`,
    run with the same `PYTHONPATH`.
  - Full closed-loop episodes, only if S0 found a live simulator: the README's
    `scene`, `simulate`, robotd and `run` sequence, one trial per seed and
    strategy, restarting the simulator and robotd before every trial.
- **Seeds:** from the prompt argument if given, otherwise `0 1 2 3 4 5 6 7 8 9`
  (the README protocol). The harness always adds the fixed course and refuses
  fewer than 5 distinct seeds.

Pass this recon summary to every downstream subagent.

## S2a — Tests (`task` agent, parallel)

Prompt the agent to run the test command from S1, capture the full verbatim
output to `results/eval-<stamp>/tests.log`, and return:

- the totals ran / passed / failed / errored / skipped;
- each non-pass with its test id, its exception type and message, and a
  one-line root cause **in the agent's words, marked as inference**;
- whether any failure is platform-dependent. For example,
  `socketserver.UnixStreamServer` and AF_UNIX tests error on Windows, and the
  MuJoCo test skips without `mujoco`.

The agent must not edit any file to make tests pass.

## S2b — Seeded evaluation (`task` agent, parallel)

Prompt the agent to:

1. Run the seeded-evaluation command from S1. It writes `environment.json`,
   `layouts.json`, `geometry.json`, `determinism.json`, `proxy-trials.json`,
   `proxy-summary.json` and `manifest.json`.
2. Run it a **second time** into `results/eval-<stamp>/offline-repeat`. Then
   compare the SHA-256 hashes of every artefact except `environment.json`
   between the two runs, and save the comparison to
   `results/eval-<stamp>/cross-run.json`.
3. If, and only if, S0 found a live simulator, run the closed-loop episodes and
   `python -m duck_course summarize` into `results/eval-<stamp>/closed-loop/`.
   Otherwise write `results/eval-<stamp>/closed-loop/NOT_EXECUTED.md` with the
   reason.
4. Return the artefact paths, exit codes, verbatim stdout and stderr tails, and
   any deviation from the planned commands.

## S3a — Implementation auditor (`evaluation-quality-engineer`, parallel, independent)

Give it the S1 recon summary and the file list, and **no results**. Ask it to
inspect `src/`, `tests/`, `configs/` and `scripts/microduck_evaluation.py` for
experimental and evaluation flaws. Areas to probe:

- metric definitions in `summarize`: denominators, `null` handling, and mixing
  scored with unscored episodes;
- terminal-state precedence in `Episode.update`: timeout before out-of-bounds,
  fall handling inside the startup grace period, and stall-anchor resets;
- whether `ReactivePolicy` latching and hysteresis can deadlock or oscillate;
- the depth reduction in `sectors()`: row band, column split, no-hit
  semantics, and failing closed;
- the seed perturbation range against corridor and obstacle geometry, and
  whether `random.Random(seed)` is stable across Python versions;
- leakage of simulator truth into navigation;
- test coverage against stated behaviour, platform coupling (AF_UNIX), and
  untested branches;
- the validity limits of the kinematic proxy: its assumptions in
  `ProxyAssumptions` and what it cannot detect.

Each finding needs a severity (High/Medium/Low), `file:line` evidence, why it
matters for experimental validity, and an [Observed] or [Inferred] tag. It must
not modify files.

## S3b — Results analyst (`general-purpose`, after S2a and S2b)

Give it the S2a and S2b returns and the artefact paths, but **not** the S3a
findings. Ask it to read the artefacts directly and report:

- the per-strategy outcomes from `proxy-summary.json`, with counts beside rates;
- paired per-seed comparisons of `clearance` against `right-hand` (status,
  `elapsed_s`, collisions and action counts, matched on `course_id`);
- uncertainty. With n ≤ 11 courses per strategy, give exact counts and a Wilson
  95 % interval for any rate. Where outcomes differ, use a paired sign test or
  exact binomial on the discordant seeds. State plainly when n is too small to
  support a claim;
- determinism: the in-process checks and the cross-run hash equality;
- geometry: the minimum widest lateral gap per seed against the proxy robot
  diameter, and seeds where geometry and outcome disagree;
- test outcomes, separating platform-caused failures from logic failures;
- which questions these data **cannot** answer, such as real locomotion,
  falls, sensor noise and contact physics.

Each finding is tagged [Observed] or [Inferred] and cites the artefact and
field. The analyst may run read-only Python over the artefacts but must not
re-run the evaluation.

## S4 — Reconciler (`rubber-duck`, after S3a and S3b)

Give it both reports verbatim. Ask it to produce:

- **agreements**, where an implementation flaw explains a result pattern;
- **conflicts**, where the auditor predicts a failure the results do not show
  or the reverse, with a likely explanation (for example, that the proxy
  cannot exercise that code path);
- **unsupported claims** from either agent, downgraded or removed;
- a **deduplicated, prioritised** finding list (High/Medium/Low), each with its
  evidence tag and source agent or agents;
- **reproducibility issues**, as a consolidated list;
- **recommendations**, ordered by impact on experimental validity, each with a
  concrete next action. Each must say whether it would change production
  code; this workflow never applies such changes.

## S5 — Report and integrity guard (orchestrator)

1. **Guard.** Recompute the protected-path snapshot from S0 and compare. If
   anything under `src/`, `tests/`, `configs/`, `pyproject.toml` or
   `README.md` changed, stop, report the violation at the top of the report,
   and do not revert silently. Ask the user.
2. **Write** `reports/<YYYY-MM-DD>-microduck-evaluation.md`, using the local
   date. If that file exists, append `-<HHMMSS>`. Never overwrite. Use British
   English, and include **all** sections below in this order:

```markdown
# MicroDuck obstacle-course evaluation — <YYYY-MM-DD>

> Scope: <one paragraph: what was evaluated, what was not, proxy vs closed-loop>

## 1. Repository state
Commit, branch, dirty paths, Python, OS, MuJoCo availability, simulator availability,
config path + SHA-256, artefact directory.

## 2. Tests executed
Exact command; totals table (ran/passed/failed/errors/skipped); each non-pass with
cause and whether platform-dependent.

## 3. Experiments executed
Table: experiment | command | executed? | artefact path | exit code.
Include offline harness, repeat run, closed-loop (or NOT EXECUTED + reason).

## 4. Seeds
List (incl. fixed course), source of the list, course_id per seed, distinct-layout count.

## 5. Results
Per-strategy table with counts and Wilson 95 % intervals; per-seed paired table;
determinism and cross-run reproducibility results; geometry summary.
Label every table "Kinematic proxy" or "Closed-loop MicroDuck" explicitly.

## 6. Failures
Every failed, errored, skipped or not-executed item with reason. "None" only if none.

## 7. Implementation findings
Reconciled, prioritised list: severity | finding | evidence (file:line / artefact) |
tag [Observed]/[Inferred] | source agent(s).

## 8. Reproducibility issues
Platform coupling, missing upstream pins, manual steps, nondeterminism, environment gaps.

## 9. Recommendations
Ordered; each with rationale, expected effect, and whether it touches production code.

## 10. Observed evidence vs inference
Two explicit lists: what was directly observed (with artefact references) and what is
inferred (with the observations it rests on). Note agent disagreements and how resolved.

## Appendix
Subagents used (and any fallbacks), stage timings, full artefact manifest hashes.
```

3. **Verify** the report. Every section is present and non-empty, every number
   appears in a cited artefact, and nothing calls proxy results MicroDuck
   locomotion performance.
4. **Reply** to the user with the report path, a five-line summary, the top
   three findings, and anything that needs their decision. Do not commit
   anything unless the user asks.
