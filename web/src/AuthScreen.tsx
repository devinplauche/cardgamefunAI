import { useEffect, useRef, useState } from 'react';
import type { User } from './types';
import { login, register, authConfig, googleSignIn } from './auth';

declare global {
  interface Window {
    google?: {
      accounts: {
        id: {
          initialize: (config: {
            client_id: string;
            callback: (response: { credential: string }) => void;
          }) => void;
          renderButton: (element: HTMLElement, options: Record<string, unknown>) => void;
        };
      };
    };
  }
}

const GIS_SCRIPT_SRC = 'https://accounts.google.com/gsi/client';

function loadGisScript(): Promise<void> {
  if (window.google?.accounts?.id) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const fail = () => reject(new Error('Could not load Google sign-in. Check your connection and try again.'));
    const existing = document.querySelector<HTMLScriptElement>(`script[src="${GIS_SCRIPT_SRC}"]`);
    if (existing) {
      existing.addEventListener('load', () => resolve(), { once: true });
      existing.addEventListener('error', fail, { once: true });
      return;
    }
    const script = document.createElement('script');
    script.src = GIS_SCRIPT_SRC;
    script.async = true;
    script.defer = true;
    script.addEventListener('load', () => resolve(), { once: true });
    script.addEventListener('error', fail, { once: true });
    document.head.appendChild(script);
  });
}

export function AuthScreen({ onAuth }: { onAuth: (user: User) => void }) {
  const [mode, setMode] = useState<'login' | 'register'>('login');
  const [username, setUsername] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [googleClientId, setGoogleClientId] = useState<string | null>(null);
  const googleBtnRef = useRef<HTMLDivElement>(null);
  const onAuthRef = useRef(onAuth);
  onAuthRef.current = onAuth;

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

  // Ask the backend whether Google sign-in is configured (the client ID is
  // public; every ID token is still verified server-side).
  useEffect(() => {
    let cancelled = false;
    authConfig()
      .then((config) => {
        if (!cancelled && config.googleClientId) setGoogleClientId(config.googleClientId);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, []);

  // Render the official Google button once the client ID is known.
  useEffect(() => {
    if (!googleClientId) return;
    let cancelled = false;
    loadGisScript()
      .then(() => {
        if (cancelled || !window.google || !googleBtnRef.current) return;
        window.google.accounts.id.initialize({
          client_id: googleClientId,
          callback: (response) => {
            setError(null);
            setBusy(true);
            googleSignIn(response.credential)
              .then((user) => onAuthRef.current(user))
              .catch((err: unknown) => {
                setError(err instanceof Error ? err.message : 'Google sign-in failed.');
              })
              .finally(() => setBusy(false));
          },
        });
        window.google.accounts.id.renderButton(googleBtnRef.current, {
          theme: 'outline',
          size: 'large',
          width: 320,
          text: 'signin_with',
        });
      })
      .catch((err: unknown) => {
        if (!cancelled) setError(err instanceof Error ? err.message : 'Google sign-in failed.');
      });
    return () => {
      cancelled = true;
    };
  }, [googleClientId]);

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
          {googleClientId ? (
            <>
              <div className="auth-divider" aria-hidden="true"><span>or</span></div>
              <div ref={googleBtnRef} className="google-btn-wrap" />
            </>
          ) : null}
        </section>
      </main>
    </div>
  );
}
