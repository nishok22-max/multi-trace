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
import Providers, { caseIdFromLocation, ErrorNote, Loading } from './Providers';

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

type Status = Schemas['ReviewQueueEntry']['status'];

function statusBadge(status: Status, explained: boolean) {
  const label = status === 'escalated' ? 'Escalated: waiting more than a working day' : status === 'decided' ? 'Decided' : status === 'stale' ? 'Stale' : 'Open';
  const tone = status === 'decided' ? 'badge-ok' : status === 'escalated' ? 'badge-warn' : status === 'stale' ? '' : 'badge-info';
  return (
    <span className={`badge ${tone}`}>
      {label}
      {explained ? ' · explained' : ''}
    </span>
  );
}

function Queue({ caseId }: { caseId: string }) {
  const client = useQueryClient();
  const latest = useLatest(caseId);
  const q = useCaseVersion(caseId, latest.data);
  const [selected, setSelected] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const failure = firstError([latest, q.state, q.review, q.claims]);
  if (failure) return <ErrorNote error={failure} />;
  if (latest.data === undefined || !q.state.data || !q.review.data || !q.claims.data) return <Loading what="review queue" />;
  const state = q.state.data;
  const entries = q.review.data;
  const entry =
    entries.find((e) => e.item.review_id === selected) ??
    entries.find((e) => e.status === 'open' || e.status === 'escalated') ??
    entries[0];
  const claimsById = new Map(q.claims.data.items.map((c) => [c.claim_id, c]));
  const related = entry ? entry.item.claim_ids.map((id) => claimsById.get(id)).filter((c): c is Schemas['ClaimRecord'] => c !== undefined) : [];
  const waiting = entries.filter((e) => e.status === 'open' || e.status === 'escalated').length;
  return (
    <>
      <div className="page-head">
        <div>
          <p className="crumbs">
            <a href="/">Cases</a> / <a href={`/case/?id=${encodeURIComponent(caseId)}`}>{caseId}</a> / Review
          </p>
          <h1>Review queue</h1>
          <p className="sub">
            {entries.length === 0 ? 'Nothing to review.' : `${waiting} of ${entries.length} waiting for a decision.`} Decisions create a new version; nothing is overwritten.
          </p>
        </div>
        <div className="meta">
          <VersionBadge version={state.version} manifestHash={state.manifest_hash} />
        </div>
      </div>
      {notice ? (
        <p role="status" data-testid="decided-notice" className="callout callout-ok" style={{ marginBottom: 20 }}>
          {notice}
        </p>
      ) : null}
      {entries.length === 0 ? (
        <p data-testid="queue-empty" className="card empty">
          Nothing to review in this version.
        </p>
      ) : (
        <div className="review-cols">
          <nav aria-label="Review items">
            <ul className="queue" data-testid="queue" style={{ listStyle: 'none', margin: 0, padding: 0 }}>
              {entries.map((e) => (
                <li key={e.item.review_id}>
                  <button
                    type="button"
                    data-testid="queue-item"
                    data-status={e.status}
                    aria-current={entry?.item.review_id === e.item.review_id ? 'true' : undefined}
                    className="q-item"
                    onClick={() => setSelected(e.item.review_id)}
                  >
                    <span className="q-title">{TITLE[e.item.type]}</span>
                    <span>{statusBadge(e.status, e.explained)}</span>
                    <span className="q-sub mono">{e.item.mention_keys[0]?.locator}</span>
                  </button>
                </li>
              ))}
            </ul>
          </nav>
          {entry ? (
            <div className="stack" data-testid="review-detail">
              <h2 style={{ margin: 0, fontSize: 20 }}>{TITLE[entry.item.type]}</h2>
              {entry.item.candidates && entry.item.candidates.length > 0 ? <CandidateList candidates={entry.item.candidates} /> : null}
              {related.map((c) => (
                <ProofPanel key={c.claim_id} caseId={caseId} version={state.version} manifestHash={state.manifest_hash} claim={c} tz={state.plant_tz} />
              ))}
              {entry.status === 'decided' ? (
                <p data-testid="already-decided" className="callout">
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
      )}
    </>
  );
}

function Picker() {
  return (
    <p data-testid="pick-case" className="card card-pad">
      Open a case first: <a href="/">choose a case</a>, then its review queue.
    </p>
  );
}

export default function ReviewQueue() {
  const caseId = caseIdFromLocation();
  return (
    <Providers>
      <Nav caseId={caseId} />
      {caseId ? <Queue caseId={caseId} /> : <Picker />}
    </Providers>
  );
}
