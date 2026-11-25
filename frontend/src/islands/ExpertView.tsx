import { useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import EnvelopeView from '../components/EnvelopeView';
import IntegrityBadge from '../components/IntegrityBadge';
import Nav from '../components/Nav';
import OutcomeBadge from '../components/OutcomeBadge';
import ReplayButton from '../components/ReplayButton';
import VersionBadge from '../components/VersionBadge';
import { api, unwrap } from '../lib/api/client';
import { fmt } from '../lib/format';
import { keys } from '../lib/query/keys';
import { firstError, useCaseVersion, useLatest } from '../lib/query/hooks';
import Providers, { caseIdFromLocation, ErrorNote, Loading } from './Providers';

type Modality = 'all' | 'text' | 'table' | 'image' | 'sensor';
type Kind = 'all' | 'extracted' | 'inferred';
type Outcome = 'all' | 'agree' | 'disagree' | 'cant_compare' | 'cant_tell';

function Expert({ caseId }: { caseId: string }) {
  const latest = useLatest(caseId);
  const q = useCaseVersion(caseId, latest.data);
  const version = latest.data;
  const entity = q.state.data?.scope_entities[0];
  const manifest = useQuery({
    queryKey: keys.manifest(caseId, version ?? 0),
    enabled: version !== undefined,
    queryFn: async () =>
      unwrap(await api.GET('/api/v1/cases/{cid}/versions/{v}/manifest', { params: { path: { cid: caseId, v: version ?? 0 } } })),
  });
  const envelope = useQuery({
    queryKey: keys.envelope(caseId, version ?? 0, entity ?? ''),
    enabled: version !== undefined && entity !== undefined,
    queryFn: async () =>
      unwrap(
        await api.GET('/api/v1/cases/{cid}/versions/{v}/entities/{eid}/envelope', {
          params: { path: { cid: caseId, v: version ?? 0, eid: entity ?? '' } },
        }),
      ),
  });
  const [modality, setModality] = useState<Modality>('all');
  const [kind, setKind] = useState<Kind>('all');
  const [outcome, setOutcome] = useState<Outcome>('all');
  const failure = firstError([latest, q.state, q.claims, q.comparisons, manifest]);
  if (failure) return <ErrorNote error={failure} />;
  if (version === undefined || !q.state.data || !q.claims.data || !q.comparisons.data || !manifest.data) return <Loading what="expert view" />;
  const state = q.state.data;
  const claims = q.claims.data.items.filter(
    (c) => (modality === 'all' || c.modality === modality) && (kind === 'all' || c.claim_type === kind),
  );
  const comparisons = q.comparisons.data.items.filter((c) => outcome === 'all' || c.outcome === outcome);
  const label = new Map(q.claims.data.items.map((c) => [c.claim_id, c.label ?? c.claim_id]));
  const v = manifest.data.version;
  return (
    <>
      <div className="page-head">
        <div>
          <p className="crumbs">
            <a href="/">Cases</a> / <a href={`/case/?id=${encodeURIComponent(caseId)}`}>{caseId}</a> / Expert view
          </p>
          <h1>Expert view</h1>
          <p className="sub">The full record behind this version: every claim, every comparison, the hashes that pin them.</p>
        </div>
        <div className="meta">
          <VersionBadge version={state.version} manifestHash={state.manifest_hash} />
          <IntegrityBadge caseId={caseId} version={state.version} />
          <ReplayButton caseId={caseId} version={state.version} />
        </div>
      </div>
      <div className="stack">
        <section aria-label="Version" className="card card-pad" data-testid="version-info">
          <p className="eyebrow">Version fingerprint</p>
          <dl className="kv kv-wide">
            <dt>Config</dt>
            <dd data-testid="config-hash">{v.config_hash.slice(0, 16)}</dd>
            <dt>Engine</dt>
            <dd>{v.engine_sha.slice(0, 12)}</dd>
            <dt>Canon</dt>
            <dd>{v.canon_version}</dd>
            <dt>LLM</dt>
            <dd>{v.llm_mode}</dd>
          </dl>
          <p className="small muted" style={{ margin: '12px 0 0', overflowWrap: 'anywhere' }}>
            manifest <span className="mono">{manifest.data.manifest_hash}</span>
          </p>
        </section>
        {envelope.data ? <EnvelopeView envelope={envelope.data} /> : null}
        <section aria-label="Claims" className="card">
          <div className="card-head">
            <h2>Claims ({claims.length})</h2>
            <div className="aside filters">
              <label>
                Modality
                <select className="input inline" data-testid="filter-modality" value={modality} onChange={(e) => setModality(e.target.value as Modality)}>
                  {(['all', 'text', 'table', 'image', 'sensor'] as const).map((m) => (
                    <option key={m}>{m}</option>
                  ))}
                </select>
              </label>
              <label>
                Type
                <select className="input inline" data-testid="filter-kind" value={kind} onChange={(e) => setKind(e.target.value as Kind)}>
                  {(['all', 'extracted', 'inferred'] as const).map((m) => (
                    <option key={m}>{m}</option>
                  ))}
                </select>
              </label>
            </div>
          </div>
          <div className="table-wrap" style={{ maxHeight: 440, border: 0, borderRadius: 0 }}>
            <table className="t" data-testid="claims-table">
              <thead>
                <tr>
                  <th>Label</th>
                  <th>Type</th>
                  <th>Modality</th>
                  <th>Attribute</th>
                  <th>Statement</th>
                  <th>Confidence</th>
                  <th>Components</th>
                </tr>
              </thead>
              <tbody>
                {claims.map((c) => (
                  <tr key={c.claim_id} data-testid="claim-row">
                    <td className="m">{c.label ?? c.claim_id.slice(0, 12)}</td>
                    <td>{c.claim_type}</td>
                    <td>{c.modality}</td>
                    <td>{c.attribute}</td>
                    <td>{c.statement}</td>
                    <td className="m">
                      {fmt(c.confidence.value)}{' '}
                      <span className={`badge ${c.confidence.calibrated ? 'badge-ok' : 'badge-warn'}`}>{c.confidence.calibrated ? 'calibrated' : 'uncalibrated'}</span>
                    </td>
                    <td className="m muted">
                      {Object.entries(c.confidence.components ?? {})
                        .map(([k, x]) => `${k} ${fmt(x)}`)
                        .join(' · ')}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
        <section aria-label="Comparisons" className="card">
          <div className="card-head">
            <h2>Comparisons ({comparisons.length})</h2>
            <div className="aside filters">
              <label>
                Outcome
                <select className="input inline" data-testid="filter-outcome" value={outcome} onChange={(e) => setOutcome(e.target.value as Outcome)}>
                  {(['all', 'agree', 'disagree', 'cant_compare', 'cant_tell'] as const).map((m) => (
                    <option key={m}>{m}</option>
                  ))}
                </select>
              </label>
            </div>
          </div>
          <ul className="rowlist" data-testid="comparisons">
            {comparisons.map((c) => (
              <li key={c.comparison_id} className="card-body stack-sm" data-testid="comparison-row" data-outcome={c.outcome}>
                <div className="actions">
                  <OutcomeBadge outcome={c.outcome} small />
                  <span className="mono small muted">
                    {label.get(c.claim_a)} vs {label.get(c.claim_b)}
                  </span>
                </div>
                <p style={{ margin: 0 }}>{c.reason}</p>
                <ol className="small muted" style={{ margin: 0, paddingLeft: 20 }}>
                  {c.checks.map((k) => (
                    <li key={k.n}>
                      {k.name}: {k.pass ? 'passed' : 'failed'} · {k.detail}
                    </li>
                  ))}
                </ol>
              </li>
            ))}
          </ul>
        </section>
      </div>
    </>
  );
}

export default function ExpertView() {
  const caseId = caseIdFromLocation();
  return (
    <Providers>
      <Nav caseId={caseId} />
      {caseId ? <Expert caseId={caseId} /> : <p role="alert" className="callout">Open a case with ?id=&lt;case id&gt;.</p>}
    </Providers>
  );
}
