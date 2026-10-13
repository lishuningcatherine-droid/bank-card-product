import { defineConfig, devices } from "@playwright/test";

const WEB = "http://127.0.0.1:3010";
const API = "http://127.0.0.1:8010";

export default defineConfig({
  testDir: "./e2e",
  timeout: 30_000,
  fullyParallel: false,
  workers: 1,
  retries: process.env.CI ? 1 : 0,
  reporter: [["list"], ["html", { open: "never" }]],
  use: { baseURL: WEB, trace: "retain-on-failure" },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: [
    { command: "bash e2e/start-api.sh", url: `${API}/api/v1/ready`, timeout: 180_000, reuseExistingServer: !process.env.CI },
    {
      // The E2E database is re-seeded (new IDs) on every run, so cached API responses from a previous run must go.
      command: "rm -rf .next/cache/fetch-cache && pnpm start -p 3010 -H 127.0.0.1",
      url: WEB,
      timeout: 120_000,
      reuseExistingServer: !process.env.CI,
      env: { API_INTERNAL_URL: API, REVALIDATE_SECRET: "e2e-secret-e2e-secret-e2e-secret-e2e" },
    },
  ],
});
