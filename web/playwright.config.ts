import { defineConfig } from "@playwright/test";

// `vite preview` serves the production build at the configured base path, so the
// same test run works locally ("/") and in CI ("/Duck-Obstacle-Course/").
const base = process.env.DEMO_BASE ?? "/";
const baseURL = `http://localhost:4173${base}`;

export default defineConfig({
  testDir: "./e2e",
  timeout: 120_000,
  expect: { timeout: 30_000 },
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["list"]] : "list",
  use: {
    baseURL,
    trace: "retain-on-failure",
  },
  webServer: {
    command: "npm run preview",
    url: baseURL,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
  },
  projects: [{ name: "chromium", use: { browserName: "chromium" } }],
});
