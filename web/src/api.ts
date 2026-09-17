import type { GameState, GameSummary, HumanGameState } from './types';
import type { HistoryFrame } from './types';
import { BotStreamNetworkError, readBotStream } from './botStream';

const API_BASE = '';

// ---- Network resilience --------------------------------------------------
//
// A response lost in transit (dead phone radio, dropped connection) must
// never hang the UI: every game action sets `busy`, which gates all input,
// so a hung fetch looks exactly like a frozen game.
//
// Quick tap mutations fail fast (~10s) and retry up to 3 times with the SAME
// idempotency key, so a retry can never double-apply: the backend dedupes by
// X-Idempotency-Key. Reads, session creation, and the bot-turn stream keep
// generous 30s+ timeouts (Cloud Run cold starts, long bot thinks).

const QUICK_TIMEOUT_MS = 10_000;
const QUICK_ATTEMPTS = 3;
const SLOW_TIMEOUT_MS = 30_000;
/** Bot-turn stream: no chunk for this long means the connection is dead. */
const STREAM_IDLE_TIMEOUT_MS = 120_000;
/** HTTP statuses worth retrying; other 4xx means the request itself was refused. */
const RETRYABLE_STATUS = new Set([408, 425, 429, 500, 502, 503, 504]);

const TIMEOUT_MESSAGE = 'The request timed out. Check your connection and try again.';

// ---- Connectivity signal ---------------------------------------------------
// A sibling renders the indicator UI from this event; this module only
// reports reachability transitions, driven by navigator.onLine plus
// failed-request detection.

export const NET_EVENT = 'hr:net';
export interface NetStatusDetail {
  online: boolean;
}

let netOnline = typeof navigator === 'undefined' || navigator.onLine;

function setNetOnline(online: boolean): void {
  if (online === netOnline) return;
  netOnline = online;
  window.dispatchEvent(new CustomEvent<NetStatusDetail>(NET_EVENT, { detail: { online } }));
}

export function isNetOnline(): boolean {
  return netOnline;
}

export function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === 'AbortError';
}

if (typeof window !== 'undefined') {
  window.addEventListener('online', () => setNetOnline(true));
  window.addEventListener('offline', () => setNetOnline(false));
}

// ---- Errors ------------------------------------------------------------------

/** A refresh that lost to a newer refresh for the same game/session. Never retried. */
export class RefreshSupersededError extends Error {
  constructor() {
    super('A newer refresh superseded this one.');
    this.name = 'RefreshSupersededError';
  }
}

class TimeoutError extends Error {
  constructor() {
    super(TIMEOUT_MESSAGE);
    this.name = 'TimeoutError';
  }
}

class HttpError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
    this.name = 'HttpError';
  }
}

function isRetryable(error: unknown): boolean {
  if (error instanceof HttpError) return RETRYABLE_STATUS.has(error.status);
  if (error instanceof TimeoutError) return true;
  // fetch() throws TypeError on network-level failure (DNS, refused, dropped).
  if (error instanceof TypeError) return true;
  return false;
}

const sleep = (ms: number): Promise<void> =>
  new Promise<void>((resolve) => window.setTimeout(resolve, ms));

interface RequestOptions {
  timeoutMs?: number;
  /** Total attempts including the first. Defaults to 1 (no retry). */
  attempts?: number;
  /** Mutation: send X-Idempotency-Key, generated once and reused across retries. */
  idempotent?: boolean;
  /** Refresh-guard signal: aborting it supersedes this request, never retries. */
  supersedeSignal?: AbortSignal;
}

async function attemptJson<T>(
  path: string,
  init: RequestInit | undefined,
  timeoutMs: number,
  idempotencyKey: string | undefined,
  supersedeSignal: AbortSignal | undefined,
): Promise<T> {
  const controller = new AbortController();
  let timedOut = false;
  let superseded = false;
  const timer = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, timeoutMs);
  const callerSignal = init?.signal ?? null;
  const onCallerAbort = (): void => controller.abort();
  const onSupersede = (): void => {
    superseded = true;
    controller.abort();
  };
  if (callerSignal) {
    if (callerSignal.aborted) onCallerAbort();
    else callerSignal.addEventListener('abort', onCallerAbort, { once: true });
  }
  if (supersedeSignal) {
    if (supersedeSignal.aborted) onSupersede();
    else supersedeSignal.addEventListener('abort', onSupersede, { once: true });
  }
  try {
    const response = await fetch(`${API_BASE}${path}`, {
      headers: {
        'Content-Type': 'application/json',
        ...(idempotencyKey ? { 'X-Idempotency-Key': idempotencyKey } : {}),
        ...(init?.headers ?? {}),
      },
      ...init,
      signal: controller.signal,
    });
    // Any HTTP response, even an error status, proves we are online.
    setNetOnline(true);

    const payload = await response.json().catch(() => null);
    if (!response.ok) {
      const message = payload && typeof payload.error === 'string' ? payload.error : response.statusText;
      throw new HttpError(response.status, message || 'Request failed');
    }
    return payload as T;
  } catch (error) {
    if (superseded) throw new RefreshSupersededError();
    if (timedOut) {
      setNetOnline(false);
      throw new TimeoutError();
    }
    if (error instanceof HttpError) throw error;
    if (isAbortError(error)) throw error; // caller abort: intentional, not a signal
    // Network-level failure with no HTTP response.
    setNetOnline(false);
    throw error;
  } finally {
    window.clearTimeout(timer);
    callerSignal?.removeEventListener('abort', onCallerAbort);
    supersedeSignal?.removeEventListener('abort', onSupersede);
  }
}

