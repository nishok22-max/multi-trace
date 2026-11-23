import { useQuery } from '@tanstack/react-query';
import { api, ApiError, unwrap } from '../api/client';
import { keys } from './keys';

/** Resolves `latest` (a 307 to a versioned path) to a version number. */
export async function fetchLatestVersion(caseId: string): Promise<number> {
  const res = await api.GET('/api/v1/cases/{cid}/latest', { params: { path: { cid: caseId } } });
  if (!res.response.ok) {
    throw new ApiError(res.response.status, res.response.status === 404 ? 'No built version yet.' : `Could not resolve the latest version (${res.response.status}).`);
  }
  const match = /\/versions\/(\d+)\//.exec(res.response.url);
  const version = match?.[1];
  if (version === undefined) throw new ApiError(500, 'The server did not name a version.');
  return Number(version);
}

export function useLatest(caseId: string) {
  return useQuery({ queryKey: keys.latest(caseId), queryFn: () => fetchLatestVersion(caseId), staleTime: 0 });
}

/** All versioned reads of one case at ONE version: nothing is requested until a version is known,
 *  and every key carries it. */
export function useCaseVersion(caseId: string, version: number | undefined) {
  const enabled = version !== undefined;
  const v = version ?? 0;
  const path = { cid: caseId, v };
  const state = useQuery({
    queryKey: keys.state(caseId, v),
    enabled,
    queryFn: async () => unwrap(await api.GET('/api/v1/cases/{cid}/versions/{v}/state', { params: { path } })),
  });
  const story = useQuery({
    queryKey: keys.story(caseId, v),
    enabled,
    queryFn: async () => unwrap(await api.GET('/api/v1/cases/{cid}/versions/{v}/story', { params: { path } })),
  });
  const conflicts = useQuery({
    queryKey: keys.conflicts(caseId, v),
    enabled,
    queryFn: async () => unwrap(await api.GET('/api/v1/cases/{cid}/versions/{v}/conflicts', { params: { path } })),
  });
  const comparisons = useQuery({
    queryKey: keys.comparisons(caseId, v),
    enabled,
    queryFn: async () =>
      unwrap(await api.GET('/api/v1/cases/{cid}/versions/{v}/comparisons', { params: { path } })),
  });
  const claims = useQuery({
    queryKey: keys.claims(caseId, v),
    enabled,
    queryFn: async () =>
      unwrap(await api.GET('/api/v1/cases/{cid}/versions/{v}/claims', { params: { path, query: { limit: 500 } } })),
  });
  const timeline = useQuery({
    queryKey: keys.timeline(caseId, v),
    enabled,
    queryFn: async () => unwrap(await api.GET('/api/v1/cases/{cid}/versions/{v}/timeline', { params: { path } })),
  });
  const review = useQuery({
    queryKey: keys.review(caseId, v),
    enabled,
    queryFn: async () => unwrap(await api.GET('/api/v1/cases/{cid}/versions/{v}/review', { params: { path } })),
  });
  return { state, story, conflicts, comparisons, claims, timeline, review };
}

export function firstError(queries: Array<{ error: unknown }>): ApiError | Error | null {
  const hit = queries.find((q) => q.error);
  return hit ? (hit.error as Error) : null;
}
