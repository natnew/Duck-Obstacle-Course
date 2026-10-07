import { execSync } from "node:child_process";
import { defineConfig } from "vite";

function gitCommit(): string {
  try {
    return execSync("git rev-parse --short HEAD", { stdio: ["ignore", "pipe", "ignore"] })
      .toString()
      .trim();
  } catch {
    return "unknown";
  }
}

// CI sets DEMO_BASE to "/Duck-Obstacle-Course/" for GitHub Pages; local dev serves at "/".
export default defineConfig({
  base: process.env.DEMO_BASE ?? "/",
  define: {
    __COMMIT__: JSON.stringify(process.env.DEMO_COMMIT ?? gitCommit()),
  },
  server: {
    // The Python package and baseline config are read from the repository root.
    fs: { allow: [".."] },
  },
  build: {
    target: "es2022",
    sourcemap: true,
  },
});
