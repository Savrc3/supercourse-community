import { defineConfig, devices } from '@playwright/test'

// Electron 默认占用 4173；测试使用独立端口，避免命中旧的桌面进程资源。
const e2ePort = process.env.E2E_PORT ?? '4174'

export default defineConfig({
  testDir: './e2e',
  testIgnore: /real-data\.spec\.ts/,
  timeout: 30_000,
  fullyParallel: false,
  use: {
    baseURL: `http://localhost:${e2ePort}`,
    trace: 'off',
  },
  projects: [
    { name: 'desktop', use: { ...devices['Desktop Chrome'] } },
    { name: 'mobile', use: { ...devices['Pixel 7'] } },
  ],
  webServer: {
    command: `npm run preview --workspace @supercourse/web -- --host localhost --port ${e2ePort}`,
    url: `http://localhost:${e2ePort}`,
    reuseExistingServer: true,
    timeout: 60_000,
  },
})
