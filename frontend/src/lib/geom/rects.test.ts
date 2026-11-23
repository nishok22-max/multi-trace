import { describe, expect, it } from 'vitest';
import { ptToPx, toDisplay, visibleRects } from './rects';

describe('ptToPx', () => {
  it('flips the y axis and scales 72 dpi points to 150 dpi pixels', () => {
    // a 100 x 20 pt box with its bottom-left at (72, 700) on an 842 pt page rendered at 150 dpi
    const heightPx = 842 * (150 / 72);
    const px = ptToPx({ x: 72, y: 700, w: 100, h: 20 }, heightPx);
    expect(px.x).toBe(Math.floor(72 * (150 / 72)));
    expect(px.w).toBeGreaterThanOrEqual(Math.floor(100 * (150 / 72)));
    // top edge: page height minus (y + h) points
    expect(px.y).toBe(Math.floor(heightPx - 720 * (150 / 72)));
    expect(px.h).toBeGreaterThanOrEqual(Math.floor(20 * (150 / 72)));
  });

  it('rounds outward so the box never shrinks', () => {
    const px = ptToPx({ x: 10.2, y: 10.2, w: 10.4, h: 10.4 }, 1000);
    const s = 150 / 72;
    expect(px.x).toBeLessThanOrEqual(10.2 * s);
    expect(px.x + px.w).toBeGreaterThanOrEqual((10.2 + 10.4) * s);
  });

  it('keeps one rectangle per line of a multi-line span', () => {
    const rects = [
      { x: 72, y: 700, w: 400, h: 14 },
      { x: 72, y: 686, w: 120, h: 14 },
    ];
    expect(visibleRects(rects)).toHaveLength(2);
    expect(visibleRects([{ x: 0, y: 0, w: 0, h: 5 }, { x: Number.NaN, y: 0, w: 1, h: 1 }])).toHaveLength(0);
  });
});

describe('toDisplay', () => {
  it('scales to the displayed width', () => {
    expect(toDisplay({ x: 100, y: 50, w: 200, h: 20 }, 1000, 500)).toEqual({ x: 50, y: 25, w: 100, h: 10 });
    expect(toDisplay({ x: 1, y: 1, w: 1, h: 1 }, 0, 500)).toEqual({ x: 1, y: 1, w: 1, h: 1 });
  });
});
