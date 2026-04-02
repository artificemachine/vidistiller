import { test, expect } from "@playwright/test";

/**
 * Theme toggle tests — verifies dark/light mode toggle button behavior.
 */

test.describe("Theme toggle", () => {
  test("toggle button is visible in navbar", async ({ page }) => {
    await page.goto("/");
    // ThemeToggle renders a button with title containing "switch to"
    const toggle = page.locator("button[title*='switch to']");
    await expect(toggle).toBeVisible({ timeout: 5_000 });
  });

  test("clicking toggle switches theme class on <html>", async ({ page }) => {
    await page.goto("/");
    const toggle = page.locator("button[title*='switch to']");
    await expect(toggle).toBeVisible({ timeout: 5_000 });

    // Get initial theme
    const initialTheme = await page.locator("html").getAttribute("class");
    const wasDark = initialTheme?.includes("dark");

    // Click toggle
    await toggle.click();

    // Theme should have changed
    if (wasDark) {
      await expect(page.locator("html")).not.toHaveClass(/dark/);
    } else {
      await expect(page.locator("html")).toHaveClass(/dark/);
    }
  });

  test("theme persists after page reload", async ({ page }) => {
    await page.goto("/");
    const toggle = page.locator("button[title*='switch to']");
    await expect(toggle).toBeVisible({ timeout: 5_000 });

    // Get initial theme and toggle it
    const initialTheme = await page.locator("html").getAttribute("class");
    const wasDark = initialTheme?.includes("dark");
    await toggle.click();

    // Verify toggle happened
    if (wasDark) {
      await expect(page.locator("html")).not.toHaveClass(/dark/);
    } else {
      await expect(page.locator("html")).toHaveClass(/dark/);
    }

    // Reload and check theme persisted
    await page.reload();
    if (wasDark) {
      // Was dark, toggled to light — should still be light after reload
      await expect(page.locator("html")).not.toHaveClass(/dark/);
    } else {
      // Was light, toggled to dark — should still be dark after reload
      await expect(page.locator("html")).toHaveClass(/dark/);
    }
  });

  test("theme persists across navigation", async ({ page }) => {
    await page.goto("/");
    const toggle = page.locator("button[title*='switch to']");
    await expect(toggle).toBeVisible({ timeout: 5_000 });

    // Get initial theme and toggle it
    const initialTheme = await page.locator("html").getAttribute("class");
    const wasDark = initialTheme?.includes("dark");
    await toggle.click();

    // Navigate to another page
    await page.goto("/login");

    // Theme should persist
    if (wasDark) {
      await expect(page.locator("html")).not.toHaveClass(/dark/);
    } else {
      await expect(page.locator("html")).toHaveClass(/dark/);
    }
  });
});
