import { useQuery } from '@tanstack/react-query';
import { api, ApiError } from '../lib/api/client';
import { keys } from '../lib/query/keys';

/** Green or red from re-walking the chain and the stored bytes, plus whether this version's root is
 *  listed in the anchor file. Always text labels. "Anchored" means listed in `anchors/demo_roots.txt`;
 *  that the file was PUSHED is a separate check (the rehearsal), so the badge says exactly that. */
export default function IntegrityBadge({ caseId, version }: { caseId: string; version: number }) {
  const integrity = useQuery({
    queryKey: keys.integrity(caseId, version),
    staleTime: 0,
    queryFn: async () => {
      const res = await api.GET('/api/v1/cases/{cid}/versions/{v}/integrity', {
        params: { path: { cid: caseId, v: version } },
      });
      if (!res.response.ok || res.data === undefined) {
        throw new ApiError(res.response.status, 'Integrity could not be checked.');
      }
      return { result: res.data, anchored: res.response.headers.get('x-manifest-anchored') === 'true' };
    },
  });
  if (integrity.isLoading) return <span data-testid="integrity-badge">Checking integrity...</span>;
  if (integrity.error || !integrity.data) {
    return (
      <span data-testid="integrity-badge" data-ok="unknown" className="rounded border border-slate-600 bg-slate-100 px-2 py-0.5 text-xs font-semibold">
        Integrity unknown
      </span>
    );
  }
  const { result: r, anchored } = integrity.data;
  return (
    <span className="inline-flex flex-wrap items-center gap-2">
      {r.ok ? (
        <span data-testid="integrity-badge" data-ok="true" className="rounded border border-green-700 bg-green-100 px-2 py-0.5 text-xs font-semibold text-green-900">
          Integrity verified · chain, snapshot, records
        </span>
      ) : (
        <span data-testid="integrity-badge" data-ok="false" role="alert" className="rounded border border-red-800 bg-red-600 px-2 py-0.5 text-xs font-bold text-white" title={(r.failures ?? []).join('; ')}>
          Integrity check FAILED{!r.chain_ok ? ' · chain' : ''}{!r.snapshot_ok ? ' · snapshot' : ''}{!r.records_ok ? ' · records' : ''}
        </span>
      )}
      <span
        data-testid="anchor-badge"
        data-anchored={anchored ? 'true' : 'false'}
        className="rounded border border-slate-600 bg-slate-100 px-2 py-0.5 text-xs font-semibold"
        title="Whether this version's root is listed in anchors/demo_roots.txt. Pushing that file to the remote is what protects it."
      >
        {anchored ? 'Root listed in the anchor file' : 'Root not anchored'}
      </span>
    </span>
  );
}
