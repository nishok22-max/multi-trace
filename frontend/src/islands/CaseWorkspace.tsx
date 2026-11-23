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
import { keys } from '../lib/query/keys';
import { firstError, useCaseVersion, useLatest } from '../lib/query/hooks';
import Providers, { caseIdFromLocation, ErrorNote } from './Providers';

function Workspace({ caseId }: { caseId: string }) {
  const client = useQueryClient();
  const latest = useLatest(caseId);
  const version = latest.data;
  const q = useCaseVersion(caseId, version);
  const [proof, setProof] = useState<string | null>(null);

  const failure = firstError([latest, q.state, q.story, q.conflicts, q.comparisons, q.claims, q.timeline, q.review]);
  if (failure) return <ErrorNote error={failure} />;
  if (version === undefined || !q.state.data || !q.story.data || !q.conflicts.data || !q.comparisons.data || !q.claims.data || !q.timeline.data || !q.review.data) {
    return <p>Loading case...</p>;
  }
  const state = q.state.data;
  const claims = q.claims.data.items;
  const proofClaim = proof ? claims.find((c) => c.claim_id === proof) : undefined;
  const open = q.review.data.filter((e) => e.status === 'open' || e.status === 'escalated');
  const sources = state.sources;
  return (
    <div>
      <Nav caseId={caseId} />
      <header className="mb-4 flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold">{state.case_id}</h1>
        <VersionBadge version={state.version} manifestHash={state.manifest_hash} />
        <IntegrityBadge caseId={caseId} version={state.version} />
        <button
          type="button"
          className="rounded border border-slate-500 px-2 py-0.5 text-sm"
          onClick={() => void client.invalidateQueries({ queryKey: keys.latest(caseId) })}
          data-testid="refresh"
        >
          Check for a newer version
        </button>
      </header>
      <SourceLine sources={sources} />
      <StorySteps story={q.story.data} />
      {q.conflicts.data.items.length === 0 ? (
        <p data-testid="no-conflict">No conflict in this version.</p>
      ) : (
        q.conflicts.data.items.map((conflict) => {
          const comparison = (q.comparisons.data?.items ?? []).find((c) => conflict.comparison_ids.includes(c.comparison_id));
          return comparison ? (
            <ConflictCard
              key={conflict.conflict_id}
              conflict={conflict}
              comparison={comparison}
              claims={claims}
              state={state}
              reviewOpen={open.length}
              onProof={setProof}
              caseId={caseId}
            />
          ) : null;
        })
      )}
      {proofClaim ? (
        <div className="my-4">
          <ProofPanel
            caseId={caseId}
            version={state.version}
            manifestHash={state.manifest_hash}
            claim={proofClaim}
            tz={state.plant_tz}
            onClose={() => setProof(null)}
          />
        </div>
      ) : null}
      <div className="my-4 rounded border border-slate-400 bg-white p-3" data-testid="your-move">
        <h2 className="font-semibold">Your move</h2>
        {open.length === 0 ? (
          <p className="text-sm">No open review items in this version.</p>
        ) : (
          <p className="text-sm">
            {open.length} item(s) wait for a decision.{' '}
            <a className="underline" href={`/review/?id=${encodeURIComponent(caseId)}`} data-testid="open-review">
              Open the review queue
            </a>
          </p>
        )}
      </div>
      <Timeline entries={q.timeline.data} claims={claims} tz={state.plant_tz} onOpen={setProof} />
    </div>
  );
}

function SourceLine({ sources }: { sources: Schemas['Source'][] }) {
  return (
    <ul className="mb-4 flex flex-wrap gap-2 text-xs" data-testid="sources">
      {sources
        .filter((s) => s.held_reason === null || s.held_reason === undefined)
        .map((s) => (
          <li key={s.source_id} className="rounded border border-slate-400 bg-white px-2 py-0.5">
            {s.modality} · {s.source_id}
            {s.synthetic ? <span className="ml-1 rounded bg-amber-100 px-1 font-semibold text-amber-900">synthetic</span> : null}
            {s.origin.includes('planted') ? <span className="ml-1 rounded bg-purple-100 px-1 font-semibold text-purple-900">planted</span> : null}
          </li>
        ))}
    </ul>
  );
}

export default function CaseWorkspace() {
  const caseId = caseIdFromLocation();
  return (
    <Providers>
      {caseId ? <Workspace caseId={caseId} /> : <p role="alert">Open a case with ?id=&lt;case id&gt;.</p>}
    </Providers>
  );
}
