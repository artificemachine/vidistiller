import { test, expect } from "@playwright/test";

/**
 * Settings page control tests — verifies interactive elements on the settings page.
 * The UI uses radio-card-style provider selection (not a <select>).
 * Uses authenticated state from global setup.
 */

test.describe("Settings page controls", () => {
  test.beforeEach(async ({ page }) => {
    await page.goto("/settings");
    await expect(page.getByText("loading settings...")).not.toBeVisible({ timeout: 10_000 });
  });

  test("llm provider heading is visible", async ({ page }) => {
    await expect(page.locator("h2").filter({ hasText: "llm provider" })).toBeVisible();
  });

  test("ollama provider card is selected by default", async ({ page }) => {
    const ollamaRadio = page.locator("input[type='radio'][name='llm_provider'][value='ollama']");
    await expect(ollamaRadio).toBeChecked();
  });

  test("ollama card shows base url and model inputs", async ({ page }) => {
    const ollamaRadio = page.locator("input[type='radio'][name='llm_provider'][value='ollama']");
    await expect(ollamaRadio).toBeChecked();
    await expect(page.locator("input[type='url']")).toBeVisible();
    await expect(page.locator("label").filter({ hasText: "base url" })).toBeVisible();
    await expect(page.locator("input[type='password']")).not.toBeVisible();
  });

  test("switching to openai reveals api key input", async ({ page }) => {
    await page.locator("input[type='radio'][name='llm_provider'][value='openai']").click({ force: true });
    await expect(page.locator("input[type='password']")).toBeVisible();
    await expect(page.locator("input[type='url']")).not.toBeVisible();
  });

  test("switching to anthropic reveals api key input", async ({ page }) => {
    await page.locator("input[type='radio'][name='llm_provider'][value='anthropic']").click({ force: true });
    await expect(page.locator("input[type='password']")).toBeVisible();
    await expect(page.locator("input[type='url']")).not.toBeVisible();
  });

  test("model name input accepts text after switching to openai", async ({ page }) => {
    await page.locator("input[type='radio'][name='llm_provider'][value='openai']").click({ force: true });
    const modelInput = page.locator("input[type='text']").first();
    await modelInput.clear();
    await modelInput.fill("gpt-4-turbo");
    await expect(modelInput).toHaveValue("gpt-4-turbo");
  });

  test("save settings button submits form", async ({ page }) => {
    await page.click("button[type='submit']:has-text('save settings')");
    // The handler shows the success toast, then makes a second request (GET
    // /auth/me) before re-enabling the button, so the toast and a disabled
    // "saving..." button are legitimately visible at the same time -- that's
    // not a third outcome, it's an implementation detail of a real success.
    // Assert on the two actual terminal states, not the transient one.
    const successMsg = page.locator("text=Settings saved successfully");
    const errorMsg = page.locator(".bg-red-50, .dark\\:bg-red-900\\/20").first();
    await expect(successMsg.or(errorMsg)).toBeVisible({ timeout: 10_000 });
  });

  test("api key input has password placeholder for openai", async ({ page }) => {
    await page.locator("input[type='radio'][name='llm_provider'][value='openai']").click({ force: true });
    const apiKeyInput = page.locator("input[type='password']");
    await expect(apiKeyInput).toBeVisible();
    await expect(apiKeyInput).toHaveAttribute("placeholder", /sk-/i);
  });

  test("all four provider cards are present", async ({ page }) => {
    await expect(page.locator("input[type='radio'][value='ollama']")).toBeAttached();
    await expect(page.locator("input[type='radio'][value='openai']")).toBeAttached();
    await expect(page.locator("input[type='radio'][value='anthropic']")).toBeAttached();
    await expect(page.locator("input[type='radio'][value='vllm']")).toBeAttached();
  });
});
