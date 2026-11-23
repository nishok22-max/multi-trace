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
import Providers, { caseIdFromLocation, ErrorNote } from './Providers';

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
  if (version === undefined || !q.state.data || !q.claims.data || !q.comparisons.data || !manifest.data) return <p>Loading expert view...</p>;
  const state = q.state.data;
  const claims = q.claims.data.items.filter(
    (c) => (modality === 'all' || c.modality === modality) && (kind === 'all' || c.claim_type === kind),
  );
  const comparisons = q.comparisons.data.items.filter((c) => outcome === 'all' || c.outcome === outcome);
  const label = new Map(q.claims.data.items.map((c) => [c.claim_id, c.label ?? c.claim_id]));
  const v = manifest.data.version;
  return (
    <div>
      <Nav caseId={caseId} />
      <header className="mb-3 flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold">Expert view · {state.case_id}</h1>
        <VersionBadge version={state.version} manifestHash={state.manifest_hash} />
        <IntegrityBadge caseId={caseId} version={state.version} />
        <ReplayButton caseId={caseId} version={state.version} />
      </header>
      <section aria-label="Version" className="mb-4 rounded border border-slate-400 bg-white p-3 text-sm" data-testid="version-info">
        <p>
          Config <span className="font-mono" data-testid="config-hash">{v.config_hash.slice(0, 16)}</span> · engine{' '}
          <span className="font-mono">{v.engine_sha.slice(0, 12)}</span> · canon <span className="font-mono">{v.canon_version}</span> · LLM{' '}
          <span className="font-mono">{v.llm_mode}</span> · manifest <span className="font-mono">{manifest.data.manifest_hash}</span>
        </p>
      </section>
      {envelope.data ? (
        <div className="mb-4">
          <EnvelopeView envelope={envelope.data} />
        </div>
      ) : null}
      <section aria-label="Claims" className="mb-6">
        <h2 className="mb-2 text-lg font-bold">Claims ({claims.length})</h2>
        <div className="mb-2 flex flex-wrap gap-3 text-sm">
          <label>
            Modality{' '}
            <select data-testid="filter-modality" value={modality} onChange={(e) => setModality(e.target.value as Modality)}>
              {(['all', 'text', 'table', 'image', 'sensor'] as const).map((m) => (
                <option key={m}>{m}</option>
              ))}
            </select>
          </label>
          <label>
            Type{' '}
            <select data-testid="filter-kind" value={kind} onChange={(e) => setKind(e.target.value as Kind)}>
              {(['all', 'extracted', 'inferred'] as const).map((m) => (
                <option key={m}>{m}</option>
              ))}
            </select>
          </label>
        </div>
        <div className="max-h-96 overflow-auto border border-slate-400">
          <table className="w-full border-collapse text-left text-xs" data-testid="claims-table">
            <thead className="sticky top-0 bg-slate-100">
              <tr>
                <th className="px-2 py-1">Label</th>
                <th className="px-2 py-1">Type</th>
                <th className="px-2 py-1">Modality</th>
                <th className="px-2 py-1">Attribute</th>
                <th className="px-2 py-1">Statement</th>
                <th className="px-2 py-1">Confidence</th>
                <th className="px-2 py-1">Components</th>
              </tr>
            </thead>
            <tbody>
              {claims.map((c) => (
                <tr key={c.claim_id} className="border-b border-slate-200 align-top" data-testid="claim-row">
                  <td className="px-2 py-0.5 font-mono">{c.label ?? c.claim_id.slice(0, 12)}</td>
                  <td className="px-2 py-0.5">{c.claim_type}</td>
                  <td className="px-2 py-0.5">{c.modality}</td>
                  <td className="px-2 py-0.5">{c.attribute}</td>
                  <td className="px-2 py-0.5">{c.statement}</td>
                  <td className="px-2 py-0.5 font-mono">
                    {fmt(c.confidence.value)} <span className="rounded bg-slate-200 px-1 font-sans">{c.confidence.calibrated ? 'calibrated' : 'uncalibrated'}</span>
                  </td>
                  <td className="px-2 py-0.5 font-mono">
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
      <section aria-label="Comparisons">
        <h2 className="mb-2 text-lg font-bold">Comparisons ({comparisons.length})</h2>
        <label className="mb-2 block text-sm">
          Outcome{' '}
          <select data-testid="filter-outcome" value={outcome} onChange={(e) => setOutcome(e.target.value as Outcome)}>
            {(['all', 'agree', 'disagree', 'cant_compare', 'cant_tell'] as const).map((m) => (
              <option key={m}>{m}</option>
            ))}
          </select>
        </label>
        <ul className="space-y-3" data-testid="comparisons">
          {comparisons.map((c) => (
            <li key={c.comparison_id} className="rounded border border-slate-400 bg-white p-3" data-testid="comparison-row" data-outcome={c.outcome}>
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <OutcomeBadge outcome={c.outcome} />
                <span className="font-mono text-xs">
                  {label.get(c.claim_a)} vs {label.get(c.claim_b)}
                </span>
              </div>
              <p className="text-sm">{c.reason}</p>
              <ol className="mt-1 list-decimal pl-5 text-xs">
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
  );
}

export default function ExpertView() {
  const caseId = caseIdFromLocation();
  return <Providers>{caseId ? <Expert caseId={caseId} /> : <p role="alert">Open a case with ?id=&lt;case id&gt;.</p>}</Providers>;
}
