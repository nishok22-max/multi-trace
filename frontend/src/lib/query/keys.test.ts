import { describe, expect, it } from 'vitest';
import { keys } from './keys';

describe('query keys', () => {
  it('every versioned key carries the version, so versions never share an answer', () => {
    const versioned = [keys.state, keys.story, keys.conflicts, keys.comparisons, keys.claims, keys.timeline, keys.review, keys.integrity, keys.manifest];
    for (const make of versioned) {
      expect(JSON.stringify(make('c1', 1))).not.toBe(JSON.stringify(make('c1', 2)));
      expect(JSON.stringify(make('c1', 2))).toContain('"version":2');
    }
    expect(JSON.stringify(keys.evidence('c1', 1, 'clm'))).not.toBe(JSON.stringify(keys.evidence('c1', 2, 'clm')));
    expect(JSON.stringify(keys.envelope('c1', 1, 'm'))).not.toBe(JSON.stringify(keys.envelope('c1', 2, 'm')));
  });
  it('another case never shares a key', () => {
    expect(JSON.stringify(keys.state('a', 1))).not.toBe(JSON.stringify(keys.state('b', 1)));
  });
});
