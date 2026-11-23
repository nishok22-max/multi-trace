import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';
import CandidateList from '../components/CandidateList';
import DecisionPanel from '../components/DecisionPanel';
import Nav from '../components/Nav';
import ProofPanel from '../components/ProofPanel';
import VersionBadge from '../components/VersionBadge';
import type { Schemas } from '../lib/api/client';
import { keys } from '../lib/query/keys';
import { firstError, useCaseVersion, useLatest } from '../lib/query/hooks';
import Providers, { caseIdFromLocation, ErrorNote } from './Providers';

const TITLE: Record<Schemas['ReviewItem']['type'], string> = {
  ambiguous_entity: 'Which machine is this?',
  reader_disagreement: 'Two readers disagree',
  implausible_value: 'Implausible reading',
  hidden_text: 'Hidden text in a document',
  envelope_drift: 'Envelope moved between versions',
  low_confidence: 'Low confidence',
  unknown_unit: 'Unknown unit',
  llm_only_interpretation: 'Interpretation without a rule',
  no_text_layer: 'Scanned page without text',
  unsupported_page: 'Unsupported page',
  pdf_page_cap: 'Document over the page cap',
  conflict_explain: 'Explain a conflict',
};

function Queue({ caseId }: { caseId: string }) {
  const client = useQueryClient();
  const latest = useLatest(caseId);
  const q = useCaseVersion(caseId, latest.data);
  const [selected, setSelected] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const failure = firstError([latest, q.state, q.review, q.claims]);
  if (failure) return <ErrorNote error={failure} />;
  if (latest.data === undefined || !q.state.data || !q.review.data || !q.claims.data) return <p>Loading review queue...</p>;
  const state = q.state.data;
  const entries = q.review.data;
  const entry =
    entries.find((e) => e.item.review_id === selected) ??
    entries.find((e) => e.status === 'open' || e.status === 'escalated') ??
    entries[0];
  const claimsById = new Map(q.claims.data.items.map((c) => [c.claim_id, c]));
  const related = entry ? entry.item.claim_ids.map((id) => claimsById.get(id)).filter((c): c is Schemas['ClaimRecord'] => c !== undefined) : [];
  return (
    <div>
      <Nav caseId={caseId} />
      <header className="mb-3 flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold">Review queue</h1>
        <VersionBadge version={state.version} manifestHash={state.manifest_hash} />
      </header>
      {notice ? (
        <p role="status" data-testid="decided-notice" className="mb-3 rounded border border-green-700 bg-green-50 p-2">
          {notice}
        </p>
      ) : null}
      {entries.length === 0 ? <p data-testid="queue-empty">Nothing to review in this version.</p> : null}
      <div className="grid gap-4 md:grid-cols-[18rem_1fr]">
        <ul className="space-y-2" data-testid="queue">
          {entries.map((e) => (
            <li key={e.item.review_id}>
              <button
                type="button"
                data-testid="queue-item"
                data-status={e.status}
                aria-current={entry?.item.review_id === e.item.review_id ? 'true' : undefined}
                className={`w-full rounded border p-2 text-left ${entry?.item.review_id === e.item.review_id ? 'border-slate-900 bg-slate-100' : 'border-slate-400 bg-white'}`}
                onClick={() => setSelected(e.item.review_id)}
              >
                <span className="block font-semibold">{TITLE[e.item.type]}</span>
                <span className="block text-xs">
                  {e.status === 'escalated' ? 'Escalated: waiting more than a working day' : e.status === 'decided' ? 'Decided' : e.status === 'stale' ? 'Stale' : 'Open'}
                  {e.explained ? ' · explained' : ''}
                </span>
                <span className="block font-mono text-xs text-slate-600">{e.item.mention_keys[0]?.locator}</span>
              </button>
            </li>
          ))}
        </ul>
        {entry ? (
          <div className="space-y-3" data-testid="review-detail">
            <h2 className="text-lg font-bold">{TITLE[entry.item.type]}</h2>
            {entry.item.candidates && entry.item.candidates.length > 0 ? <CandidateList candidates={entry.item.candidates} /> : null}
            {related.map((c) => (
              <ProofPanel key={c.claim_id} caseId={caseId} version={state.version} manifestHash={state.manifest_hash} claim={c} tz={state.plant_tz} />
            ))}
            {entry.status === 'decided' ? (
              <p data-testid="already-decided" className="rounded border border-slate-500 bg-slate-100 p-2">
                This item is decided. Only a senior reviewer can supersede a decision.
              </p>
            ) : (
              <DecisionPanel
                caseId={caseId}
                baseVersion={state.version}
                item={entry.item}
                onDecided={(res) => {
                  setNotice(`Decision saved. Version ${res.version} is ready (manifest ${res.manifest_hash.slice(0, 12)}).`);
                  void client.invalidateQueries({ queryKey: keys.latest(caseId) });
                }}
              />
            )}
          </div>
        ) : null}
      </div>
    </div>
  );
}

function Picker() {
  return (
    <div>
      <Nav />
      <p data-testid="pick-case">
        Open a case first: <a className="underline" href="/">choose a case</a>, then its review queue.
      </p>
    </div>
  );
}

export default function ReviewQueue() {
  const caseId = caseIdFromLocation();
  return <Providers>{caseId ? <Queue caseId={caseId} /> : <Picker />}</Providers>;
}
