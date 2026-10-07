import { expect, test, type Page } from "@playwright/test";

// Pyodide downloads ~10 MB on a cold cache, so readiness gets a generous budget.
async function waitForRuntime(page: Page): Promise<void> {
  await expect(page.locator("body")).toHaveAttribute("data-state", "ready", { timeout: 90_000 });
  await expect(page.locator("#build-info")).toContainText("package modules loaded");
}

async function jumpToEnd(page: Page): Promise<void> {
  await expect(page.locator("#scrub")).toBeEnabled();
  await page.locator("#scrub").focus();
  await page.keyboard.press("End");
  await expect(page.locator("#result")).toBeVisible();
}

test.describe("Duck Obstacle Course browser demo", () => {
  test("runs the fixed course to success with the real package", async ({ page }) => {
    await page.goto("./");
    await waitForRuntime(page);
    await expect(page.locator("#status")).toContainText("Ready");
    await page.getByRole("button", { name: "Run episode" }).click();
    await jumpToEnd(page);
    await expect(page.locator("#result-status")).toContainText("Success");
    await expect(page.locator("#result-collisions")).toHaveText("0");
    await expect(page.locator("#result-trace")).toHaveText(/^[0-9a-f]{12}$/);
    await expect(page).toHaveURL(/seed=fixed&strategy=clearance/);
  });

  test("deep link reproduces the seed-48 corner-clip stall byte-for-byte", async ({ page }) => {
    await page.goto("./?seed=48&strategy=clearance");
    await waitForRuntime(page);
    await jumpToEnd(page);
    await expect(page.locator("#result-status")).toContainText("Stalled");
    await expect(page.locator("#result-collisions")).toHaveText("1");
    // Same prefix as the native run recorded in tests/test_proxy.py's regression case.
    await expect(page.locator("#result-trace")).toHaveText("ab48a2d2fc2e");
    await expect(page.locator("#rules tr.active")).toHaveAttribute("data-rule", "episode");
  });

  test("sweep over the fixed course and seeds 0–9 succeeds everywhere", async ({ page }) => {
    await page.goto("./");
    await waitForRuntime(page);
    await page.locator("#sweep-max").fill("9");
    await page.getByRole("button", { name: "Run sweep" }).click();
    const output = page.locator("#sweep-output");
    await expect(output.locator("table")).toBeVisible({ timeout: 60_000 });
    await expect(output).toContainText("22 proxy episodes across 11 courses");
    await expect(output).toContainText("All reached the finish without contact.");
    await expect(output.locator("tbody tr")).toHaveCount(2);
    await expect(output.locator("tbody tr").first()).toContainText("100.0 %");
  });

  test("has no accessibility-breaking structure", async ({ page }) => {
    await page.goto("./");
    await expect(page.getByRole("heading", { level: 1 })).toHaveText("Duck Obstacle Course");
    await expect(page.getByRole("img", { name: /Top-down view of the course/ })).toBeVisible();
    await expect(page.getByRole("note")).toContainText("not evidence of MicroDuck locomotion");
    await expect(page.locator("html")).toHaveAttribute("lang", "en-GB");
  });
});
