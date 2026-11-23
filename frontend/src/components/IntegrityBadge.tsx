import { useQuery } from '@tanstack/react-query';
import { api, unwrap } from '../lib/api/client';
import { keys } from '../lib/query/keys';

/** Green or red from re-walking the chain and the stored bytes. Always a text label. */
export default function IntegrityBadge({ caseId, version }: { caseId: string; version: number }) {
  const integrity = useQuery({
    queryKey: keys.integrity(caseId, version),
    staleTime: 0,
    queryFn: async () =>
      unwrap(
        await api.GET('/api/v1/cases/{cid}/versions/{v}/integrity', { params: { path: { cid: caseId, v: version } } }),
      ),
  });
  if (integrity.isLoading) return <span data-testid="integrity-badge">Checking integrity...</span>;
  if (integrity.error || !integrity.data) {
    return (
      <span data-testid="integrity-badge" data-ok="unknown" className="rounded border border-slate-600 bg-slate-100 px-2 py-0.5 text-xs font-semibold">
        Integrity unknown
      </span>
    );
  }
  const r = integrity.data;
  return r.ok ? (
    <span data-testid="integrity-badge" data-ok="true" className="rounded border border-green-700 bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-900">
      Integrity verified · chain, snapshot, records
    </span>
  ) : (
    <span data-testid="integrity-badge" data-ok="false" role="alert" className="rounded border border-red-800 bg-red-600 px-2 py-0.5 text-xs font-bold text-white" title={(r.failures ?? []).join('; ')}>
      Integrity check FAILED{!r.chain_ok ? ' · chain' : ''}{!r.snapshot_ok ? ' · snapshot' : ''}{!r.records_ok ? ' · records' : ''}
    </span>
  );
}
