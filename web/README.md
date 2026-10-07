# Browser demo

A static page that runs the repository's `duck_course` Python package in the
browser via [Pyodide](https://pyodide.org/) and animates the 2-D kinematic proxy
([`src/duck_course/proxy.py`](../src/duck_course/proxy.py)). It is deployed to
GitHub Pages by [`.github/workflows/ci.yml`](../.github/workflows/ci.yml) on every
push to `main`, after the Python tests, the proxy harness and the browser tests
pass.

The proxy shows navigation logic only. It is not MicroDuck locomotion; the page
says so in a persistent notice, and the README's limitations section applies.

## How it works

| Piece | Role |
|---|---|
| `index.html`, `src/style.css` | Semantic layout, restrained styling, loading overlay |
| `src/engine.ts` | Loads Pyodide from the jsDelivr CDN (pinned version), writes every `src/duck_course/**/*.py` file into the in-browser filesystem, and exposes `run_trial`, per-seed `sweep` and `summarize` |
| `src/renderer.ts` | Canvas renderer: course, rays by sector, hysteresis bands, latched-turn ring, trail |
| `src/rules.ts` | Explains which `ReactivePolicy.decide` / `Episode.update` rule produced each action |
| `src/main.ts` | Controls, playback, URL state (`?seed=&strategy=`), sweep panel |
| `e2e/demo.spec.ts` | Playwright tests against the production build |
| `scripts/capture.mjs` | Regenerates `docs/demo.png` |

The Python sources are inlined at build time with Vite's `import.meta.glob`, so
the demo always ships the package as it exists in the same commit. Arguments
cross the JS→Python boundary as JSON strings so that `null` reliably becomes
`None`. The sweep yields to the browser between seeds via `MessageChannel`,
which, unlike `setTimeout`, background tabs do not throttle.

## Commands

```sh
npm ci
npm run dev          # Vite dev server at http://localhost:5173/
npm run typecheck    # tsc --noEmit
npm run build        # type-check + production bundle in dist/
npm run preview      # serve dist/ at http://localhost:4173/
npm run test:e2e     # Playwright (starts the preview server itself)
npx playwright install chromium   # once, before test:e2e
```

`DEMO_BASE` sets the Vite `base` (CI uses `/Duck-Obstacle-Course/`), and
`DEMO_COMMIT` overrides the commit shown in the footer.

Screenshot for the README, with the dev server running:

```sh
node scripts/capture.mjs                     # seed 4, clearance, frame 186
node scripts/capture.mjs "http://localhost:5173/?seed=48&strategy=clearance" 308 ../docs/seed48.png
```

## Dependencies

Development only: `vite`, `typescript`, `@playwright/test`, `@types/node`. The
page itself has no runtime dependency other than the Pyodide CDN. No framework
is used; a canvas and a dozen controls do not justify one.

## Limitations

- First load fetches roughly 10 MB of WebAssembly and standard library from the
  CDN. Later visits use the browser cache.
- Everything runs on the main thread. Episodes compute in a few milliseconds; a
  51-course sweep takes a few seconds and yields between seeds.
- The synthetic ToF frame is identical across rows, has a 45° horizontal field of
  view and no noise. The real simulator's ray caster differs.
