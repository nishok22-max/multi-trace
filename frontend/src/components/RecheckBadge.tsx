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
    <div className="actions" data-testid="recheck">
      <button type="button" data-testid="recheck-button" className="btn btn-sm" disabled={mutation.isPending} onClick={() => mutation.mutate()}>
        {mutation.isPending ? 'Re-checking...' : 'Re-check now'}
      </button>
      {result ? (
        result.match ? (
          <span data-testid="recheck-result" data-match="true" className="badge badge-ok">
            <span className="dot" /> Re-checked just now: matches the stored evidence
          </span>
        ) : (
          <span data-testid="recheck-result" data-match="false" role="alert" className="badge badge-bad">
            Evidence changed
            {!result.source_sha_ok ? ' · source bytes differ' : ''}
            {!result.artifact_sha_ok ? ' · artifact differs' : ''}
            {!result.input_sha_ok ? ' · input hash differs' : ''}
            {!result.value_ok ? ' · cited value differs' : ''}
          </span>
        )
      ) : null}
      {mutation.error ? (
        <span role="alert" data-testid="recheck-error" className="field-error">
          {mutation.error.message}
        </span>
      ) : null}
    </div>
  );
}
