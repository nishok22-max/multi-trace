import { defineConfig } from 'vitest/config';

// Unit tests live next to the code; the Playwright specs in e2e/ are run by `npm run e2e`.
export default defineConfig({
  test: { include: ['src/**/*.test.ts'], environment: 'node' },
});
