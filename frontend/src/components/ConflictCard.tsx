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

/** Red card: both sides side by side, the six checks, the computed numbers, the version. */
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
  const red = comparison.outcome === 'disagree';
  return (
    <article
      data-testid="conflict-card"
      aria-label="Conflict"
      className={`rounded-lg border-2 p-4 ${red ? 'border-red-700 bg-red-50' : 'border-slate-500 bg-slate-50'}`}
    >
      <header className="mb-3 flex flex-wrap items-center gap-3">
        <OutcomeBadge outcome={comparison.outcome} />
        <VersionBadge version={state.version} manifestHash={state.manifest_hash} />
        <span className="rounded bg-slate-200 px-1 text-xs font-semibold">
          {conflict.averaged ? 'averaged' : 'not averaged: both sides kept'}
        </span>
      </header>
      <p className="mb-3" data-testid="reason">
        {comparison.reason}
      </p>
      <div className="mb-4 grid gap-3 md:grid-cols-2">
        {textSide ? <TextClaimPanel claim={textSide} synthetic={synthetic} tz={state.plant_tz} /> : null}
        {sensorSide ? (
          <SensorClaimPanel
            claim={sensorSide}
            child={child}
            threshold={conflict.magnitude.threshold}
            tz={state.plant_tz}
          />
        ) : null}
      </div>
      <p className="mb-3 text-sm" data-testid="magnitude">
        {conflict.magnitude.statistic}: observed {fmt(conflict.magnitude.observed)} against threshold{' '}
        {fmt(conflict.magnitude.threshold)} ({conflict.magnitude.unit})
      </p>
      <GateTable checks={comparison.checks} />
      <div className="mt-3 flex flex-wrap items-center gap-2" data-testid="conflict-actions">
        {sides.map((side) => (
          <button
            key={side.claim_id}
            type="button"
            data-testid="show-proof"
            data-modality={side.modality}
            className="rounded border border-slate-700 bg-white px-2 py-1 text-sm font-semibold"
            onClick={() => onProof(side.claim_id)}
          >
            Show me the proof: {side.label ?? side.claim_id}
          </button>
        ))}
        {reviewOpen > 0 ? (
          <>
            <a className="rounded bg-slate-800 px-2 py-1 text-sm font-semibold text-white" href={`/review/?id=${encodeURIComponent(caseId)}`} data-testid="resolve">
              Resolve
            </a>
            <a className="rounded border border-slate-700 px-2 py-1 text-sm font-semibold" href={`/review/?id=${encodeURIComponent(caseId)}`} data-testid="escalate">
              Escalate
            </a>
          </>
        ) : (
          <span className="text-xs text-slate-700" data-testid="no-review-item">
            No review item is open for this case, so there is nothing to resolve or escalate here.
          </span>
        )}
      </div>
      {child ? (
        <p className="mt-3 text-sm" data-testid="supporting">
          Supporting context ({child.label ?? child.claim_id}): {child.statement}
        </p>
      ) : null}
    </article>
  );
}
