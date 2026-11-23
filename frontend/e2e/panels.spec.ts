import { expect, test } from '@playwright/test';
import { info, login } from './helpers';

test('e2e_all_panels_same_version', async ({ page }) => {
  await login(page);
  await page.goto('/case/?id=case-main');
  await expect(page.getByTestId('conflict-card')).toBeVisible();
  await page.locator('[data-testid=show-proof][data-modality=text]').click();
  await expect(page.getByTestId('proof-panel')).toBeVisible();
  const badges = await page.getByTestId('version-badge').allTextContents();
  expect(badges.length).toBeGreaterThanOrEqual(3);  // header, conflict card, proof panel
  expect(new Set(badges).size, badges.join(' | ')).toBe(1);
  const manifest = info().cases['case-main']?.manifest_hash ?? '';
  expect(badges[0]).toContain(manifest.slice(0, 12));
  // the expert view of the same case shows the same version and a green integrity badge
  await page.goto('/case/expert/?id=case-main');
  await expect(page.getByTestId('claims-table')).toBeVisible();
  const expert = await page.getByTestId('version-badge').allTextContents();
  expect(new Set([...expert, badges[0]]).size).toBe(1);
  await expect(page.getByTestId('integrity-badge')).toHaveAttribute('data-ok', 'true');
  await expect(page.getByTestId('envelope-view')).toBeVisible();
});

test('the story, outcome labels and uncalibrated badge are text, not colour alone', async ({ page }) => {
  await login(page);
  await page.goto('/case/?id=case-main');
  await expect(page.getByTestId('outcome-badge')).toHaveText("They disagree");
  await expect(page.getByTestId('story')).toContainText('Step 1');
  await expect(page.getByTestId('sources')).toContainText('synthetic');
  await expect(page.getByTestId('confidence').first()).toContainText('uncalibrated');
  await expect(page.getByTestId('magnitude')).toContainText('observed');
});

test('login rejects a wrong password and the review queue lists the ambiguous mention', async ({ page }) => {
  await page.goto('/login/');
  await page.getByTestId('username').fill('rita');
  await page.getByTestId('password').fill('definitely wrong');
  await page.getByTestId('login').click();
  await expect(page.getByTestId('login-error')).toContainText('Wrong user name or password');
  await login(page);
  await page.goto('/review/?id=case-main');
  await expect(page.getByTestId('queue-item').first()).toContainText('Which machine is this?');
  await expect(page.getByTestId('candidate').first()).toContainText('machine:21');
});

test('expert view filters and the evaluation page shows the report', async ({ page }) => {
  await login(page, 'eve');
  await page.goto('/case/expert/?id=case-main');
  await expect(page.getByTestId('claim-row').first()).toBeVisible();
  const all = await page.getByTestId('claim-row').count();
  await page.getByTestId('filter-modality').selectOption('text');
  const text = await page.getByTestId('claim-row').count();
  expect(text).toBeGreaterThan(0);
  expect(text).toBeLessThan(all);
  await page.getByTestId('filter-outcome').selectOption('disagree');
  await expect(page.getByTestId('comparison-row').first()).toHaveAttribute('data-outcome', 'disagree');
  await page.getByTestId('replay-button').click();
  await expect(page.getByTestId('replay-result')).toHaveAttribute('data-match', 'true', { timeout: 60_000 });
  await page.goto('/eval/');
  await expect(page.getByTestId('report')).toBeVisible();
});

test('NFR-10: the proof is one click and the decision form two clicks from the case page', async ({ page }) => {
  await login(page);
  await page.goto('/case/?id=case-main');
  await expect(page.getByTestId('conflict-card')).toBeVisible();
  await page.locator('[data-testid=show-proof][data-modality=text]').click(); // click 1
  await expect(page.getByTestId('proof-quote')).toBeVisible();
  await page.getByTestId('resolve').click(); // click 1 towards the decision
  await expect(page.getByTestId('decision-panel')).toBeVisible(); // the form is there: no second hop
});
