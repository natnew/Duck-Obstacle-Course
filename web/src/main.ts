import { Engine, PYODIDE_VERSION, type LoadStage } from "./engine";
import { CourseRenderer } from "./renderer";
import { RULES, activeRule, describeStatus } from "./rules";
import type { Frame, Strategy, Trial, TrialResult } from "./types";

const SEED_COUNT = 100;
const SIM_HZ = 10;

function $<T extends HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) {
    throw new Error(`missing element #${id}`);
  }
  return element as T;
}

const ui = {
  body: document.body,
  canvas: $<HTMLCanvasElement>("course"),
  scrub: $<HTMLInputElement>("scrub"),
  play: $<HTMLButtonElement>("play"),
  stepBack: $<HTMLButtonElement>("step-back"),
  stepForward: $<HTMLButtonElement>("step-forward"),
  speed: $<HTMLSelectElement>("speed"),
  clock: $<HTMLSpanElement>("clock"),
  form: $<HTMLFormElement>("episode-form"),
  seed: $<HTMLSelectElement>("seed"),
  strategy: $<HTMLSelectElement>("strategy"),
  run: $<HTMLButtonElement>("run"),
  action: $<HTMLElement>("action"),
  latched: $<HTMLElement>("latched"),
  sectorLeft: $<HTMLElement>("sector-left"),
  sectorForward: $<HTMLElement>("sector-forward"),
  sectorRight: $<HTMLElement>("sector-right"),
  pose: $<HTMLElement>("pose"),
  contacts: $<HTMLElement>("contacts"),
  status: $<HTMLElement>("status"),
  rules: $<HTMLTableElement>("rules"),
  result: $<HTMLElement>("result"),
  resultStatus: $<HTMLElement>("result-status"),
  resultElapsed: $<HTMLElement>("result-elapsed"),
  resultDistance: $<HTMLElement>("result-distance"),
  resultCollisions: $<HTMLElement>("result-collisions"),
  resultSteps: $<HTMLElement>("result-steps"),
  resultCourse: $<HTMLElement>("result-course"),
  resultTrace: $<HTMLElement>("result-trace"),
  sweepForm: $<HTMLFormElement>("sweep-form"),
  sweepMax: $<HTMLInputElement>("sweep-max"),
  sweepFixed: $<HTMLInputElement>("sweep-fixed"),
  sweepRun: $<HTMLButtonElement>("sweep-run"),
  sweepProgress: $<HTMLProgressElement>("sweep-progress"),
  sweepOutput: $<HTMLElement>("sweep-output"),
  buildInfo: $<HTMLElement>("build-info"),
  loadingStage: $<HTMLElement>("loading-stage"),
};

interface State {
  engine: Engine | null;
  trial: Trial | null;
  frame: number;
  playing: boolean;
  carry: number;
  lastTick: number | null;
}

const state: State = { engine: null, trial: null, frame: 0, playing: false, carry: 0, lastTick: null };
const renderer = new CourseRenderer(ui.canvas);

function seedFromSelect(): number | null {
  return ui.seed.value === "fixed" ? null : Number(ui.seed.value);
}

function strategyFromSelect(): Strategy {
  return ui.strategy.value === "right-hand" ? "right-hand" : "clearance";
}

function populateSeeds(): void {
  for (let seed = 0; seed < SEED_COUNT; seed += 1) {
    const option = document.createElement("option");
    option.value = String(seed);
    option.textContent = `seed ${seed}`;
    ui.seed.appendChild(option);
  }
}

function buildRulesTable(): void {
  const body = ui.rules.tBodies[0];
  if (!body) {
    return;
  }
  for (const rule of RULES) {
    const row = document.createElement("tr");
    row.dataset.rule = rule.id;
    const condition = document.createElement("td");
    condition.textContent = rule.condition;
    const action = document.createElement("td");
    action.textContent = rule.action;
    row.append(condition, action);
    body.appendChild(row);
  }
}

function metres(value: number): string {
  return `${value.toFixed(2)} m`;
}

function sectorClass(value: number, blocked: number, clear: number): string {
  return value < blocked ? "blocked" : value < clear ? "caution" : "ok";
}

function setText(element: HTMLElement, text: string, className = ""): void {
  element.textContent = text;
  element.className = className;
}

