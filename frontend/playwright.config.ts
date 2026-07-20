import { defineConfig, devices } from '@playwright/test'

export default defineConfig({
  testDir: './e2e',
  timeout: 60_000,
  expect: { timeout: 10_000 },
  fullyParallel: false,
  retries: 0,
  reporter: [['list']],
  use: {
    baseURL: 'http://127.0.0.1:5173',
    locale: 'zh-CN',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      // 本机 Playwright chromium 二进制下载受限，使用系统 Edge（Chromium 内核）。
      // 如已执行 npx playwright install chromium，可移除 channel 改用自带浏览器。
      name: 'chromium',
      use: { ...devices['Desktop Chrome'], channel: 'msedge' },
    },
  ],
  webServer: {
    command: 'npm run dev',
    url: 'http://127.0.0.1:5173',
    reuseExistingServer: true,
    timeout: 120_000,
  },
})
