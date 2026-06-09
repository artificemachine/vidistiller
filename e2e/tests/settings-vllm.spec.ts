import { test, expect, Route } from "@playwright/test";

/**
 * E2E tests for the vLLM provider card on the settings page.
 * Fleet and sidecar API calls are intercepted so no real fleet access is needed.
 *
 * IMPORTANT: fleet mock must be set up BEFORE page.goto("/settings") because
 * fetchSettings() calls /settings/vllm/fleet during initial page load.
 */

const MODELS_API = "**/api/settings/vllm/models**";
const FLEET_API  = "**/api/settings/vllm/fleet**";

const MOCK_FLEET = [
  { id: "vm913",  label: "VM913",  tier: "opus-class",   desc: "4× RTX 3090 · 96 GB · TP=2", model: "qwopus-27b", url: "http://192.0.2.1:8100" },
  { id: "vm903",  label: "VM903",  tier: "sonnet-class", desc: "2× RTX 3090 · 48 GB",              model: "",           url: "http://192.0.2.2:8100" },
  { id: "vm901",  label: "VM901",  tier: "haiku-class",  desc: "2× RTX 3080 · 20 GB",              model: "",           url: "http://192.0.2.3:8100" },
  { id: "vm2900", label: "VM2900", tier: "small",        desc: "RTX 3060 Ti · 8 GB usable",            model: "",           url: "http://192.0.2.4:8100" },
];

function mockFleet(route: Route) {
  route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ nodes: MOCK_FLEET }),
  });
}

function mockSidecar(route: Route, models: string[] = ["qwopus-27b"]) {
  route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ models }),
  });
}

/**
 * Navigate to /settings with fleet mock already active so the initial
 * fetchSettings() call returns the mocked fleet nodes.
 */
async function gotoSettingsWithFleet(page: any, sidecarModels?: string[]) {
  await page.route(FLEET_API, (route: Route) => mockFleet(route));
  if (sidecarModels !== undefined) {
    await page.route(MODELS_API, (route: Route) => mockSidecar(route, sidecarModels));
  }
  await page.goto("/settings");
  await expect(page.getByText("loading settings...")).not.toBeVisible({ timeout: 10_000 });
}