async function requestJson<T>(path: string, init?: RequestInit, opts?: RequestOptions): Promise<T> {
  const timeoutMs = opts?.timeoutMs ?? SLOW_TIMEOUT_MS;
  const attempts = Math.max(1, opts?.attempts ?? 1);
  // One key per logical mutation, shared by every retry attempt, so the
  // backend dedupes a retried tap instead of applying it twice.
  const idempotencyKey = opts?.idempotent ? crypto.randomUUID() : undefined;
  let lastError: unknown = null;
  for (let attempt = 1; attempt <= attempts; attempt++) {
    try {
      return await attemptJson<T>(path, init, timeoutMs, idempotencyKey, opts?.supersedeSignal);
    } catch (error) {
      lastError = error;
      if (error instanceof RefreshSupersededError) throw error;
      if (isAbortError(error)) throw error; // caller abort is intentional: never retry
      if (attempt < attempts && isRetryable(error)) {
        await sleep(250 * attempt);
        continue;
      }
      throw error;
    }
  }
  throw lastError;
}

/** Quick tap mutation: 10s timeout, up to 3 attempts, idempotent retry. */
function mutate<T>(path: string, body: unknown): Promise<T> {
  return requestJson<T>(
    path,
    { method: 'POST', body: JSON.stringify(body) },
    { timeoutMs: QUICK_TIMEOUT_MS, attempts: QUICK_ATTEMPTS, idempotent: true },
  );
}

// ---- Refresh guard ------------------------------------------------------------
// The poll, manual refresh, and post-action refreshes can overlap. Per
// game/session only one refresh is ever in flight: identical refreshes share
// the in-flight promise, and a full refresh aborts an in-flight poll tick
// (the tick's caller already ignores the supersede error). A slow response
// can therefore never overwrite newer state.

interface RefreshEntry {
  promise: Promise<unknown>;
  controller: AbortController;
  full: boolean;
}

const inflightRefresh = new Map<string, RefreshEntry>();

function guardedRefresh<T>(
  key: string,
  full: boolean,
  start: (supersedeSignal: AbortSignal) => Promise<T>,
): Promise<T> {
  const existing = inflightRefresh.get(key);
  if (existing) {
    if (full && !existing.full) {
      existing.controller.abort();
    } else {
      return existing.promise as Promise<T>;
    }
  }
  const controller = new AbortController();
  const cleanup = (): void => {
    if (inflightRefresh.get(key)?.controller === controller) inflightRefresh.delete(key);
  };
  const tracked = start(controller.signal).then(
    (value) => {
      cleanup();
      return value;
    },
    (error) => {
      cleanup();
      throw error;
    },
  );
  inflightRefresh.set(key, { promise: tracked, controller, full });
  return tracked;
}

export async function createSession(input: { seed: number; algorithm: string; budgetMs: number }): Promise<GameState> {
  return requestJson<GameState>(
    '/api/sessions',
    {
      method: 'POST',
      body: JSON.stringify({
        seed: input.seed,
        algorithm: input.algorithm,
        budgetMs: input.budgetMs,
      }),
    },
    // Session creation keeps the generous timeout and is never retried: a
    // blind retry could orphan a duplicate session.
    { timeoutMs: SLOW_TIMEOUT_MS, idempotent: true },
  );
}

export async function loadSession(sessionId: string): Promise<GameState> {
  return guardedRefresh(`session:${sessionId}`, true, (supersedeSignal) =>
    requestJson<GameState>(`/api/sessions/${sessionId}`, undefined, { supersedeSignal }),
  );
}

export async function playCard(sessionId: string, cardId: string, stunTargetIndex?: number): Promise<GameState> {
  return mutate<GameState>(`/api/sessions/${sessionId}/play-card`, { cardId, stunTargetIndex });
}

export async function sacrificePlayed(sessionId: string, cardId: string): Promise<GameState> {
  return mutate<GameState>(`/api/sessions/${sessionId}/sacrifice-played`, { cardId });
}

export async function expendChampion(
  sessionId: string,
  championId: string,
  stunTargetIndex?: number,
  choice?: string,
  sacrificeIndex?: number,
  sacrificeZone?: string,
): Promise<GameState> {
  return mutate<GameState>(`/api/sessions/${sessionId}/expend-champion`, {
    championId,
    stunTargetIndex,
    choice,
    sacrificeIndex,
    sacrificeZone,
  });
}

