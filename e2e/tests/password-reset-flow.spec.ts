import { test, expect } from "@playwright/test";

test.use({ storageState: { cookies: [], origins: [] } }); // unauthenticated

test.describe("Forgot password form", () => {
  test("forgot password page renders and accepts email", async ({ page }) => {
    await page.goto("/forgot-password");

    await expect(page.locator("#email")).toBeVisible();
    await expect(page.locator("button[type='submit']")).toContainText("send reset link");

    await page.fill("#email", "e2e@test.local");
    await page.click("button[type='submit']");

    // Should show success (green) or error (red) feedback div — not the button or Next.js announcer
    await expect(
      page.locator(".bg-green-50, .bg-red-50")
    ).toBeVisible({ timeout: 5_000 });
  });
});

test.describe("Reset password form", () => {
  test("renders with a token in the URL", async ({ page }) => {
    await page.goto("/reset-password?token=test-token-123");

    await expect(page.locator("#new-password")).toBeVisible();
    await expect(page.locator("#confirm-password")).toBeVisible();
    await expect(page.locator("button[type='submit']")).toContainText("update password");
  });

  test("shows invalid link message without a token", async ({ page }) => {
    await page.goto("/reset-password");

    await expect(page.getByRole("heading", { name: "Invalid Reset Link" })).toBeVisible({ timeout: 5_000 });
  });
});
