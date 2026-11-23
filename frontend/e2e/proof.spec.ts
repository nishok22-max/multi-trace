import { expect, test } from '@playwright/test';
import { login, median, watchProblems } from './helpers';

test('e2e_proof_under_1s', async ({ page }) => {
  const problems = watchProblems(page);
  await login(page);
  await page.goto('/case/?id=case-main');
  await expect(page.getByTestId('conflict-card')).toBeVisible();
  const times: number[] = [];
  for (let run = 0; run < 5; run += 1) {
    const started = Date.now();
    await page.locator('[data-testid=show-proof][data-modality=text]').click();
    await expect(page.getByTestId('proof-quote')).toBeVisible();
    await expect(page.getByTestId('region-overlay').first()).toBeVisible();
    await expect(page.getByTestId('region-image')).toHaveJSProperty('complete', true);
    times.push(Date.now() - started);
    await page.getByRole('button', { name: 'Close proof' }).click();
  }
  expect(median(times), `proof times ${times.join(', ')} ms`).toBeLessThan(1000);
  // the cited quote is on the page as plain text and the overlay sits on the rendered page
  await page.locator('[data-testid=show-proof][data-modality=text]').click();
  await expect(page.getByTestId('proof-quote')).toContainText('ran normally');
  const box = await page.getByTestId('region-overlay').first().boundingBox();
  const image = await page.getByTestId('region-image').boundingBox();
  expect(box && image && box.y >= image.y && box.y + box.height <= image.y + image.height).toBeTruthy();
  expect(problems).toEqual([]);
});

test('proof for the sensor side shows the chart, the band caption and a version badge', async ({ page }) => {
  await login(page);
  await page.goto('/case/?id=case-main');
  await page.locator('[data-testid=show-proof][data-modality=sensor]').click();
  await expect(page.getByTestId('sensor-chart')).toBeVisible();
  await expect(page.getByTestId('sensor-chart')).toContainText('alarm threshold');
  await expect(page.getByTestId('proof-panel').getByTestId('version-badge')).toBeVisible();
  await page.getByTestId('recheck-button').click();
  await expect(page.getByTestId('recheck-result')).toHaveAttribute('data-match', 'true');
});
