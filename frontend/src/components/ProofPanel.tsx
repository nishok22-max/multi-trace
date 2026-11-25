import { useQuery } from '@tanstack/react-query';
import { api, unwrap, type Schemas } from '../lib/api/client';
import { keys } from '../lib/query/keys';
import RecheckBadge from './RecheckBadge';
import RegionViewer from './RegionViewer';
import SensorChart from './SensorChart';
import TableWindow from './TableWindow';
import VersionBadge from './VersionBadge';

type Claim = Schemas['ClaimRecord'];

interface Props {
  caseId: string;
  version: number;
  manifestHash: string;
  claim: Claim;
  tz: string;
  onClose?: () => void;
}

/** "Show me the proof": the exact spot the claim cites, for each of the four proof kinds, with the
 *  version it was read at and a re-check. Inferred claims show the evidence of their own pointer
 *  (when they have one) and list the claims they were derived from. */
export default function ProofPanel({ caseId, version, manifestHash, claim, tz, onClose }: Props) {
  const evidence = useQuery({
    queryKey: keys.evidence(caseId, version, claim.claim_id),
    queryFn: async () =>
      unwrap(
        await api.GET('/api/v1/cases/{cid}/versions/{v}/claims/{claim_id}/evidence', {
          params: { path: { cid: caseId, v: version, claim_id: claim.claim_id } },
        }),
      ),
    enabled: claim.evidence !== null && claim.evidence !== undefined,
  });
  const entityId = claim.subject.entity_id ?? null;
  const isSensor = claim.evidence?.kind === 'sensor_window';
  const envelope = useQuery({
    queryKey: keys.envelope(caseId, version, entityId ?? ''),
    enabled: isSensor && entityId !== null,
    queryFn: async () =>
      unwrap(
        await api.GET('/api/v1/cases/{cid}/versions/{v}/entities/{eid}/envelope', {
          params: { path: { cid: caseId, v: version, eid: entityId ?? '' } },
        }),
      ),
  });

  const data = evidence.data;
  const pointer = data?.pointer;
  return (
    <section aria-label="Proof" data-testid="proof-panel" className="proof">
      <header className="card-head">
        <h3>
          Proof: <span data-testid="proof-label">{claim.label ?? claim.claim_id}</span>
        </h3>
        <VersionBadge version={version} manifestHash={manifestHash} />
        {onClose ? (
          <span className="aside">
            <button type="button" className="btn btn-sm" onClick={onClose}>
              Close proof
            </button>
          </span>
        ) : null}
      </header>
      <div className="card-body stack-sm">
        <p style={{ margin: 0 }}>{claim.statement}</p>
        {claim.evidence === null || claim.evidence === undefined ? (
          <p data-testid="derived-note" className="callout">
            This claim is inferred. It has no pointer of its own; it was derived from {(claim.derived_from ?? []).length} other record(s) by rule{' '}
            <code>{claim.method.rule_id}</code>.
          </p>
        ) : evidence.isLoading ? (
          <p className="muted">Loading proof...</p>
        ) : evidence.error ? (
          <p role="alert" data-testid="proof-error" className="callout callout-bad">
            {evidence.error.message}
          </p>
        ) : pointer && data ? (
          <div className="stack-sm">
            {pointer.kind === 'text_span' ? (
              <>
                <blockquote data-testid="proof-quote">{pointer.quote}</blockquote>
                <p className="mono small muted" style={{ margin: 0 }}>
                  {pointer.source_id} · page {pointer.page ?? 'n/a'} · line {pointer.line ?? 'n/a'} · chars {pointer.char_start}–{pointer.char_end}
                </p>
                {data.page_png ? (
                  <RegionViewer src={data.page_png} alt="Rendered page" rectsPt={pointer.line_rects_pt ?? []} />
                ) : (
                  <p data-testid="render-missing" className="callout callout-warn">
                    The page image was not rendered for this version. The quoted text above is the stored evidence.
                  </p>
                )}
              </>
            ) : null}
            {pointer.kind === 'image_region' ? (
              <>
                <p className="mono small muted" style={{ margin: 0 }}>
                  {pointer.source_id} · read “{pointer.read_text}” {pointer.reread_text ? `· re-read “${pointer.reread_text}”` : ''}
                </p>
                {data.page_png ? <RegionViewer src={data.page_png} alt="Oriented photo" rectsPx={[pointer.bbox]} /> : null}
                {data.crop_png ? <img src={data.crop_png} alt="Cropped region" data-testid="crop-image" style={{ border: '1px solid var(--line-strong)' }} /> : null}
              </>
            ) : null}
            {pointer.kind === 'table_cell' ? (
              <>
                <p className="mono small muted" style={{ margin: 0 }}>
                  {pointer.source_id} · row {pointer.row} · column {pointer.column} · value {pointer.raw_value}
                </p>
                <TableWindow rows={data.window_rows ?? []} citedRow={pointer.row} citedColumn={pointer.column} />
              </>
            ) : null}
            {pointer.kind === 'sensor_window' ? (
              <>
                <p className="mono small muted" style={{ margin: 0 }}>
                  {pointer.series_id} · {pointer.n_points} of {pointer.expected_points} readings · {pointer.statistic}/{pointer.granularity}
                </p>
                <SensorChart rows={data.window_rows ?? []} channels={pointer.channels} envelope={envelope.data ?? null} tStar={thresholdOf(claim)} tz={tz} />
              </>
            ) : null}
            <RecheckBadge caseId={caseId} claimId={claim.claim_id} />
          </div>
        ) : null}
      </div>
    </section>
  );
}

function thresholdOf(claim: Claim): number | null {
  const v = claim.value;
  if (typeof v === 'object' && v !== null && !Array.isArray(v)) {
    const t = (v as Record<string, unknown>)['T_star'];
    if (typeof t === 'number') return t;
  }
  return null;
}
