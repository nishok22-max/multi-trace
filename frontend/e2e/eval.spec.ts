import { expect, test } from '@playwright/test';
import { login } from './helpers';

test('e2e_eval_page_renders_report', async ({ page }) => {
  await login(page, 'eve');
  await page.goto('/eval/');
  await expect(page.getByTestId('report')).toBeVisible();
  await expect(page.getByTestId('split')).toHaveText('dev');
  // every fault type is reported with its own precision, recall, F1 and n
  await expect(page.getByTestId('fault-row')).toHaveCount(5);
  await expect(page.getByTestId('per-fault')).toContainText('contradicting_note');
  // rates carry their Wilson intervals, never a bare percentage
  await expect(page.getByTestId('false-alarm')).toContainText('95% CI');
  await expect(page.getByTestId('false-conflicts')).toContainText('95% CI');
  // the two invariants the product promises are shown as numbers
  await expect(page.getByTestId('invariants')).toContainText('Gaps read as normal: 0');
  await expect(page.getByTestId('invariants')).toContainText('averaged outputs: 0');
  // calibration is honest: no fit exists, so it says so, and every bin shows its count
  await expect(page.getByTestId('calibration')).toContainText('not fitted yet');
  await expect(page.getByTestId('calibration')).toContainText('uncalibrated');
  await expect(page.getByTestId('bin-row')).toHaveCount(10);
  const counts = await page.getByTestId('bin-row').evaluateAll((rows) => rows.map((r) => Number(r.getAttribute('data-n'))));
  expect(counts.reduce((a, b) => a + b, 0)).toBeGreaterThan(0);
  // the baselines' real outputs are on the page
  await expect(page.locator('[data-testid=baseline][data-name=tfidf]')).toContainText('[note]');
  await expect(page.locator('[data-testid=baseline][data-name=fusion]')).toContainText('last write wins');
  await expect(page.locator('[data-testid=baseline][data-name=nogate]')).toContainText('non-comparable');
});

test('the report is for the evaluator role only', async ({ page }) => {
  await login(page, 'vik');
  await page.goto('/eval/');
  await expect(page.getByTestId('eval-denied')).toBeVisible();
  await expect(page.getByTestId('report')).toHaveCount(0);
});
