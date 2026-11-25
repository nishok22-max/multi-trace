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
    <div className="actions" data-testid="replay">
      <button type="button" data-testid="replay-button" className="btn btn-sm" disabled={mutation.isPending} onClick={() => mutation.mutate()}>
        {mutation.isPending ? 'Replaying...' : 'Verify replay'}
      </button>
      {r ? (
        r.match ? (
          <span data-testid="replay-result" data-match="true" className="badge badge-ok">
            <span className="dot" /> Replay matches: {r.actual_manifest_hash.slice(0, 12)}
          </span>
        ) : (
          <span data-testid="replay-result" data-match="false" role="alert" className="badge badge-bad">
            Replay differs: expected {r.expected_manifest_hash.slice(0, 12)}, rebuilt {r.actual_manifest_hash.slice(0, 12)}
          </span>
        )
      ) : null}
      {mutation.error ? (
        <span role="alert" className="field-error">
          {mutation.error.message}
        </span>
      ) : null}
    </div>
  );
}
