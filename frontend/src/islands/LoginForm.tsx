import { useMutation } from '@tanstack/react-query';
import { useState } from 'react';
import { api, ApiError, CSRF, unwrap } from '../lib/api/client';
import Providers from './Providers';

function Form() {
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const login = useMutation({
    mutationFn: async () =>
      unwrap(await api.POST('/api/v1/auth/login', { params: { header: CSRF }, body: { username, password } })),
    onSuccess: () => window.location.assign('/'),
  });
  const error = login.error;
  const message =
    error instanceof ApiError
      ? error.status === 429
        ? 'Too many attempts. Wait 5 minutes and try again.'
        : error.status === 401
          ? 'Wrong user name or password.'
          : error.message
      : null;
  return (
    <form
      aria-label="Sign in"
      className="mx-auto max-w-sm space-y-3 rounded border border-slate-400 bg-white p-4"
      onSubmit={(e) => {
        e.preventDefault();
        login.mutate();
      }}
    >
      <h1 className="text-xl font-bold">Sign in to TRACE</h1>
      <label className="block text-sm">
        User name
        <input
          data-testid="username"
          autoComplete="username"
          className="mt-1 block w-full rounded border border-slate-500 p-1"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
        />
      </label>
      <label className="block text-sm">
        Password
        <input
          data-testid="password"
          type="password"
          autoComplete="current-password"
          className="mt-1 block w-full rounded border border-slate-500 p-1"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
        />
      </label>
      {message ? (
        <p role="alert" data-testid="login-error" className="text-sm text-red-800">
          {message}
        </p>
      ) : null}
      <button type="submit" data-testid="login" disabled={login.isPending || !username || !password} className="rounded bg-slate-800 px-3 py-1 font-semibold text-white">
        {login.isPending ? 'Signing in...' : 'Sign in'}
      </button>
    </form>
  );
}

export default function LoginForm() {
  return (
    <Providers>
      <Form />
    </Providers>
  );
}
