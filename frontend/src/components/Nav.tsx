import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, CSRF, unwrap } from '../lib/api/client';
import { keys } from '../lib/query/keys';

/** Top bar: where you are, where you can go, who is signed in (from the server session). */
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
  const path = window.location.pathname.replace(/\/$/, '');
  const suffix = caseId ? `?id=${encodeURIComponent(caseId)}` : '';
  const link = (href: string, label: string, active: boolean) => (
    <a href={href} aria-current={active ? 'page' : undefined}>
      {label}
    </a>
  );
  return (
    <header className="topbar">
      <nav aria-label="Main" className="topbar-inner">
        <a href="/" className="brand">
          TRACE <small>Traceable evidence across documents and sensors</small>
        </a>
        <div className="navlinks">
          {link('/', 'Cases', path === '')}
          {caseId ? link(`/case/${suffix}`, 'Case', path === '/case') : null}
          {caseId ? link(`/case/expert/${suffix}`, 'Expert view', path === '/case/expert') : null}
          {link(`/review/${suffix}`, 'Review queue', path === '/review')}
          {link('/eval/', 'Evaluation', path === '/eval')}
        </div>
        <div className="whoami">
          <span data-testid="whoami">
            {me.data ? (
              <>
                {me.data.display_name} <span className="role">({me.data.role})</span>
              </>
            ) : me.isLoading ? (
              ''
            ) : (
              'Not signed in'
            )}
          </span>
          {me.data ? (
            <button type="button" className="btn btn-sm" onClick={() => logout.mutate()} data-testid="logout">
              Sign out
            </button>
          ) : (
            <a href="/login/" className="btn btn-sm">
              Sign in
            </a>
          )}
        </div>
      </nav>
    </header>
  );
}
