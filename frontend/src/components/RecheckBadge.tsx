import { useMutation } from '@tanstack/react-query';
import { api, CSRF, unwrap, type Schemas } from '../lib/api/client';

/** "Re-checked just now": re-hashes the stored bytes and re-derives the cited value on demand.
 *  A mismatch is shown as a red "Evidence changed"; nothing is repaired or hidden. */
export default function RecheckBadge({ caseId, claimId }: { caseId: string; claimId: string }) {
  const mutation = useMutation({
    mutationFn: async (): Promise<Schemas['RecheckResult']> =>
      unwrap(
        await api.POST('/api/v1/cases/{cid}/claims/{claim_id}/recheck', {
          params: { header: CSRF, path: { cid: caseId, claim_id: claimId } },
        }),
      ),
  });
  const result = mutation.data;
  return (
    <div className="flex flex-wrap items-center gap-2" data-testid="recheck">
      <button
        type="button"
        data-testid="recheck-button"
        className="rounded border border-slate-600 bg-white px-2 py-1 text-sm font-semibold"
        disabled={mutation.isPending}
        onClick={() => mutation.mutate()}
      >
        {mutation.isPending ? 'Re-checking...' : 'Re-check now'}
      </button>
      {result ? (
        result.match ? (
          <span data-testid="recheck-result" data-match="true" className="rounded border border-green-700 bg-green-100 px-2 py-0.5 text-sm font-semibold text-green-900">
            Re-checked just now: matches the stored evidence
          </span>
        ) : (
          <span data-testid="recheck-result" data-match="false" role="alert" className="rounded border border-red-800 bg-red-600 px-2 py-0.5 text-sm font-bold text-white">
            Evidence changed
            {!result.source_sha_ok ? ' · source bytes differ' : ''}
            {!result.artifact_sha_ok ? ' · artifact differs' : ''}
            {!result.input_sha_ok ? ' · input hash differs' : ''}
            {!result.value_ok ? ' · cited value differs' : ''}
          </span>
        )
      ) : null}
      {mutation.error ? (
        <span role="alert" data-testid="recheck-error" className="text-sm text-red-800">
          {mutation.error.message}
        </span>
      ) : null}
    </div>
  );
}
