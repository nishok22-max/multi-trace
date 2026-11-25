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
  if (integrity.isLoading) {
    return (
      <span data-testid="integrity-badge" className="badge">
        Checking integrity...
      </span>
    );
  }
  if (integrity.error || !integrity.data) {
    return (
      <span data-testid="integrity-badge" data-ok="unknown" className="badge badge-warn">
        Integrity unknown
      </span>
    );
  }
  const { result: r, anchored } = integrity.data;
  return (
    <>
      {r.ok ? (
        <span data-testid="integrity-badge" data-ok="true" className="badge badge-ok" title="Hash chain, stored snapshot and every record were re-checked just now.">
          <span className="dot" /> Integrity verified · chain, snapshot, records
        </span>
      ) : (
        <span data-testid="integrity-badge" data-ok="false" role="alert" className="badge badge-bad" title={(r.failures ?? []).join('; ')}>
          Integrity check FAILED{!r.chain_ok ? ' · chain' : ''}
          {!r.snapshot_ok ? ' · snapshot' : ''}
          {!r.records_ok ? ' · records' : ''}
        </span>
      )}
      <span
        data-testid="anchor-badge"
        data-anchored={anchored ? 'true' : 'false'}
        className={`badge ${anchored ? 'badge-info' : ''}`}
        title="Whether this version's root is listed in anchors/demo_roots.txt. Pushing that file to the remote is what protects it."
      >
        {anchored ? 'Root listed in the anchor file' : 'Root not anchored'}
      </span>
    </>
  );
}
