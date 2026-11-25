import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { useState, type ReactNode } from 'react';
import { ApiError } from '../lib/api/client';

export function caseIdFromLocation(): string | null {
  return new URLSearchParams(window.location.search).get('id');
}

/** One island per page, so one QueryClient per page. A 401 on any query sends the browser to the
 *  login page; nothing else is retried (a wrong answer must not be retried into a right-looking one). */
export default function Providers({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            retry: false,
            refetchOnWindowFocus: false,
            throwOnError: (error) => {
              if (error instanceof ApiError && error.status === 401 && window.location.pathname !== '/login/') {
                window.location.assign('/login/');
              }
              return false;
            },
          },
        },
      }),
  );
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

export function Loading({ what }: { what: string }) {
  return (
    <p className="empty" role="status">
      Loading {what}...
    </p>
  );
}

export function ErrorNote({ error }: { error: Error }) {
  return (
    <p role="alert" data-testid="error" className="callout callout-bad">
      {error.message}
      {error instanceof ApiError && error.status === 401 ? (
        <>
          {' '}
          <a href="/login/">Sign in</a>
        </>
      ) : null}
    </p>
  );
}
