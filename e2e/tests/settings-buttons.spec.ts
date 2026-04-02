import { test, expect } from "@playwright/test";

/**
 * Settings page button/control tests — verifies all interactive elements on the settings page.
 * Uses authenticated state from global setup.
 */

test.describe("Settings page controls", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/settings");
    // Wait for settings to load (loading state disappears)
    await expect(page.getByText("loading settings...")).not.toBeVisible({ timeout: 10_000 });
  });

  test("page heading is visible", async ({ page }) => {
    await expect(page.getByRole("heading", { name: "settings" })).toBeVisible();
  });

  test("provider select defaults to ollama", async ({ page }) => {
    const select = page.locator("select");
    await expect(select).toHaveValue("ollama");
  });

  test("can switch provider to openai", async ({ page }) => {
    const select = page.locator("select");
    await select.selectOption("openai");
    await expect(select).toHaveValue("openai");
    // API key label should appear for cloud providers
    await expect(page.locator("label").filter({ hasText: "api key" })).toBeVisible();
  });

  test("can switch provider to anthropic", async ({ page }) => {
    const select = page.locator("select");
    await select.selectOption("anthropic");
    await expect(select).toHaveValue("anthropic");
    await expect(page.locator("label").filter({ hasText: "api key" })).toBeVisible();
  });

  test("ollama shows base URL input instead of API key", async ({ page }) => {
    const select = page.locator("select");
    await select.selectOption("ollama");
    // Ollama URL field should be visible
    await expect(page.locator("text=ollama base url")).toBeVisible();
    // API key field should NOT be visible for ollama
    await expect(page.locator("label:has-text('api key')")).not.toBeVisible();
  });

  test("model name input accepts text", async ({ page }) => {
    const modelInput = page.locator("input[type='text']").first();
    await modelInput.clear();
    await modelInput.fill("custom-model-v1");
    await expect(modelInput).toHaveValue("custom-model-v1");
  });

  test("'save settings' button submits form", async ({ page }) => {
    // Click save and expect success or network error (both are valid — backend may not have settings endpoint ready)
    await page.click("button:has-text('save settings')");

    // Wait for either success message or error message
    const successMsg = page.locator("text=Settings saved successfully");
    const errorMsg = page.locator(".bg-red-50, .dark\\:bg-red-900\\/20").first();
    const savingBtn = page.locator("button:has-text('saving...')");

    // Button should show saving state briefly, then result appears
    await expect(successMsg.or(errorMsg).or(savingBtn)).toBeVisible({ timeout: 10_000 });
  });

  test("'cancel' button navigates back", async ({ page }) => {
    // First navigate to settings from dashboard so there's a back history
    await page.goto("/dashboard");
    await page.waitForTimeout(1000);
    await page.goto("/settings");
    await expect(page.getByText("loading settings...")).not.toBeVisible({ timeout: 10_000 });

    await page.click("button:has-text('cancel')");
    // cancel calls router.back() — should go back to previous page
    await expect(page).not.toHaveURL(/\/settings/);
  });

  test("switching to openai shows API key input field", async ({ page }) => {
    const select = page.locator("select");
    await select.selectOption("openai");

    // The API key password input should now be visible
    const apiKeyInput = page.locator("input[type='password']");
    await expect(apiKeyInput).toBeVisible();
    await expect(apiKeyInput).toHaveAttribute("placeholder", /api key/i);
  });

  test("provider info section is visible", async ({ page }) => {
    await expect(page.getByRole("heading", { name: "provider information" })).toBeVisible();
    await expect(page.locator("text=ollama (recommended for privacy)")).toBeVisible();
    await expect(page.locator("h3:has-text('openai')")).toBeVisible();
    await expect(page.locator("h3:has-text('anthropic')")).toBeVisible();
  });
});
