import { QueryClient, QueryClientProvider, useQuery } from '@tanstack/react-query';
import { useState } from 'react';
import ConflictCard from '../components/ConflictCard';
import StorySteps from '../components/StorySteps';
import VersionBadge from '../components/VersionBadge';
import { api, ApiError, unwrap } from '../lib/api/client';
import { keys } from '../lib/query/keys';

function caseIdFromLocation(): string | null {
  return new URLSearchParams(window.location.search).get('id');
}

/** Resolves `latest` (a 307 to a versioned path) to a version number. */
async function fetchLatestVersion(caseId: string): Promise<number> {
  const res = await api.GET('/api/v1/cases/{cid}/latest', { params: { path: { cid: caseId } } });
  if (!res.response.ok) {
    throw new ApiError(res.response.status, `Could not resolve the latest version (${res.response.status}).`);
  }
  const match = /\/versions\/(\d+)\//.exec(res.response.url);
  const version = match?.[1];
  if (version === undefined) throw new ApiError(500, 'The server did not name a version.');
  return Number(version);
}

function Workspace({ caseId }: { caseId: string }) {
  const latest = useQuery({ queryKey: keys.latest(caseId), queryFn: () => fetchLatestVersion(caseId) });
  const version = latest.data;
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
      unwrap(
        await api.GET('/api/v1/cases/{cid}/versions/{v}/claims', {
          params: { path, query: { limit: 500 } },
        }),
      ),
  });

  const failure = [latest, state, story, conflicts, comparisons, claims].find((q) => q.error);
  if (failure?.error) {
    return (
      <p role="alert" data-testid="error" className="rounded border border-red-700 bg-red-50 p-3">
        {failure.error instanceof ApiError ? failure.error.message : 'Could not load this case.'}
      </p>
    );
  }
  if (!state.data || !story.data || !conflicts.data || !comparisons.data || !claims.data) {
    return <p>Loading case...</p>;
  }
  return (
    <div>
      <header className="mb-4 flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold">{state.data.case_id}</h1>
        <VersionBadge version={state.data.version} manifestHash={state.data.manifest_hash} />
      </header>
      <StorySteps story={story.data} />
      {conflicts.data.items.length === 0 ? (
        <p data-testid="no-conflict">No conflict in this version.</p>
      ) : (
        conflicts.data.items.map((conflict) => {
          const comparison = comparisons.data.items.find((c) => conflict.comparison_ids.includes(c.comparison_id));
          return comparison ? (
            <ConflictCard
              key={conflict.conflict_id}
              conflict={conflict}
              comparison={comparison}
              claims={claims.data.items}
              state={state.data}
            />
          ) : null;
        })
      )}
    </div>
  );
}

export default function CaseWorkspace() {
  const [client] = useState(() => new QueryClient({ defaultOptions: { queries: { retry: false } } }));
  const caseId = caseIdFromLocation();
  return (
    <QueryClientProvider client={client}>
      {caseId ? <Workspace caseId={caseId} /> : <p role="alert">Open a case with ?id=&lt;case id&gt;.</p>}
    </QueryClientProvider>
  );
}