function showFrame(index: number): void {
  const { trial } = state;
  if (!trial) {
    return;
  }
  const frames = trial.result.frames;
  const clamped = Math.max(0, Math.min(index, frames.length - 1));
  state.frame = clamped;
  const frame = frames[clamped];
  if (!frame) {
    return;
  }
  const previous = frames[clamped - 1];
  renderer.draw(trial, clamped);
  ui.scrub.value = String(clamped);
  ui.clock.textContent = `t = ${frame.t.toFixed(1)} s · frame ${clamped}/${frames.length - 1}`;
  updateStatePanel(trial, frame, previous);
  const last = clamped === frames.length - 1;
  ui.result.hidden = !last;
  if (last) {
    state.playing = false;
    ui.play.textContent = "Replay";
    ui.play.setAttribute("aria-pressed", "false");
  }
}

function updateStatePanel(trial: Trial, frame: Frame, previous: Frame | undefined): void {
  const { blocked_m, clear_m } = trial.config.policy;
  setText(ui.action, frame.action ? frame.action.toUpperCase() : "—");
  setText(ui.latched, frame.latched ? frame.latched.toUpperCase() : "none");
  setText(ui.sectorLeft, metres(frame.sectors.left), sectorClass(frame.sectors.left, blocked_m, clear_m));
  setText(ui.sectorForward, metres(frame.sectors.forward), sectorClass(frame.sectors.forward, blocked_m, clear_m));
  setText(ui.sectorRight, metres(frame.sectors.right), sectorClass(frame.sectors.right, blocked_m, clear_m));
  const headingDeg = ((frame.heading * 180) / Math.PI).toFixed(0);
  setText(ui.pose, `x ${frame.x.toFixed(2)}  y ${frame.y.toFixed(2)}  θ ${headingDeg}°`);
  setText(ui.contacts, String(frame.collisions), frame.collisions > 0 ? "blocked" : "");
  const statusClass = frame.status === "success" ? "ok" : frame.status === "running" ? "" : "blocked";
  setText(ui.status, describeStatus(frame.status), statusClass);
  const rule = activeRule(frame, previous, trial.config.policy);
  for (const row of ui.rules.querySelectorAll<HTMLTableRowElement>("tbody tr")) {
    row.classList.toggle("active", row.dataset.rule === rule);
  }
}

function showResult(trial: Trial): void {
  const { result } = trial;
  setText(ui.resultStatus, describeStatus(result.status), result.status === "success" ? "ok" : "blocked");
  setText(ui.resultElapsed, `${result.elapsed_s.toFixed(1)} s`);
  setText(ui.resultDistance, metres(result.distance_m));
  setText(ui.resultCollisions, String(result.collision_events), result.collision_events > 0 ? "blocked" : "ok");
  setText(ui.resultSteps, String(result.steps));
  setText(ui.resultCourse, result.course_id.slice(0, 12), "mono");
  setText(ui.resultTrace, result.action_trace_sha256.slice(0, 12), "mono");
}

function setPlaying(playing: boolean): void {
  if (!state.trial) {
    return;
  }
  const frames = state.trial.result.frames;
  if (playing && state.frame >= frames.length - 1) {
    showFrame(0);
  }
  state.playing = playing;
  state.lastTick = null;
  state.carry = 0;
  ui.play.textContent = playing ? "Pause" : state.frame >= frames.length - 1 ? "Replay" : "Play";
  ui.play.setAttribute("aria-pressed", String(playing));
}

function tick(now: number): void {
  if (state.playing && state.trial) {
    const speed = Number(ui.speed.value) || 1;
    const elapsed = state.lastTick === null ? 0 : (now - state.lastTick) / 1000;
    state.lastTick = now;
    state.carry += elapsed * SIM_HZ * speed;
    const advance = Math.floor(state.carry);
    if (advance > 0) {
      state.carry -= advance;
      showFrame(state.frame + advance);
    }
  }
  requestAnimationFrame(tick);
}

function updateUrl(seed: number | null, strategy: Strategy): void {
  const url = new URL(window.location.href);
  url.searchParams.set("seed", seed === null ? "fixed" : String(seed));
  url.searchParams.set("strategy", strategy);
  window.history.replaceState(null, "", url);
}

