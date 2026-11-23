import { readFileSync, writeFileSync } from 'node:fs';
import { join } from 'node:path';
import { expect, test } from '@playwright/test';
import { info, login } from './helpers';

test('e2e_byte_flip_evidence_changed', async ({ page }) => {
  await login(page);
  await page.goto('/case/?id=case-flip');
  await expect(page.getByTestId('integrity-badge')).toHaveAttribute('data-ok', 'true');
  await page.locator('[data-testid=show-proof][data-modality=text]').click();
  await page.getByTestId('recheck-button').click();
  await expect(page.getByTestId('recheck-result')).toHaveAttribute('data-match', 'true');

  // flip one byte of the stored source, behind the server's back
  const sha = info().cases['case-flip']?.report_sha;
  if (!sha) throw new Error('missing report sha');
  const blob = join(info().data_dir, 'blobs', sha.slice(0, 2), sha);
  const bytes = readFileSync(blob);
  bytes[Math.floor(bytes.length / 2)] = (bytes[Math.floor(bytes.length / 2)] ?? 0) ^ 0xff;
  writeFileSync(blob, bytes);

  await page.getByTestId('recheck-button').click();
  const result = page.getByTestId('recheck-result');
  await expect(result).toHaveAttribute('data-match', 'false');
  await expect(result).toContainText('Evidence changed');
  await page.reload();
  await expect(page.getByTestId('integrity-badge')).toHaveAttribute('data-ok', 'false');
  await expect(page.getByTestId('integrity-badge')).toContainText('FAILED');
});
