import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, CSRF, unwrap } from '../lib/api/client';
import { keys } from '../lib/query/keys';

/** Session header: who is signed in (from the server session) and sign out. */
export default function Nav({ caseId }: { caseId?: string | null | undefined }) {
  const client = useQueryClient();
  const me = useQuery({
    queryKey: keys.me(),
    retry: false,
    queryFn: async () => unwrap(await api.GET('/api/v1/auth/me')),
  });
  const logout = useMutation({
    mutationFn: async () => {
      await api.POST('/api/v1/auth/logout', { params: { header: CSRF } });
    },
    onSuccess: () => {
      client.clear();
      window.location.assign('/login/');
    },
  });
  const suffix = caseId ? `?id=${encodeURIComponent(caseId)}` : '';
  return (
    <nav aria-label="Main" className="mb-4 flex flex-wrap items-center gap-4 border-b border-slate-300 pb-2 text-sm">
      <a href="/" className="font-bold">
        TRACE
      </a>
      <a href="/">Cases</a>
      {caseId ? <a href={`/case/${suffix}`}>Case</a> : null}
      {caseId ? <a href={`/case/expert/${suffix}`}>Expert view</a> : null}
      <a href="/review/">Review queue</a>
      <a href="/eval/">Evaluation</a>
      <span className="ml-auto" data-testid="whoami">
        {me.data ? `${me.data.display_name} (${me.data.role})` : me.isLoading ? '' : 'Not signed in'}
      </span>
      {me.data ? (
        <button type="button" className="rounded border border-slate-500 px-2 py-0.5" onClick={() => logout.mutate()} data-testid="logout">
          Sign out
        </button>
      ) : (
        <a href="/login/" className="underline">
          Sign in
        </a>
      )}
    </nav>
  );
}
