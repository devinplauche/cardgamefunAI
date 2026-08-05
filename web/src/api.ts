import type { GameState } from './types';

const API_BASE = '';

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(init?.headers ?? {}),
    },
    ...init,
  });

  const payload = await response.json().catch(() => null);
  if (!response.ok) {
    const message = payload && typeof payload.error === 'string' ? payload.error : response.statusText;
    throw new Error(message || 'Request failed');
  }
  return payload as T;
}

export async function createSession(input: { seed: number; algorithm: string; budgetMs: number }): Promise<GameState> {
  return requestJson<GameState>('/api/sessions', {
    method: 'POST',
    body: JSON.stringify({
      seed: input.seed,
      algorithm: input.algorithm,
      budgetMs: input.budgetMs,
    }),
  });
}

export async function loadSession(sessionId: string): Promise<GameState> {
  return requestJson<GameState>(`/api/sessions/${sessionId}`);
}

export async function playCard(sessionId: string, cardId: string, stunTargetIndex?: number): Promise<GameState> {
  return requestJson<GameState>(`/api/sessions/${sessionId}/play-card`, {
    method: 'POST',
    body: JSON.stringify({ cardId, stunTargetIndex }),
  });
}

export async function sacrificePlayed(sessionId: string, cardId: string): Promise<GameState> {
  return requestJson<GameState>(`/api/sessions/${sessionId}/sacrifice-played`, {
    method: 'POST',
    body: JSON.stringify({ cardId }),
  });
}

export async function expendChampion(sessionId: string, championId: string, stunTargetIndex?: number, choice?: string): Promise<GameState> {
  return requestJson<GameState>(`/api/sessions/${sessionId}/expend-champion`, {
    method: 'POST',
    body: JSON.stringify({ championId, stunTargetIndex, choice }),
  });
}

export async function buyCard(sessionId: string, marketIndex: number): Promise<GameState> {
  return requestJson<GameState>(`/api/sessions/${sessionId}/buy-card`, {
    method: 'POST',
    body: JSON.stringify({ marketIndex }),
  });
}

export async function attackTarget(sessionId: string, target: 'player' | 'champion', championId?: string): Promise<GameState> {
  return requestJson<GameState>(`/api/sessions/${sessionId}/attack`, {
    method: 'POST',
    body: JSON.stringify({ target, championId }),
  });
}

export async function advancePhase(sessionId: string): Promise<GameState> {
  return requestJson<GameState>(`/api/sessions/${sessionId}/advance-phase`, {
    method: 'POST',
    body: '{}',
  });
}

export async function endTurn(sessionId: string): Promise<GameState> {
  return requestJson<GameState>(`/api/sessions/${sessionId}/end-turn`, {
    method: 'POST',
    body: '{}',
  });
}

export async function runBotTurn(sessionId: string, algorithm: string, budgetMs: number): Promise<GameState> {
  return requestJson<GameState>(`/api/sessions/${sessionId}/bot-turn`, {
    method: 'POST',
    body: JSON.stringify({ algorithm, budgetMs }),
  });
}
