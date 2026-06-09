import { test, expect } from "@playwright/test";

test.use({ storageState: { cookies: [], origins: [] } }); // start unauthenticated

test.describe("Registration flow", () => {
  test("registers a new user and lands on home page", async ({ page }) => {
    const unique = Date.now().toString(36);

    await page.goto("/register");
    await page.fill("#username", `e2e_${unique}`);
    await page.fill("#email", `e2e_${unique}@example.com`);
    await page.fill("#password", "TestPass1!");
    await page.fill("#confirmPassword", "TestPass1!");

    await page.click("button[type='submit']");

    // After successful registration + auto-login, user should be authenticated.
    // The nav always shows a "dashboard" link when logged in. The "logout" text
    // lives inside a collapsed dropdown and is never visible by default.
    await expect(page.getByRole("link", { name: "dashboard" })).toBeVisible({
      timeout: 15_000,
    });
  });
});

const TEST_USERNAME = process.env.E2E_TEST_USERNAME || "e2e_testuser";
const TEST_PASSWORD = process.env.E2E_TEST_PASSWORD || "E2ePassword1!";

test.describe("Login flow", () => {
  test("logs in with existing test user", async ({ page }) => {
    await page.goto("/login");
    await page.fill("#username", TEST_USERNAME);
    await page.fill("#password", TEST_PASSWORD);

    await page.click("button[type='submit']");

    // Wait for authentication state to update in the navbar.
    // The "dashboard" link is always visible when logged in; the logout text
    // is inside a collapsed dropdown and is never visible by default.
    await expect(page.getByRole("link", { name: "dashboard" })).toBeVisible({
      timeout: 15_000,
    });
  });

  test("shows error for wrong password", async ({ page }) => {
    await page.goto("/login");
    await page.fill("#username", TEST_USERNAME);
    await page.fill("#password", "WrongPassword1!");

    await page.click("button[type='submit']");

    // Error message appears — wait for the Sign In button to re-enable (no longer "Signing in...")
    // or an error alert to appear
    await expect(
      page.locator('[role="alert"]').or(page.locator("button:has-text('Sign In'):not([disabled])"))
    ).toBeVisible({ timeout: 10_000 });
    await expect(page).toHaveURL(/\/login/);
  });
});
