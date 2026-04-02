import { test, expect } from "@playwright/test";

test.use({ storageState: { cookies: [], origins: [] } }); // unauthenticated

test.describe("Route protection", () => {
  test("redirects /dashboard to /login when unauthenticated", async ({ page }) => {
    await page.goto("/dashboard");
    await expect(page).toHaveURL(/\/login/);
  });

  test("redirects /jobs/123 to /login when unauthenticated", async ({ page }) => {
    await page.goto("/jobs/123");
    await expect(page).toHaveURL(/\/login/);
  });

  test("login page is accessible without auth", async ({ page }) => {
    await page.goto("/login");
    await expect(page.locator("button[type='submit']")).toContainText("sign in");
  });

  test("register page is accessible without auth", async ({ page }) => {
    await page.goto("/register");
    await expect(page.locator("button[type='submit']")).toContainText("create account");
  });
});
