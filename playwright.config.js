import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e',
  timeout: 15_000,
  retries: 0,
  reporter: 'list',

  use: {
    baseURL: 'http://localhost:5173',
    // Software-rendered WebGL so Mapbox GL initialises without a GPU
    launchOptions: {
      args: ['--use-gl=swiftshader', '--disable-web-security'],
    },
  },

  // Spin up `serve .` before running tests, tear it down after
  webServer: {
    command: 'npx serve . -p 5173 --no-clipboard',
    url: 'http://localhost:5173',
    reuseExistingServer: !process.env.CI,
    timeout: 10_000,
  },

  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
  ],
});
