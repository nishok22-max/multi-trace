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
    <div className="login-wrap">
      <form
        aria-label="Sign in"
        className="card login stack-sm"
        onSubmit={(e) => {
          e.preventDefault();
          login.mutate();
        }}
      >
        <div>
          <p className="brand" style={{ margin: '0 0 14px' }}>
            TRACE
          </p>
          <h1>Sign in</h1>
          <p className="lead">Every fact in TRACE has an address. Sign in to follow it.</p>
        </div>
        <label className="field">
          User name
          <input data-testid="username" className="input" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} />
        </label>
        <label className="field">
          Password
          <input data-testid="password" className="input" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {message ? (
          <p role="alert" data-testid="login-error" className="field-error">
            {message}
          </p>
        ) : null}
        <button type="submit" data-testid="login" disabled={login.isPending || !username || !password} className="btn btn-primary">
          {login.isPending ? 'Signing in...' : 'Sign in'}
        </button>
      </form>
    </div>
  );
}

export default function LoginForm() {
  return (
    <Providers>
      <Form />
    </Providers>
  );
}
