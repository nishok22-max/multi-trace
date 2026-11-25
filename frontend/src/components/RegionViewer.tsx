import { useState } from 'react';
import { ptToPx, toDisplay, visibleRects, type Rect } from '../lib/geom/rects';

interface Props {
  src: string;
  alt: string;
  /** PDF-point rectangles (text proofs): converted with the natural height of the page PNG. */
  rectsPt?: Rect[];
  /** Pixel rectangles of the image itself (image proofs, `oriented_px`). */
  rectsPx?: Rect[];
}

/** A server-rendered PNG with one outlined box per rectangle (multi-line spans draw every line).
 *  No PDF bytes reach the browser: the image is the only thing served. */
export default function RegionViewer({ src, alt, rectsPt, rectsPx }: Props) {
  const [size, setSize] = useState<{ nw: number; nh: number; dw: number } | null>(null);
  const boxes = size
    ? visibleRects([
        ...(rectsPt ?? []).map((r) => ptToPx(r, size.nh)),
        ...(rectsPx ?? []),
      ]).map((r) => toDisplay(r, size.nw, size.dw))
    : [];
  return (
    <div className="viewer" data-testid="region-viewer">
      <img
        src={src}
        alt={alt}
                data-testid="region-image"
        onLoad={(e) => {
          const img = e.currentTarget;
          setSize({ nw: img.naturalWidth, nh: img.naturalHeight, dw: img.clientWidth });
        }}
      />
      {boxes.map((b, i) => (
        <div
          key={i}
          data-testid="region-overlay"
          aria-label="Cited region"
          className="box"
          style={{ left: b.x, top: b.y, width: b.w, height: b.h }}
        />
      ))}
    </div>
  );
}
