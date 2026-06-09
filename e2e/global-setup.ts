import { chromium } from "@playwright/test";

// Credentials match the defaults the specs fall back to (see auth-flow.spec.ts).
const TEST_USERNAME = process.env.E2E_TEST_USERNAME || "e2e_testuser";
const TEST_PASSWORD = process.env.E2E_TEST_PASSWORD || "E2ePassword1!";
const TEST_EMAIL = process.env.E2E_TEST_EMAIL || "e2e_testuser@example.com";

/**
 * Ensure a known authenticated user exists and persist its session.
 *
 * Tries to register the test user (first run); if registration fails because
 * the user already exists, falls back to logging in. The resulting session is
 * written to .auth/user.json, which the config uses as the default storageState.
 *
 * Auth detection: the nav always shows a "dashboard" link when authenticated.
 * The "logout" text is inside a collapsed dropdown, so it is never visible by
 * default — do not rely on it for waitFor.
 *
 * Middleware note: /login and /register redirect to / when auth_token cookie is
 * present. After a successful register the user is already authenticated, so
 * page.goto("/login") lands on / — detect this by checking page.url().
 */
async function globalSetup(): Promise<void> {
  const baseURL = process.env.E2E_BASE_URL || "http://localhost:3000";
  // __dirname + literal segments — no external input, so no traversal risk.
  const authFile = `${__dirname}/.auth/user.json`;

  const browser = await chromium.launch();
  const page = await browser.newPage({ baseURL });

  // "dashboard" link is always visible in the nav when authenticated.
  const dashboardLink = page.getByRole("link", { name: "dashboard" });

  // First run: register (auto-logs in on success).
  await page.goto("/register");
  await page.fill("#username", TEST_USERNAME);
  await page.fill("#email", TEST_EMAIL);
  await page.fill("#password", TEST_PASSWORD);
  await page.fill("#confirmPassword", TEST_PASSWORD);
  await page.click("button[type='submit']");

  try {
    await dashboardLink.waitFor({ state: "visible", timeout: 10_000 });
  } catch {
    // Registration may have failed (user already exists) or succeeded but the
    // dashboard link wasn't detected yet. Navigate to /login to either:
    //   a) Fill the login form (if not yet authenticated).
    //   b) Detect the middleware redirect to / (auth_token cookie already set).
    await page.goto("/login");
    const afterGoto = page.url();
    if (afterGoto.includes("/login")) {
      // Not yet authenticated — log in explicitly.
      await page.fill("#username", TEST_USERNAME);
      await page.fill("#password", TEST_PASSWORD);
      await page.click("button[type='submit']");
      await dashboardLink.waitFor({ state: "visible", timeout: 15_000 });
    }
    // else: middleware redirected to / — user is already authenticated, fall through.
  }

  await page.context().storageState({ path: authFile });
  await browser.close();
}

export default globalSetup;
