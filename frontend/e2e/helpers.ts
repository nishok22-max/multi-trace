import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { expect, type Page } from '@playwright/test';

export interface Info {
  data_dir: string;
  password: string;
  cases: Record<string, { report_sha: string; manifest_hash: string }>;
}

export function info(): Info {
  const dir = process.env['PW_E2E_DIR'];
  if (!dir) throw new Error('PW_E2E_DIR is not set');
  return JSON.parse(readFileSync(join(dir, 'e2e_info.json'), 'utf-8')) as Info;
}

export async function login(page: Page, user = 'rita'): Promise<void> {
  await page.goto('/login/');
  await page.getByTestId('username').fill(user);
  await page.getByTestId('password').fill(info().password);
  await page.getByTestId('login').click();
  await expect(page.getByTestId('case-list')).toBeVisible();
}

export function median(values: number[]): number {
  const sorted = [...values].sort((a, b) => a - b);
  return sorted[Math.floor(sorted.length / 2)] ?? Number.NaN;
}

/** Page errors and console messages that mean the CSP or the app misbehaved. */
export function watchProblems(page: Page): string[] {
  const problems: string[] = [];
  page.on('pageerror', (e) => problems.push(`pageerror: ${e.message}`));
  page.on('console', (m) => {
    if (m.type() === 'error') problems.push(`console: ${m.text()}`);
  });
  return problems;
}
