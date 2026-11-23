import { useMutation } from '@tanstack/react-query';
import { api, CSRF, unwrap } from '../lib/api/client';

/** "Verify replay": rebuilds this version from the stored artifacts and compares manifest hashes. */
export default function ReplayButton({ caseId, version }: { caseId: string; version: number }) {
  const mutation = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST('/api/v1/cases/{cid}/versions/{v}/replay', { params: { header: CSRF, path: { cid: caseId, v: version } } })),
  });
  const r = mutation.data;
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="replay">
      <button
        type="button"
        data-testid="replay-button"
        className="rounded border border-slate-600 bg-white px-2 py-1 text-sm font-semibold"
        disabled={mutation.isPending}
        onClick={() => mutation.mutate()}
      >
        {mutation.isPending ? 'Replaying...' : 'Verify replay'}
      </button>
      {r ? (
        r.match ? (
          <span data-testid="replay-result" data-match="true" className="rounded border border-green-700 bg-green-100 px-2 py-0.5 text-sm font-semibold text-green-900">
            Replay matches: {r.actual_manifest_hash.slice(0, 12)}
          </span>
        ) : (
          <span data-testid="replay-result" data-match="false" role="alert" className="rounded border border-red-800 bg-red-600 px-2 py-0.5 text-sm font-bold text-white">
            Replay differs: expected {r.expected_manifest_hash.slice(0, 12)}, rebuilt {r.actual_manifest_hash.slice(0, 12)}
          </span>
        )
      ) : null}
      {mutation.error ? (
        <span role="alert" className="text-sm text-red-800">
          {mutation.error.message}
        </span>
      ) : null}
    </div>
  );
}
