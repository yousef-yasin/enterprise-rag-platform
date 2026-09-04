import { defineConfig, devices } from "@playwright/test";

// Golden E2E: drives the real UI against a running stack. In CI this is the
// docker-compose stack with APP_PROFILE=ci (fake providers); locally it targets
// whatever E2E_BASE_URL points at (defaults to the Vite dev server). Use
// `localhost`, not `127.0.0.1` — Vite v5 binds `::1` (IPv6) by default.
const BASE_URL = process.env.E2E_BASE_URL ?? "http://localhost:5173";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 60_000,
  expect: { timeout: 15_000 },
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: process.env.CI ? [["github"], ["html", { open: "never" }]] : "list",
  use: {
    baseURL: BASE_URL,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: process.env.E2E_BASE_URL
    ? undefined
    : {
        command: "npm run dev",
        url: BASE_URL,
        reuseExistingServer: !process.env.CI,
        timeout: 60_000,
      },
});
