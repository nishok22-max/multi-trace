import type { Schemas } from '../lib/api/client';
import { fmt } from '../lib/format';
import { SensorClaimPanel, TextClaimPanel } from './ClaimPanels';
import GateTable from './GateTable';
import OutcomeBadge from './OutcomeBadge';
import VersionBadge from './VersionBadge';

type Claim = Schemas['ClaimRecord'];

export interface ConflictCardProps {
  conflict: Schemas['ConflictRecord'];
  comparison: Schemas['ComparisonRecord'];
  claims: Claim[];
  state: Schemas['CaseState'];
  caseId: string;
  /** Open review items in this version: Resolve and Escalate act on them in the review queue. */
  reviewOpen: number;
  onProof: (claimId: string) => void;
}

/** The verdict: the outcome, the reason, both sides side by side, the six checks, the computed numbers. */
export default function ConflictCard({ conflict, comparison, claims, state, caseId, reviewOpen, onProof }: ConflictCardProps) {
  const byId = new Map(claims.map((c) => [c.claim_id, c]));
  const sides = conflict.sides.map((id) => byId.get(id)).filter((c): c is Claim => c !== undefined);
  const textSide = sides.find((c) => c.modality === 'text');
  const sensorSide = sides.find((c) => c.modality === 'sensor');
  const context = (conflict.supporting_context ?? [])
    .map((id) => byId.get(id))
    .filter((c): c is Claim => c !== undefined);
  const child = context.find((c) => c.modality === 'sensor');
  const synthetic = textSide?.evidence
    ? state.sources.some((s) => s.source_id === (textSide.evidence as { source_id?: string }).source_id && s.synthetic)
    : false;
  const review = `/review/?id=${encodeURIComponent(caseId)}`;
  return (
    <article data-testid="conflict-card" aria-label="Conflict" className="verdict" data-outcome={comparison.outcome}>
      <header className="verdict-top">
        <OutcomeBadge outcome={comparison.outcome} />
        <span className="badge">{conflict.averaged ? 'averaged' : 'Not averaged: both sides kept'}</span>
        <span style={{ marginLeft: 'auto' }}>
          <VersionBadge version={state.version} manifestHash={state.manifest_hash} />
        </span>
      </header>
      <p className="verdict-reason" data-testid="reason">
        {comparison.reason}
      </p>
      <div className="verdict-body">
        <div className="two">
          {textSide ? <TextClaimPanel claim={textSide} synthetic={synthetic} tz={state.plant_tz} /> : null}
          {sensorSide ? (
            <SensorClaimPanel claim={sensorSide} child={child} threshold={conflict.magnitude.threshold} tz={state.plant_tz} />
          ) : null}
        </div>
        <p className="magnitude" data-testid="magnitude">
          {conflict.magnitude.statistic}: observed <strong className="num">{fmt(conflict.magnitude.observed)}</strong> against threshold{' '}
          <strong className="num">{fmt(conflict.magnitude.threshold)}</strong> ({conflict.magnitude.unit})
        </p>
        {child ? (
          <p className="small muted" data-testid="supporting" style={{ margin: 0 }}>
            Supporting context ({child.label ?? child.claim_id}): {child.statement}
          </p>
        ) : null}
        <div>
          <p className="eyebrow">Comparability gate · 6 checks</p>
          <GateTable checks={comparison.checks} />
        </div>
        <div className="actions" data-testid="conflict-actions">
          {sides.map((side) => (
            <button key={side.claim_id} type="button" data-testid="show-proof" data-modality={side.modality} className="btn" onClick={() => onProof(side.claim_id)}>
              Show me the proof: {side.label ?? side.claim_id}
            </button>
          ))}
          {reviewOpen > 0 ? (
            <>
              <a className="btn btn-primary" href={review} data-testid="resolve">
                Resolve
              </a>
              <a className="btn" href={review} data-testid="escalate">
                Escalate
              </a>
            </>
          ) : (
            <span className="small muted" data-testid="no-review-item">
              No review item is open for this case, so there is nothing to resolve or escalate here.
            </span>
          )}
        </div>
      </div>
    </article>
  );
}