function readUrl(): { seed: string; strategy: Strategy } | null {
  const params = new URLSearchParams(window.location.search);
  const seed = params.get("seed");
  const strategy = params.get("strategy");
  if (seed === null) {
    return null;
  }
  const valid = seed === "fixed" || (/^\d+$/.test(seed) && Number(seed) < SEED_COUNT);
  return {
    seed: valid ? seed : "fixed",
    strategy: strategy === "right-hand" ? "right-hand" : "clearance",
  };
}

function runEpisode(seed: number | null, strategy: Strategy, autoplay = true): void {
  if (!state.engine) {
    return;
  }
  ui.seed.value = seed === null ? "fixed" : String(seed);
  ui.strategy.value = strategy;
  let trial: Trial;
  try {
    trial = state.engine.trial(seed, strategy);
  } catch (error) {
    const message = error instanceof Error ? error.message.split("\n").at(-1) ?? error.message : String(error);
    setText(ui.status, `Episode failed: ${message}`, "blocked");
    return;
  }
  state.trial = trial;
  ui.scrub.max = String(trial.result.frames.length - 1);
  ui.scrub.disabled = false;
  ui.play.disabled = false;
  ui.stepBack.disabled = false;
  ui.stepForward.disabled = false;
  showResult(trial);
  showFrame(0);
  ui.result.hidden = true;
  updateUrl(seed, strategy);
  setPlaying(autoplay);
}

function formatRate(value: number | null): string {
  return value === null ? "—" : `${(value * 100).toFixed(1)} %`;
}

function renderSweep(trials: TrialResult[], seeds: (number | null)[], seconds: number): void {
  if (!state.engine) {
    return;
  }
  const summary = state.engine.summarize(trials);
  const table = document.createElement("table");
  table.innerHTML = `
    <thead><tr>
      <th scope="col">Strategy</th><th scope="col">Courses</th><th scope="col">Success</th>
      <th scope="col">Collision-free</th><th scope="col">Mean elapsed</th><th scope="col">Statuses</th>
    </tr></thead>`;
  const body = document.createElement("tbody");
  for (const strategy of ["clearance", "right-hand"] as const) {
    const row = summary[strategy];
    const tr = document.createElement("tr");
    const statuses = Object.entries(row.statuses)
      .map(([k, v]) => `${k} ${v}`)
      .join(", ");
    tr.innerHTML = `
      <td>${strategy}</td>
      <td class="num">${row.layouts}</td>
      <td class="num">${formatRate(row.success_rate)}</td>
      <td class="num">${formatRate(row.collision_free_rate)}</td>
      <td class="num">${row.mean_elapsed_s === null ? "—" : `${row.mean_elapsed_s.toFixed(1)} s`}</td>
      <td>${statuses}</td>`;
    body.appendChild(tr);
  }
  table.appendChild(body);
  ui.sweepOutput.replaceChildren(table);

  const failures = trials.filter((trial) => trial.status !== "success");
  const note = document.createElement("p");
  note.className = "failures";
  const timing = `${trials.length} proxy episodes across ${seeds.length} courses in ${seconds.toFixed(1)} s in-browser. `;
  if (failures.length === 0) {
    note.textContent = `${timing}All reached the finish without contact.`;
  } else {
    note.append(`${timing}${failures.length} did not succeed — open one: `);
    for (const failure of failures) {
      const button = document.createElement("button");
      button.type = "button";
      const label = failure.seed === null ? "fixed" : `seed ${failure.seed}`;
      button.textContent = `${label} · ${failure.strategy} · ${failure.status}`;
      button.addEventListener("click", () => {
        runEpisode(failure.seed, failure.strategy);
        ui.canvas.scrollIntoView({ behavior: "smooth", block: "start" });
      });
      note.appendChild(button);
    }
  }
  ui.sweepOutput.appendChild(note);
}

/** Yield to the event loop without `setTimeout`, which background tabs throttle to ≥1 s. */
function yieldToBrowser(): Promise<void> {
  return new Promise((resolve) => {
    const channel = new MessageChannel();
    channel.port1.onmessage = () => resolve();
    channel.port2.postMessage(null);
  });
}

