/** PDF-point rectangles (origin bottom-left, y up) to pixels of the server-rendered page PNG
 *  (origin top-left, y down). The PNG covers the page's CropBox at `dpi`; a CropBox that does not
 *  start at (0, 0) is not supported by the overlay (the server renders the CropBox, and the
 *  overlay assumes a zero origin: it is hidden rather than drawn in the wrong place). */
export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

export const RENDER_DPI = 150;

export function ptToPx(rect: Rect, pageHeightPx: number, dpi: number = RENDER_DPI): Rect {
  const s = dpi / 72;
  const x = rect.x * s;
  const w = rect.w * s;
  const h = rect.h * s;
  const y = pageHeightPx - (rect.y + rect.h) * s;
  return { x: Math.floor(x), y: Math.floor(y), w: Math.ceil(x + w) - Math.floor(x), h: Math.ceil(y + h) - Math.floor(y) };
}

/** Scales a pixel rectangle of the natural image to the size it is displayed at. */
export function toDisplay(rect: Rect, naturalWidth: number, displayWidth: number): Rect {
  const k = naturalWidth > 0 ? displayWidth / naturalWidth : 1;
  return { x: rect.x * k, y: rect.y * k, w: rect.w * k, h: rect.h * k };
}

/** One rectangle per text line is kept as is: the overlay draws every rect (multi-line spans). */
export function visibleRects(rects: readonly Rect[]): Rect[] {
  return rects.filter((r) => Number.isFinite(r.x + r.y + r.w + r.h) && r.w > 0 && r.h > 0);
}
