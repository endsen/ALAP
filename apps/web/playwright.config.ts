import { defineConfig } from "@playwright/test";
export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 90000,
  expect: { timeout: 15000 },
  workers: 1,
  use: {
    baseURL: "http://127.0.0.1:53000",
    viewport: { width: 1440, height: 1000 },
    trace: "off",
    actionTimeout: 15000,
    launchOptions: { executablePath: process.env.ALAP_BROWSER_EXECUTABLE },
    screenshot: "only-on-failure",
  },
  reporter: [["list"]],
  webServer: [
    {
      command: `${process.env.CI ? "python" : ".venv/bin/python"} -m tests.web_server`,
      cwd: "../..",
      url: "http://127.0.0.1:58000/api/v1/me",
      reuseExistingServer: false,
      gracefulShutdown: { signal: "SIGTERM", timeout: 15000 },
      timeout: 60000,
    },
    {
      command: "npm run start -- --port 53000",
      url: "http://127.0.0.1:53000",
      reuseExistingServer: false,
      gracefulShutdown: { signal: "SIGTERM", timeout: 15000 },
      timeout: 60000,
    },
  ],
});
