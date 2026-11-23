import { expect, test } from '@playwright/test';
import { login, median } from './helpers';

test('e2e_decision_card_under_2s', async ({ page }) => {
  await login(page, 'rita');
  const times: number[] = [];
  for (const n of [1, 2, 3]) {
    await page.goto(`/review/?id=case-decide-${n}`);
    await expect(page.getByTestId('queue-item').first()).toBeVisible();
    await expect(page.getByTestId('candidate-list')).toBeVisible();
    await page.getByTestId('entity-select').selectOption('machine:21');
    // the reason rule is enforced before anything is sent
    await page.getByTestId('reason').fill('too short');
    await page.getByTestId('decide').click();
    await expect(page.getByTestId('reason-error')).toBeVisible();
    await page.getByTestId('reason').fill('The register lists Press 21 as machine 21 on line 2.');
    const started = Date.now();
    await page.getByTestId('decide').click();
    await expect(page.getByTestId('decided-notice')).toContainText('Version 2');
    times.push(Date.now() - started);
    await page.goto(`/case/?id=case-decide-${n}`);
    await expect(page.getByTestId('version-badge').first()).toContainText('version 2');
    await expect(page.getByTestId('integrity-badge')).toHaveAttribute('data-ok', 'true');
  }
  expect(median(times), `decision times ${times.join(', ')} ms`).toBeLessThan(2000);
});

test('a decided item cannot be decided again and a viewer cannot decide', async ({ page, browser }) => {
  await login(page, 'rita');
  await page.goto('/review/?id=case-decide-1');
  await expect(page.getByTestId('already-decided')).toBeVisible();
  const other = await browser.newPage();
  await login(other, 'vik');
  await other.goto('/review/?id=case-main');
  await other.getByTestId('entity-select').selectOption('machine:21');
  await other.getByTestId('reason').fill('A viewer should not be able to do this at all.');
  await other.getByTestId('decide').click();
  await expect(other.getByTestId('decision-error')).toContainText('role does not allow');
  await other.close();
});
