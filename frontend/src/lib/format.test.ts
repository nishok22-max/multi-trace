import { describe, expect, it } from 'vitest';
import { asRecord, fmt, localDay, localHour, num } from './format';

describe('format', () => {
  it('shows two decimals and n/a for a missing number', () => {
    expect(fmt(3.14159)).toBe('3.14');
    expect(fmt(null)).toBe('n/a');
    expect(fmt(undefined)).toBe('n/a');
  });
  it('formats times in the plant zone, not the browser zone', () => {
    expect(localHour('2015-08-05T18:30:00Z', 'Asia/Kolkata')).toBe('00:00');
    expect(localDay('2015-08-05T18:30:00Z', 'Asia/Kolkata')).toBe('06 Aug 2015');
  });
  it('narrows unknown values safely', () => {
    expect(asRecord({ a: 1 })).toEqual({ a: 1 });
    expect(asRecord([1])).toBeNull();
    expect(asRecord('x')).toBeNull();
    expect(num(2)).toBe(2);
    expect(num('2')).toBeNull();
  });
});
