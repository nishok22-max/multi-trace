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
    <section aria-label="Timeline" data-testid="timeline" className="card card-pad">
      <p className="eyebrow">Timeline</p>
      {from && to ? (
        <p className="small muted" style={{ margin: '0 0 12px' }}>
          {localDateTime(from, tz)} to {localDateTime(to, tz)} (plant-local). Select an entry to see its proof.
        </p>
      ) : null}
      <ul className="tl">
        {placed.map(({ entry, left, width }) => (
          <li key={entry.entry_id} data-testid="timeline-entry" data-modality={entry.modality}>
            <button type="button" className="link" onClick={() => onOpen?.(entry.claim_id)}>
              {entry.label} · {entry.attribute}
            </button>
            <div className="tl-track">
              <div className="tl-bar" style={{ left: `${left * 100}%`, width: `${width * 100}%` }} title={`${entry.granularity} · observed ${observed(entry.claim_id)}`} />
            </div>
          </li>
        ))}
      </ul>
      {unknown.length > 0 ? (
        <div data-testid="timeline-unknown" style={{ marginTop: 16 }}>
          <p className="eyebrow">Time unknown (not placed on the axis)</p>
          <ul className="small" style={{ margin: 0, paddingLeft: 18 }}>
            {unknown.map((e) => (
              <li key={e.entry_id}>
                {e.label} · {e.attribute}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