async function runSweep(): Promise<void> {
  if (!state.engine) {
    return;
  }
  const max = Math.max(4, Math.min(199, Number(ui.sweepMax.value) || 0));
  ui.sweepMax.value = String(max);
  const seeds: (number | null)[] = ui.sweepFixed.checked ? [null] : [];
  for (let seed = 0; seed <= max; seed += 1) {
    seeds.push(seed);
  }
  ui.sweepRun.disabled = true;
  ui.sweepProgress.hidden = false;
  ui.sweepProgress.value = 0;
  ui.sweepOutput.replaceChildren();
  const trials: TrialResult[] = [];
  const started = performance.now();
  try {
    for (const [index, seed] of seeds.entries()) {
      trials.push(...state.engine.sweepSeed(seed));
      ui.sweepProgress.value = (index + 1) / seeds.length;
      await yieldToBrowser();
    }
    renderSweep(trials, seeds, (performance.now() - started) / 1000);
  } finally {
    ui.sweepRun.disabled = false;
    ui.sweepProgress.hidden = true;
  }
}

function wireEvents(): void {
  ui.form.addEventListener("submit", (event) => {
    event.preventDefault();
    runEpisode(seedFromSelect(), strategyFromSelect());
  });
  ui.play.addEventListener("click", () => setPlaying(!state.playing));
  ui.stepBack.addEventListener("click", () => {
    setPlaying(false);
    showFrame(state.frame - 1);
  });
  ui.stepForward.addEventListener("click", () => {
    setPlaying(false);
    showFrame(state.frame + 1);
  });
  ui.scrub.addEventListener("input", () => {
    setPlaying(false);
    showFrame(Number(ui.scrub.value));
  });
  ui.sweepForm.addEventListener("submit", (event) => {
    event.preventDefault();
    void runSweep();
  });
  window.addEventListener("resize", () => {
    renderer.resize();
    renderer.draw(state.trial, state.frame);
  });
  window.addEventListener("keydown", (event) => {
    if (event.target instanceof HTMLInputElement || event.target instanceof HTMLSelectElement) {
      return;
    }
    if (event.key === " " && state.trial) {
      event.preventDefault();
      setPlaying(!state.playing);
    } else if (event.key === "ArrowRight" && state.trial) {
      setPlaying(false);
      showFrame(state.frame + 1);
    } else if (event.key === "ArrowLeft" && state.trial) {
      setPlaying(false);
      showFrame(state.frame - 1);
    }
  });
}

const STAGE_TEXT: Record<LoadStage, string> = {
  script: "Fetching the Pyodide loader…",
  runtime: "Starting CPython (WebAssembly, about 10 MB, cached after the first visit)…",
  package: "Installing the duck_course package into the in-browser filesystem…",
  ready: "Ready.",
};

async function boot(): Promise<void> {
  populateSeeds();
  buildRulesTable();
  wireEvents();
  renderer.resize();
  renderer.draw(null, 0);
  requestAnimationFrame(tick);
  try {
    const engine = await Engine.load({
      onStage: (stage) => {
        ui.loadingStage.textContent = STAGE_TEXT[stage];
      },
    });
    state.engine = engine;
    const commit = document.createElement("a");
    commit.href = `https://github.com/natnew/Duck-Obstacle-Course/commit/${__COMMIT__}`;
    commit.rel = "noopener";
    commit.textContent = `build ${__COMMIT__.slice(0, 7)}`;
    ui.buildInfo.replaceChildren(
      commit,
      ` · Pyodide ${engine.pyodideVersion} (pinned ${PYODIDE_VERSION}) · ` +
        `CPython ${engine.pythonVersion} · ${engine.moduleCount} package modules loaded`,
    );
    ui.run.disabled = false;
    ui.sweepRun.disabled = false;
    setText(ui.status, "Ready — choose a course and run an episode.");
    ui.body.dataset.state = "ready";
    const fromUrl = readUrl();
    if (fromUrl) {
      runEpisode(fromUrl.seed === "fixed" ? null : Number(fromUrl.seed), fromUrl.strategy);
    }
  } catch (error) {
    ui.body.dataset.state = "error";
    const message = error instanceof Error ? error.message : String(error);
    ui.loadingStage.textContent = `Could not start the Python runtime: ${message}. Check your connection and reload.`;
    setText(ui.status, "Runtime failed to load.", "blocked");
  }
}

void boot();