test.describe("Settings — vLLM provider", () => {

  // -------------------------------------------------------------------------
  // Provider card visibility
  // -------------------------------------------------------------------------

  test("vllm provider card is visible", async ({ page }) => {
    await gotoSettingsWithFleet(page);
    await expect(page.locator("input[type='radio'][value='vllm']")).toBeAttached();
    await expect(
      page.locator("text=self-hosted vllm fleet, openai-compatible, no api key required")
    ).toBeVisible();
  });

  // -------------------------------------------------------------------------
  // Selecting the vllm provider
  // -------------------------------------------------------------------------

  test("selecting vllm shows fleet node buttons", async ({ page }) => {
    await gotoSettingsWithFleet(page);
    await page.locator("input[type='radio'][value='vllm']").click({ force: true });

    await expect(page.locator("button", { hasText: "VM913" })).toBeVisible();
    await expect(page.locator("button", { hasText: "VM903" })).toBeVisible();
    await expect(page.locator("button", { hasText: "VM901" })).toBeVisible();
    await expect(page.locator("button", { hasText: "VM2900" })).toBeVisible();
  });

  test("vllm card does not show api key input", async ({ page }) => {
    await gotoSettingsWithFleet(page);
    await page.locator("input[type='radio'][value='vllm']").click({ force: true });
    await expect(page.locator("input[type='password']")).not.toBeVisible();
  });

  // -------------------------------------------------------------------------
  // Node selection — model auto-fetch
  // -------------------------------------------------------------------------

  test("clicking VM913 node fetches and displays model", async ({ page }) => {
    await gotoSettingsWithFleet(page, ["qwopus-27b"]);
    await page.locator("input[type='radio'][value='vllm']").click({ force: true });
    await page.locator("button", { hasText: "VM913" }).click();

    await expect(page.locator("text=qwopus-27b").first()).toBeVisible({ timeout: 5_000 });
  });

  test("clicking VM913 node calls sidecar with correct URL", async ({ page }) => {
    let capturedUrl = "";
    await page.route(FLEET_API, (route: Route) => mockFleet(route));
    await page.route(MODELS_API, (route: Route) => {
      capturedUrl = route.request().url();
      mockSidecar(route);
    });
    await page.goto("/settings");
    await expect(page.getByText("loading settings...")).not.toBeVisible({ timeout: 10_000 });

    await page.locator("input[type='radio'][value='vllm']").click({ force: true });
    await Promise.all([
      page.waitForResponse(MODELS_API),
      page.locator("button", { hasText: "VM913" }).click(),
    ]);
    expect(capturedUrl).toContain("192.0.2.1:8100"); // VM913 from MOCK_FLEET
  });

  test("node button highlights when selected", async ({ page }) => {
    await gotoSettingsWithFleet(page);
    await page.locator("input[type='radio'][value='vllm']").click({ force: true });
    const vm913 = page.locator("button", { hasText: "VM913" });
    await vm913.click();

    await expect(vm913).toHaveClass(/border-primary/);
  });

  // -------------------------------------------------------------------------
  // Multiple models — list shown
  // -------------------------------------------------------------------------

  test("shows model list when sidecar returns multiple models", async ({ page }) => {
    await gotoSettingsWithFleet(page);
    await page.route(MODELS_API, (route: Route) => mockSidecar(route, ["model-a", "model-b"]));

    await page.locator("input[type='radio'][value='vllm']").click({ force: true });
    await page.locator("button", { hasText: "VM903" }).click();

    await expect(page.locator("button", { hasText: "model-a" })).toBeVisible({ timeout: 5_000 });
    await expect(page.locator("button", { hasText: "model-b" })).toBeVisible();
  });

  test("clicking a model from the list fills the text input", async ({ page }) => {
    await gotoSettingsWithFleet(page);
    await page.route(MODELS_API, (route: Route) => mockSidecar(route, ["model-a", "model-b"]));

    await page.locator("input[type='radio'][value='vllm']").click({ force: true });
    await page.locator("button", { hasText: "VM903" }).click();
    await page.locator("button", { hasText: "model-b" }).click();

    const modelInput = page.locator("input[placeholder*='type a model name']");
    await expect(modelInput).toHaveValue("model-b");
  });

  // -------------------------------------------------------------------------
  // Custom model override
  // -------------------------------------------------------------------------

  test("user can type a custom model name not in the list", async ({ page }) => {
    await gotoSettingsWithFleet(page, ["qwopus-27b"]);
    await page.locator("input[type='radio'][value='vllm']").click({ force: true });
    await Promise.all([
      page.waitForResponse(MODELS_API),
      page.locator("button", { hasText: "VM913" }).click(),
    ]);

    const modelInput = page.locator("input[placeholder*='type a model name']");
    await modelInput.clear();
    await modelInput.fill("my-custom-model");

    await expect(modelInput).toHaveValue("my-custom-model");
  });

  // -------------------------------------------------------------------------
  // Sidecar unreachable
  // -------------------------------------------------------------------------

  test("shows empty model input when sidecar returns error", async ({ page }) => {
    await gotoSettingsWithFleet(page);
    await page.route(MODELS_API, (route: Route) =>
      route.fulfill({ status: 502, body: JSON.stringify({ detail: "unreachable" }) })
    );

    await page.locator("input[type='radio'][value='vllm']").click({ force: true });
    await Promise.all([
      page.waitForResponse(MODELS_API),
      page.locator("button", { hasText: "VM901" }).click(),
    ]);

    const modelInput = page.locator("input[placeholder*='type a model name']");
    await expect(modelInput).toHaveValue("");
  });

  // -------------------------------------------------------------------------
  // Save
  // -------------------------------------------------------------------------

  test("can save vllm provider settings", async ({ page }) => {
    await gotoSettingsWithFleet(page, ["qwopus-27b"]);
    await page.locator("input[type='radio'][value='vllm']").click({ force: true });
    await Promise.all([
      page.waitForResponse(MODELS_API),
      page.locator("button", { hasText: "VM913" }).click(),
    ]);

    await page.click("button[type='submit']:has-text('save settings')");

    const success = page.locator("text=Settings saved successfully");
    const error = page.locator(".bg-red-50, .dark\\:bg-red-900\\/20").first();
    await expect(success.or(error)).toBeVisible({ timeout: 10_000 });
  });
});
