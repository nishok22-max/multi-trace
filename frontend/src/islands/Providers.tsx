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

export function ErrorNote({ error }: { error: Error }) {
  return (
    <p role="alert" data-testid="error" className="rounded border border-red-700 bg-red-50 p-3">
      {error.message}
      {error instanceof ApiError && error.status === 401 ? (
        <>
          {' '}
          <a href="/login/" className="underline">
            Sign in
          </a>
        </>
      ) : null}
    </p>
  );
}
