import { describe, expect, it } from 'vitest';
import { alarmBand, escapeHtml, MAD_TO_SIGMA, sensorChartOption, tooltipFormatter } from './options';

const PAYLOAD = '<img src=x onerror=alert(1)>';

describe('escapeHtml', () => {
  it('escapes every character that can open markup', () => {
    expect(escapeHtml(PAYLOAD)).toBe('&lt;img src=x onerror=alert(1)&gt;');
    expect(escapeHtml(`"'&`)).toBe('&quot;&#39;&amp;');
    expect(escapeHtml(null)).toBe('null');
  });
});

describe('alarmBand', () => {
  const env = { med: { vibration: 40, flat: 10 }, mad: { vibration: 3, flat: 0 }, T_star: 4 };
  it('is the median plus or minus T* times the robust scale', () => {
    const band = alarmBand(env, 'vibration');
    expect(band).not.toBeNull();
    expect(band?.high).toBeCloseTo(40 + 4 * MAD_TO_SIGMA * 3, 10);
    expect(band?.low).toBeCloseTo(40 - 4 * MAD_TO_SIGMA * 3, 10);
  });
  it('uses the claim threshold when one is given and draws no band for a degenerate scale', () => {
    expect(alarmBand(env, 'vibration', 2)?.high).toBeCloseTo(40 + 2 * MAD_TO_SIGMA * 3, 10);
    expect(alarmBand(env, 'flat')).toBeNull();
    expect(alarmBand(env, 'missing')).toBeNull();
  });
});

describe('tooltip formatter', () => {
  it('never lets a channel name become markup', () => {
    const html = tooltipFormatter('Asia/Kolkata')([
      { axisValue: '2015-08-05T18:30:00Z', seriesName: PAYLOAD, value: ['x', 3] },
    ]);
    expect(html).not.toContain('<img');
    expect(html).toContain('&lt;img');
  });
  it('shows a missing reading as such and hides band helper series', () => {
    const html = tooltipFormatter('UTC')([
      { axisValue: '2015-08-05T01:00:00Z', seriesName: 'vibration', value: ['x', null] },
      { axisValue: '2015-08-05T01:00:00Z', seriesName: 'band:vibration', value: ['x', 1] },
    ]);
    expect(html).toContain('no reading');
    expect(html).not.toContain('band:');
  });
});

describe('sensorChartOption', () => {
  const rows = [
    { ts: '2015-08-05T01:00:00Z', vibration: 40 },
    { ts: '2015-08-05T02:00:00Z', vibration: null },
    { ts: '2015-08-05T03:00:00Z', vibration: 42 },
  ];
  it('keeps a missing hour as a hole and never connects across it', () => {
    const option = sensorChartOption({ rows, channels: ['vibration'], envelope: null, tStar: null, tz: 'UTC' });
    const series = (option['series'] as Array<Record<string, unknown>>)[0];
    expect(series?.['connectNulls']).toBe(false);
    expect((series?.['data'] as unknown[][])[1]?.[1]).toBeNull();
    expect(series?.['markArea']).toBeUndefined(); // no envelope, no band
  });
  it('draws the band from the envelope', () => {
    const option = sensorChartOption({
      rows,
      channels: ['vibration'],
      envelope: { med: { vibration: 40 }, mad: { vibration: 3 }, T_star: 4 },
      tStar: null,
      tz: 'UTC',
    });
    const series = (option['series'] as Array<Record<string, unknown>>)[0];
    expect(series?.['markArea']).toBeDefined();
  });
});
