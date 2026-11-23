import { describe, expect, it } from 'vitest';
import { layout, MIN_WIDTH, type Entry } from './timeline';

const e = (id: string, start: string | null, end: string | null, granularity = 'hour'): Entry => ({
  entry_id: id,
  claim_id: id,
  label: id,
  attribute: 'a',
  modality: 'sensor',
  granularity,
  start,
  end,
});

describe('layout', () => {
  it('places dated entries as fractions of the span, in time order', () => {
    const out = layout([
      e('late', '2015-08-05T12:00:00Z', '2015-08-05T13:00:00Z'),
      e('early', '2015-08-05T00:00:00Z', '2015-08-05T01:00:00Z'),
    ]);
    expect(out.placed.map((p) => p.entry.entry_id)).toEqual(['early', 'late']);
    expect(out.placed[0]?.left).toBe(0);
    expect(out.placed[1]?.left).toBeCloseTo(12 / 13, 10);
    expect(out.placed.every((p) => p.left >= 0 && p.left + p.width <= 1 + 1e-9)).toBe(true);
  });

  it('never places an unknown time on the axis', () => {
    const out = layout([e('known', '2015-08-05T00:00:00Z', '2015-08-05T01:00:00Z'), e('unknown', null, null, 'unknown')]);
    expect(out.placed.map((p) => p.entry.entry_id)).toEqual(['known']);
    expect(out.unknown.map((x) => x.entry_id)).toEqual(['unknown']);
  });

  it('keeps an instant visible and handles an empty or all-unknown case', () => {
    const out = layout([e('a', '2015-08-05T00:00:00Z', '2015-08-05T00:00:00Z'), e('b', '2015-08-06T00:00:00Z', '2015-08-06T01:00:00Z')]);
    expect(out.placed[0]?.width).toBeGreaterThanOrEqual(MIN_WIDTH);
    expect(layout([]).placed).toEqual([]);
    expect(layout([e('u', null, null, 'unknown')]).from).toBeNull();
  });
});
