import { useState } from 'react';
import type { User } from './types';
import { login, register } from './auth';

export function AuthScreen({ onAuth }: { onAuth: (user: User) => void }) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(event: React.FormEvent) {
    event.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const user = mode === 'login' ? await login(username.trim(), password) : await register(username.trim(), password);
      onAuth(user);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Sign in failed.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="app-shell">
      <main className="auth-main">
        <section className="auth-card">
          <h1 className="auth-title">Hero Realms</h1>
          <p className="auth-sub">Sign in to play against a human opponent.</p>
          <div className="auth-tabs">
            <button
              type="button"
              className={mode === 'login' ? 'auth-tab active' : 'auth-tab'}
              onClick={() => { setMode('login'); setError(null); }}
            >
              Sign in
            </button>
            <button
              type="button"
              className={mode === 'register' ? 'auth-tab active' : 'auth-tab'}
              onClick={() => { setMode('register'); setError(null); }}
            >
              Create account
            </button>
          </div>
          <form onSubmit={submit} className="auth-form">
            <label className="auth-label">
              Username
              <input
                className="auth-input"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="username"
                maxLength={64}
                required
              />
            </label>
            <label className="auth-label">
              Password
              <input
                className="auth-input"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete={mode === 'login' ? 'current-password' : 'new-password'}
                minLength={6}
                required
              />
            </label>
            {error ? <p className="auth-error">{error}</p> : null}
            <button type="submit" className="primary-button auth-submit" disabled={busy}>
              {busy ? 'Working…' : mode === 'login' ? 'Sign in' : 'Create account'}
            </button>
          </form>
        </section>
      </main>
    </div>
  );
}
