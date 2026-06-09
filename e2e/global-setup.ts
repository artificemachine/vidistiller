import { chromium } from "@playwright/test";
import path from "path";

// Credentials match the defaults the specs fall back to (see auth-flow.spec.ts).
const TEST_USERNAME = process.env.E2E_TEST_USERNAME || "e2e_testuser";
const TEST_PASSWORD = process.env.E2E_TEST_PASSWORD || "E2ePassword1!";
const TEST_EMAIL = process.env.E2E_TEST_EMAIL || "e2e_testuser@example.com";

/**
 * Ensure a known authenticated user exists and persist its session.
 *
 * Tries to register the test user (first run); if registration fails because the
 * user already exists, falls back to logging in. The resulting session is written
 * to .auth/user.json, which the config uses as the default storageState.
 */
async function globalSetup(): Promise<void> {
  const baseURL = process.env.E2E_BASE_URL || "http://localhost:3000";
  const authFile = path.join(__dirname, ".auth", "user.json");

  const browser = await chromium.launch();
  const page = await browser.newPage({ baseURL });

  const loggedIn = page.getByRole("button", { name: "Logout" });

  // First run: register (auto-logs in on success).
  await page.goto("/register");
  await page.fill("#username", TEST_USERNAME);
  await page.fill("#email", TEST_EMAIL);
  await page.fill("#password", TEST_PASSWORD);
  await page.fill("#confirmPassword", TEST_PASSWORD);
  await page.click("button[type='submit']");

  try {
    await loggedIn.waitFor({ state: "visible", timeout: 10_000 });
  } catch {
    // User already exists (or auto-login skipped) — log in explicitly.
    await page.goto("/login");
    await page.fill("#username", TEST_USERNAME);
    await page.fill("#password", TEST_PASSWORD);
    await page.click("button[type='submit']");
    await loggedIn.waitFor({ state: "visible", timeout: 15_000 });
  }

  await page.context().storageState({ path: authFile });
  await browser.close();
}

export default globalSetup;
