// Pre-suite health check for the e2e rig.
//
// Playwright runs this once before any spec file (see `globalSetup` in
// playwright.config.ts). It exercises the exact round-trip every rigged test
// depends on — register, create session, debug-setup a hand — so a dead,
// unreachable, or misconfigured backend (e.g. HR_DEBUG_SETUP=1 not enabled
// for the test window) aborts the whole run with ONE clear line instead of
// every test burning 20s `toBeVisible` timeouts one after another.
//
// Node 18+ (global fetch, AbortSignal.timeout). No Playwright imports: this
// also runs standalone via `node` for a quick smoke test.
const BASE = process.env.E2E_BASE_URL || 'https://hero-realms-yokyhjajxq-uc.a.run.app';
const REQ_TIMEOUT_MS = 10_000;

type ApiResult = { status: number; body: unknown };

async function api(p: string, init?: RequestInit, cookie?: string): Promise<ApiResult> {
  const res = await fetch(`${BASE}${p}`, {
    ...init,
    signal: AbortSignal.timeout(REQ_TIMEOUT_MS),
    headers: {
      'Content-Type': 'application/json',
      ...(cookie ? { Cookie: cookie } : {}),
      ...(init?.headers ?? {}),
    },
  });
  const text = await res.text();
  let body: unknown = text.slice(0, 300);
  try {
    body = JSON.parse(text);
  } catch {
    /* keep the raw text */
  }
  return { status: res.status, body };
}

function short(v: unknown): string {
  const s = typeof v === 'string' ? v : JSON.stringify(v);
  return (s ?? 'null').slice(0, 200);
}

// A throwing `never` so callers' definite-assignment analysis still works
// after a try/catch that can only exit via this function.
function fail(detail: string): never {
  throw new Error(`e2e pre-suite health check FAILED — backend rig unreachable: ${detail}`);
}

export default async function globalSetup(): Promise<void> {
  const user = `e2ehealth_${Date.now().toString(36)}`;
  const pass = 'e2e-health-pass';

  let reg: ApiResult;
  try {
    reg = await api('/api/auth/register', {
      method: 'POST',
      body: JSON.stringify({ username: user, password: pass }),
    });
  } catch (err) {
    fail(`POST /api/auth/register threw (${err instanceof Error ? err.message : err})`);
  }
  if (reg.status !== 200) fail(`POST /api/auth/register -> ${reg.status} ${short(reg.body)}`);

  let login: Response;
  try {
    login = await fetch(`${BASE}/api/auth/login`, {
      method: 'POST',
      signal: AbortSignal.timeout(REQ_TIMEOUT_MS),
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: user, password: pass }),
    });
  } catch (err) {
    fail(`POST /api/auth/login threw (${err instanceof Error ? err.message : err})`);
  }
  if (!login.ok) fail(`POST /api/auth/login -> ${login.status}`);
  const match = (login.headers.get('set-cookie') ?? '').match(/hr_session=([^;]+)/);
  if (!match) fail('login response carried no hr_session cookie');
  const cookie = `hr_session=${match[1]}`;

  let created: ApiResult;
  try {
    created = await api('/api/sessions', { method: 'POST', body: JSON.stringify({ seed: 1 }) }, cookie);
  } catch (err) {
    fail(`POST /api/sessions threw (${err instanceof Error ? err.message : err})`);
  }
  if (created.status !== 200) fail(`POST /api/sessions -> ${created.status} ${short(created.body)}`);
  const sessionId = (created.body as { sessionId?: unknown } | null)?.sessionId;
  if (typeof sessionId !== 'string' || !sessionId) {
    fail(`POST /api/sessions -> 200 but no sessionId (${short(created.body)})`);
  }

  let setup: ApiResult;
  try {
    setup = await api(
      `/api/sessions/${sessionId}/debug-setup`,
      { method: 'POST', body: JSON.stringify({ hand: ['Gold'] }) },
      cookie,
    );
  } catch (err) {
    fail(`POST debug-setup threw (${err instanceof Error ? err.message : err})`);
  }
  if (setup.status !== 200) {
    fail(`POST debug-setup -> ${setup.status} ${short(setup.body)} (is HR_DEBUG_SETUP=1 enabled on the backend?)`);
  }
}
