/** Timeline layout (FR-UI-3). Pure: positions are fractions of the dated span; entries with an
 *  unknown time are never placed on the axis (they are listed apart: unknown is not "now"). */
export interface Entry {
  entry_id: string;
  claim_id: string;
  label: string;
  attribute: string;
  modality: string;
  granularity: string;
  start?: string | null | undefined;
  end?: string | null | undefined;
}

export interface Placed<T extends Entry> {
  entry: T;
  left: number; // 0..1
  width: number; // 0..1, at least `MIN_WIDTH` so an hour is still visible
}

export const MIN_WIDTH = 0.006;

export function layout<T extends Entry>(entries: readonly T[]): { placed: Placed<T>[]; unknown: T[]; from: string | null; to: string | null } {
  const dated = entries.filter((e) => e.start && e.granularity !== 'unknown');
  const unknown = entries.filter((e) => !e.start || e.granularity === 'unknown');
  if (dated.length === 0) return { placed: [], unknown: [...unknown], from: null, to: null };
  const starts = dated.map((e) => Date.parse(e.start as string));
  const ends = dated.map((e) => Date.parse((e.end ?? e.start) as string));
  const lo = Math.min(...starts);
  const hi = Math.max(...ends, lo + 1);
  const span = hi - lo;
  const placed = dated
    .map((entry, i) => {
      const s = starts[i] ?? lo;
      const e = ends[i] ?? s;
      return { entry, left: (s - lo) / span, width: Math.max(MIN_WIDTH, (e - s) / span) };
    })
    .sort((a, b) => a.left - b.left || a.entry.claim_id.localeCompare(b.entry.claim_id));
  return { placed, unknown: [...unknown], from: new Date(lo).toISOString(), to: new Date(hi).toISOString() };
}
