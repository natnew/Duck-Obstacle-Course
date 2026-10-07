// Capture a README screenshot of the demo at a chosen seed, strategy and frame.
//
//   npm run dev            (in another terminal)
//   node scripts/capture.mjs [url] [frame] [output]
//
// Defaults reproduce docs/demo.png: seed 4, clearance, frame 186 (a latched left
// turn beside the second obstacle).

import { chromium } from "@playwright/test";

const url = process.argv[2] ?? "http://localhost:5173/?seed=4&strategy=clearance";
const frame = Number(process.argv[3] ?? "186");
const output = process.argv[4] ?? "../docs/demo.png";

const browser = await chromium.launch();
try {
  const page = await browser.newPage({ viewport: { width: 1240, height: 900 }, deviceScaleFactor: 2 });
  await page.goto(url);
  await page.waitForSelector('body[data-state="ready"]', { timeout: 90_000 });
  await page.waitForFunction(() => !document.querySelector("#scrub").disabled);
  await page.evaluate((target) => {
    const scrub = document.querySelector("#scrub");
    scrub.value = String(target);
    scrub.dispatchEvent(new Event("input", { bubbles: true }));
  }, frame);
  await page.addStyleTag({ content: ".sweep { display: none; }" });
  await page.locator("main.layout").screenshot({ path: output });
  console.log(`wrote ${output}`);
} finally {
  await browser.close();
}
