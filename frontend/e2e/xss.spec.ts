import { expect, test } from '@playwright/test';
import { login } from './helpers';

test('e2e_xss_fixture_no_dialog_under_csp', async ({ page }) => {
  const dialogs: string[] = [];
  page.on('dialog', async (d) => {
    dialogs.push(d.message());
    await d.dismiss();
  });
  const response = await page.goto('/login/');
  const csp = response?.headers()['content-security-policy'] ?? '';
  expect(csp).toContain("frame-ancestors 'none'");
  expect(csp).not.toContain('unsafe-inline');
  expect(csp).not.toContain('unsafe-eval');
  await login(page);
  await page.goto('/case/?id=case-xss');
  await expect(page.getByTestId('version-badge').first()).toBeVisible();
  // open the proof of the text claim whose quote carries an HTML payload
  await page.locator('[data-testid=show-proof][data-modality=text]').click();
  const quote = page.getByTestId('proof-quote');
  await expect(quote).toContainText('<img src=x onerror=alert(1)>');  // shown as text
  await expect(page.locator('img[src="x"]')).toHaveCount(0);  // never parsed as markup
  await page.goto('/case/expert/?id=case-xss');
  await expect(page.getByTestId('claims-table')).toBeVisible();
  await expect(page.locator('img[src="x"]')).toHaveCount(0);
  expect(await page.evaluate(() => (window as unknown as { __xss?: number }).__xss)).toBeUndefined();
  expect(dialogs).toEqual([]);
});
