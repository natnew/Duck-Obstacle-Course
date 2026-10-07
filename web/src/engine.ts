/**
 * Pyodide bridge. Loads CPython (WebAssembly) from the jsDelivr CDN, writes the
 * repository's `duck_course` package into the in-browser filesystem, and exposes
 * the proxy entry points. The navigation, sensing and scoring code that runs here
 * is byte-for-byte the package under `src/`, bundled at build time.
 */

import baseline from "../../configs/baseline.json";
import type { Strategy, Summary, Trial, TrialResult } from "./types";

export const PYODIDE_VERSION = "314.0.7";
const PYODIDE_INDEX = `https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`;
const PACKAGE_ROOT = "/duck";

// Vite inlines every module of the Python package as a string.
const PYTHON_SOURCES = import.meta.glob("../../src/duck_course/**/*.py", {
  query: "?raw",
  import: "default",
  eager: true,
}) as Record<string, string>;

const GLUE = `
import json, sys
sys.path.insert(0, ${JSON.stringify(PACKAGE_ROOT)})
from duck_course.proxy import run_trial, sweep
from duck_course.evaluation import summarize
CONFIG = json.loads(CONFIG_JSON)

def trial_json(args_json):
    args = json.loads(args_json)
    return json.dumps(run_trial(args["seed"], args["strategy"], CONFIG))

def sweep_seed_json(seed_json):
    return json.dumps(sweep([json.loads(seed_json)], CONFIG)["trials"])

def summarize_json(trials_json):
    return json.dumps(summarize(json.loads(trials_json)))
`;

interface PyodideFS {
  mkdirTree(path: string): void;
  writeFile(path: string, data: string): void;
}

interface PyCallable {
  (...args: unknown[]): unknown;
}

interface Pyodide {
  version: string;
  FS: PyodideFS;
  globals: { get(name: string): PyCallable; set(name: string, value: unknown): void };
  runPython(code: string): unknown;
}

declare global {
  interface Window {
    loadPyodide?: (options: { indexURL: string }) => Promise<Pyodide>;
  }
}

export type LoadStage = "script" | "runtime" | "package" | "ready";

export interface EngineOptions {
  onStage?: (stage: LoadStage) => void;
}

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    if (window.loadPyodide) {
      resolve();
      return;
    }
    const script = document.createElement("script");
    script.src = src;
    script.async = true;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`failed to load ${src}`));
    document.head.appendChild(script);
  });
}

export class Engine {
  private constructor(
    private readonly py: Pyodide,
    readonly pythonVersion: string,
    readonly moduleCount: number,
  ) {}

  static async load(options: EngineOptions = {}): Promise<Engine> {
    const stage = options.onStage ?? (() => undefined);
    stage("script");
    await loadScript(`${PYODIDE_INDEX}pyodide.js`);
    if (!window.loadPyodide) {
      throw new Error("Pyodide loader did not register on window");
    }
    stage("runtime");
    const py = await window.loadPyodide({ indexURL: PYODIDE_INDEX });
    stage("package");
    let count = 0;
    for (const [path, source] of Object.entries(PYTHON_SOURCES)) {
      const relative = path.slice(path.indexOf("duck_course/"));
      const target = `${PACKAGE_ROOT}/${relative}`;
      py.FS.mkdirTree(target.slice(0, target.lastIndexOf("/")));
      py.FS.writeFile(target, source);
      count += 1;
    }
    py.globals.set("CONFIG_JSON", JSON.stringify(baseline));
    py.runPython(GLUE);
    const version = String(py.runPython("import sys; sys.version.split()[0]"));
    stage("ready");
    return new Engine(py, version, count);
  }

  get pyodideVersion(): string {
    return this.py.version;
  }

  get config(): typeof baseline {
    return baseline;
  }

  /** One fully recorded proxy episode for rendering. */
  trial(seed: number | null, strategy: Strategy): Trial {
    // Arguments cross the JS→Python boundary as JSON so `null` reliably becomes `None`.
    const json = this.py.globals.get("trial_json")(JSON.stringify({ seed, strategy })) as string;
    return JSON.parse(json) as Trial;
  }

  /** Unrecorded trials for both strategies on one seed. */
  sweepSeed(seed: number | null): TrialResult[] {
    const json = this.py.globals.get("sweep_seed_json")(JSON.stringify(seed)) as string;
    return JSON.parse(json) as TrialResult[];
  }

  /** Aggregate with the package's own `summarize`, not a JavaScript re-implementation. */
  summarize(trials: TrialResult[]): Summary {
    const json = this.py.globals.get("summarize_json")(JSON.stringify(trials)) as string;
    return JSON.parse(json) as Summary;
  }
}
