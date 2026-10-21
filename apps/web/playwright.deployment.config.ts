import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/deployment",
  timeout: 120000,
  expect: { timeout: 20000 },
  workers: 1,
  retries: 0,
  use: {
    baseURL: "http://127.0.0.1:3000",
    viewport: { width: 1440, height: 1000 },
    trace: "off",
    screenshot: "off",
    video: "off",
    actionTimeout: 20000,
  },
  reporter: [["list"]],
});
