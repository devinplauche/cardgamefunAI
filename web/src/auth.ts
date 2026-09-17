import type { User } from './types';

// Same timeout rationale as api.ts: a hung auth fetch must surface an
// error, never hang the form forever.
const REQUEST_TIMEOUT_MS = 30_000;

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, REQUEST_TIMEOUT_MS);
  try {
    const response = await fetch(path, {
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
      ...init,
      signal: controller.signal,
    });
    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      const message =
        payload && typeof payload.error === 'string' ? payload.error : response.statusText;
      const err = new Error(message || 'Request failed') as Error & { status: number };
      err.status = response.status;
      throw err;
    }
    return payload as T;
  } catch (error) {
    if (timedOut) throw new Error('The request timed out. Check your connection and try again.');
    throw error;
  } finally {
    window.clearTimeout(timer);
  }
}

export async function me(): Promise<User | null> {
  try {
    const payload = await requestJson<{ user: User }>('/api/auth/me');
    return payload.user;
  } catch (err) {
    if ((err as { status?: number }).status === 401) return null;
    throw err;
  }
}

export async function register(username: string, password: string): Promise<User> {
  const payload = await requestJson<{ user: User }>('/api/auth/register', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });
  return payload.user;
}

export async function login(username: string, password: string): Promise<User> {
  const payload = await requestJson<{ user: User }>('/api/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  });
  return payload.user;
}

export async function logout(): Promise<void> {
  await requestJson('/api/auth/logout', { method: 'POST', body: '{}' });
}
