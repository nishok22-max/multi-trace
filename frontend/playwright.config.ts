import { mkdtempSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { defineConfig } from '@playwright/test';

// One throwaway data directory per run; workers inherit it through the environment.
const dataDir = (process.env['PW_E2E_DIR'] ??= mkdtempSync(join(tmpdir(), 'trace-e2e-')));
const port = 8765;

/** C-12: the five specs run against the REAL app (built frontend + API) on loopback, with the
 *  enforcing CSP header the server sends. The browser is the system Edge so no download is needed;
 *  set PW_CHANNEL=chrome (or unset it for the bundled Chromium) to use another. */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 90_000,
  reporter: [['list']],
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    channel: process.env['PW_CHANNEL'] ?? 'msedge',
    headless: true,
    trace: 'off',
  },
  webServer: {
    command: process.platform === 'win32'
      ? '..\\backend\\.venv\\Scripts\\python.exe -m tools.e2e_server'
      : '../backend/.venv/bin/python -m tools.e2e_server',
    cwd: '../backend',
    url: `http://127.0.0.1:${port}/healthz`,
    timeout: 300_000,
    reuseExistingServer: false,
    stdout: 'ignore',
    stderr: 'ignore',
    env: { TRACE_E2E_DATA: dataDir, TRACE_E2E_PORT: String(port) },
  },
});
