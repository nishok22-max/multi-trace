import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import ConflictCard from '../components/ConflictCard';
import IntegrityBadge from '../components/IntegrityBadge';
import Nav from '../components/Nav';
import ProofPanel from '../components/ProofPanel';
import StorySteps from '../components/StorySteps';
import Timeline from '../components/Timeline';
import VersionBadge from '../components/VersionBadge';
import type { Schemas } from '../lib/api/client';
import { localDateTime } from '../lib/format';
import { keys } from '../lib/query/keys';
import { firstError, useCaseVersion, useLatest } from '../lib/query/hooks';
import Providers, { caseIdFromLocation, ErrorNote, Loading } from './Providers';

function Workspace({ caseId }: { caseId: string }) {
  const client = useQueryClient();
  const latest = useLatest(caseId);
  const version = latest.data;
  const q = useCaseVersion(caseId, version);
  const [proof, setProof] = useState<string | null>(null);

  const failure = firstError([latest, q.state, q.story, q.conflicts, q.comparisons, q.claims, q.timeline, q.review]);
  if (failure) return <ErrorNote error={failure} />;
  if (version === undefined || !q.state.data || !q.story.data || !q.conflicts.data || !q.comparisons.data || !q.claims.data || !q.timeline.data || !q.review.data) {
    return <Loading what="case" />;
  }
  const state = q.state.data;
  const claims = q.claims.data.items;
  const proofClaim = proof ? claims.find((c) => c.claim_id === proof) : undefined;
  const open = q.review.data.filter((e) => e.status === 'open' || e.status === 'escalated');
  const reviewHref = `/review/?id=${encodeURIComponent(caseId)}`;
  return (
    <>
      <div className="page-head">
        <div>
          <p className="crumbs">
            <a href="/">Cases</a> / {state.case_id}
          </p>
          <h1>{state.case_id}</h1>
          <p className="sub">
            {state.scope_entities.join(', ')} · {localDateTime(state.window_start, state.plant_tz)} to {localDateTime(state.window_end, state.plant_tz)} (plant-local)
          </p>
        </div>
        <div className="meta">
          <VersionBadge version={state.version} manifestHash={state.manifest_hash} />
          <IntegrityBadge caseId={caseId} version={state.version} />
          <button type="button" className="btn btn-sm" onClick={() => void client.invalidateQueries({ queryKey: keys.latest(caseId) })} data-testid="refresh">
            Check for a newer version
          </button>
        </div>
      </div>
      <div className="cols">
        <div className="stack">
          {q.conflicts.data.items.length === 0 ? (
            <p data-testid="no-conflict" className="callout callout-ok">
              No conflict in this version.
            </p>
          ) : (
            q.conflicts.data.items.map((conflict) => {
              const comparison = (q.comparisons.data?.items ?? []).find((c) => conflict.comparison_ids.includes(c.comparison_id));
              return comparison ? (
                <ConflictCard key={conflict.conflict_id} conflict={conflict} comparison={comparison} claims={claims} state={state} reviewOpen={open.length} onProof={setProof} caseId={caseId} />
              ) : null;
            })
          )}
          {proofClaim ? (
            <ProofPanel caseId={caseId} version={state.version} manifestHash={state.manifest_hash} claim={proofClaim} tz={state.plant_tz} onClose={() => setProof(null)} />
          ) : null}
          <StorySteps story={q.story.data} />
          <Timeline entries={q.timeline.data} claims={claims} tz={state.plant_tz} onOpen={setProof} />
        </div>
        <aside className="rail" aria-label="Case summary">
          <section className="card card-pad" data-testid="your-move">
            <p className="eyebrow">Your move</p>
            {open.length === 0 ? (
              <p className="small" style={{ margin: 0 }}>
                No open review items in this version.
              </p>
            ) : (
              <>
                <p style={{ margin: '0 0 12px' }}>
                  <strong>{open.length}</strong> item(s) wait for a decision.
                </p>
                <a className="btn btn-primary" href={reviewHref} data-testid="open-review">
                  Open the review queue
                </a>
              </>
            )}
          </section>
          <SourceList sources={state.sources} />
          <section className="card card-pad small">
            <p className="eyebrow">Open the evidence</p>
            <p style={{ margin: '0 0 10px' }} className="muted">
              Every claim, comparison, hash and the learned envelope.
            </p>
            <a href={`/case/expert/?id=${encodeURIComponent(caseId)}`}>Expert view →</a>
          </section>
        </aside>
      </div>
    </>
  );
}

function SourceList({ sources }: { sources: Schemas['Source'][] }) {
  const shown = sources.filter((s) => s.held_reason === null || s.held_reason === undefined);
  return (
    <section className="card card-pad">
      <p className="eyebrow">Sources ({shown.length})</p>
      <ul className="stack-sm" style={{ listStyle: 'none', margin: 0, padding: 0 }} data-testid="sources">
        {shown.map((s) => (
          <li key={s.source_id} className="small" style={{ display: 'flex', flexWrap: 'wrap', gap: '4px 8px', alignItems: 'center' }}>
            <span style={{ fontWeight: 600 }}>{s.modality}</span>
            <span className="mono muted" style={{ overflowWrap: 'anywhere' }}>{s.source_id}</span>
            <span className="chips">
              {s.synthetic ? <span className="badge badge-warn">synthetic</span> : null}
              {s.origin.includes('planted') ? <span className="badge badge-note">planted</span> : null}
            </span>
          </li>
        ))}
      </ul>
    </section>
  );
}

export default function CaseWorkspace() {
  const caseId = caseIdFromLocation();
  return (
    <Providers>
      <Nav caseId={caseId} />
      {caseId ? <Workspace caseId={caseId} /> : <p role="alert" className="callout">Open a case with ?id=&lt;case id&gt;.</p>}
    </Providers>
  );
}
