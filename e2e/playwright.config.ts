import { defineConfig, devices } from "@playwright/test";

// E2E runs against the stack stood up by docker-compose.e2e.yml (web :3000, api :8000).
// Override the target with E2E_BASE_URL when running against another environment.
const BASE_URL = process.env.E2E_BASE_URL || "http://localhost:3000";

export default defineConfig({
  testDir: "./tests",
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? "github" : "list",
  timeout: 30_000,
  // global-setup authenticates the test user and writes the default storageState.
  // Specs that need an anonymous session override with test.use({ storageState: ... }).
  globalSetup: "./global-setup.ts",
  use: {
    baseURL: BASE_URL,
    storageState: "./.auth/user.json",
    trace: "on-first-retry",
    screenshot: "only-on-failure",
  },
  projects: [
    { name: "chromium", use: { ...devices["Desktop Chrome"] } },
  ],
});