export async function triggerAlly(
  sessionId: string,
  cardId: string,
  stunTargetIndex?: number,
): Promise<GameState> {
  return mutate<GameState>(`/api/sessions/${sessionId}/trigger-ally`, { cardId, stunTargetIndex });
}

export async function buyCard(sessionId: string, marketIndex: number): Promise<GameState> {
  return mutate<GameState>(`/api/sessions/${sessionId}/buy-card`, { marketIndex });
}

export async function attackTarget(sessionId: string, target: 'player' | 'champion', championId?: string): Promise<GameState> {
  return mutate<GameState>(`/api/sessions/${sessionId}/attack`, { target, championId });
}

export async function advancePhase(sessionId: string): Promise<GameState> {
  return mutate<GameState>(`/api/sessions/${sessionId}/advance-phase`, {});
}

export async function endTurn(sessionId: string): Promise<GameState> {
  return mutate<GameState>(`/api/sessions/${sessionId}/end-turn`, {});
}

export async function runBotTurn(sessionId: string, algorithm: string, budgetMs: number): Promise<GameState> {
  return requestJson<GameState>(
    `/api/sessions/${sessionId}/bot-turn`,
    { method: 'POST', body: JSON.stringify({ algorithm, budgetMs }) },
    // A bot turn is a single committed run: generous timeout, no blind retry.
    { timeoutMs: SLOW_TIMEOUT_MS, idempotent: true },
  );
}

export async function playAll(sessionId: string): Promise<GameState> {
  return mutate<GameState>(`/api/sessions/${sessionId}/play-all`, {});
}

export async function resolveChoice(sessionId: string, candidateIndex: number): Promise<GameState> {
  return mutate<GameState>(`/api/sessions/${sessionId}/resolve-choice`, { candidateIndex });
}

export async function streamBotTurn(
  sessionId: string, algorithm: string, budgetMs: number,
  onFrame: (frame: HistoryFrame) => Promise<void>, signal: AbortSignal,
): Promise<GameState> {
  const controller = new AbortController();
  let timedOut = false;
  const timer = window.setTimeout(() => {
    timedOut = true;
    controller.abort();
  }, SLOW_TIMEOUT_MS);
  // A caller-provided signal still aborts the request.
  if (signal.aborted) controller.abort();
  else signal.addEventListener('abort', () => controller.abort(), { once: true });
  try {
    const response = await fetch(`${API_BASE}/api/sessions/${sessionId}/bot-turn-stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'X-Idempotency-Key': crypto.randomUUID() },
      body: JSON.stringify({ algorithm, budgetMs }),
      signal: controller.signal,
    });
    // Headers arrived: the connection phase is over; the body read below has
    // its own idle timeout.
    window.clearTimeout(timer);
    setNetOnline(true);
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      throw new Error(payload?.error || response.statusText);
    }
    if (!response.body) throw new Error('This browser does not support streamed turns.');
    return await readBotStream(response.body, onFrame, { idleTimeoutMs: STREAM_IDLE_TIMEOUT_MS });
  } catch (error) {
    window.clearTimeout(timer);
    if (signal.aborted) throw error;
    if (timedOut) {
      setNetOnline(false);
      throw new TimeoutError();
    }
    if (error instanceof TypeError || error instanceof BotStreamNetworkError) setNetOnline(false);
    throw error;
  }
}

export type { GameSummary, HumanGameState };

export async function createGame(): Promise<{ id: string; inviteCode: string }> {
  return mutate('/api/games', {});
}

export async function joinGame(code: string): Promise<{ id: string; inviteCode: string }> {
  return mutate('/api/games/join', { code });
}

export async function listGames(): Promise<{ games: GameSummary[] }> {
  return guardedRefresh('games', true, (supersedeSignal) =>
    requestJson<{ games: GameSummary[] }>('/api/games', undefined, { supersedeSignal }),
  );
}

export interface GamePollResult {
  changed?: boolean;
  turnCount?: number;
}

export async function loadGame(
  gameId: string,
  since?: number,
): Promise<HumanGameState | GamePollResult> {
  const path = since === undefined ? `/api/games/${gameId}` : `/api/games/${gameId}?since=${since}`;
  return guardedRefresh(`game:${gameId}`, since === undefined, (supersedeSignal) =>
    requestJson<HumanGameState | GamePollResult>(path, undefined, { supersedeSignal }),
  );
}

export async function gameAction(
  gameId: string,
  action: string,
  params: Record<string, unknown> = {},
): Promise<HumanGameState> {
  return mutate<HumanGameState>(`/api/games/${gameId}/action`, { action, ...params });
}

export async function undo(gameId: string): Promise<HumanGameState> {
  return mutate<HumanGameState>(`/api/games/${gameId}/undo`, {});
}
