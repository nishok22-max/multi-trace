import type { Schemas } from '../lib/api/client';
import { localDateTime } from '../lib/format';
import { layout } from '../lib/timeline';

type Claim = Schemas['ClaimRecord'];

/** All claims, events and gaps on one axis. Valid time is the bar; observed time is shown as text
 *  beside each entry. A claim with unknown time is listed apart, never placed on the axis. */
export default function Timeline({
  entries,
  claims,
  tz,
  onOpen,
}: {
  entries: Schemas['TimelineEntry'][];
  claims: Claim[];
  tz: string;
  onOpen?: (claimId: string) => void;
}) {
  const { placed, unknown, from, to } = layout(entries);
  const byId = new Map(claims.map((c) => [c.claim_id, c]));
  const observed = (id: string): string => {
    const at = byId.get(id)?.temporal.observed_time.at;
    return at ? localDateTime(at, tz) : 'not stated';
  };
  return (
    <section aria-label="Timeline" data-testid="timeline" className="rounded border border-slate-400 bg-white p-3">
      <h2 className="mb-2 font-semibold">Timeline</h2>
      {from && to ? (
        <p className="mb-2 text-xs text-slate-700">
          {localDateTime(from, tz)} to {localDateTime(to, tz)} (plant-local)
        </p>
      ) : null}
      <ul className="space-y-1">
        {placed.map(({ entry, left, width }) => (
          <li key={entry.entry_id} data-testid="timeline-entry" data-modality={entry.modality} className="grid grid-cols-[14rem_1fr] items-center gap-2 text-xs">
            <button type="button" className="truncate text-left underline" onClick={() => onOpen?.(entry.claim_id)}>
              {entry.label} · {entry.attribute}
            </button>
            <div className="relative h-4 rounded bg-slate-100">
              <div
                className="absolute top-0 h-4 rounded bg-slate-600"
                style={{ left: `${left * 100}%`, width: `${width * 100}%` }}
                title={`${entry.granularity} · observed ${observed(entry.claim_id)}`}
              />
            </div>
          </li>
        ))}
      </ul>
      {unknown.length > 0 ? (
        <div className="mt-3" data-testid="timeline-unknown">
          <h3 className="text-sm font-semibold">Time unknown (not placed on the axis)</h3>
          <ul className="list-disc pl-5 text-xs">
            {unknown.map((e) => (
              <li key={e.entry_id}>{e.label} · {e.attribute}</li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
