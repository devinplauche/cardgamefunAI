import { test, expect, type Page, type Route } from '@playwright/test';

// Juice pack: rewarding-moment banners, faction combos, damage floaters.
// The rig: page.route intercepts the app's POST /api/sessions and fulfills
// it with a debug-rigged session, so each test starts mid-game.
const BASE = process.env.E2E_BASE_URL || 'https://hero-realms-yokyhjajxq-uc.a.run.app';
const USER = `e2ejuice_${Date.now().toString(36)}`;
const PASS = 'e2e-juice-pass';

async function api<T>(p: string, init?: RequestInit, cookie?: string): Promise<{ status: number; body: T }> {
  const res = await fetch(`${BASE}${p}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(cookie ? { Cookie: cookie } : {}), ...(init?.headers ?? {}) },
  });
  const body = (await res.json().catch(() => null)) as T;
  return { status: res.status, body };
}

test.beforeAll(async () => {
  const { status, body } = await api<any>('/api/auth/register', {
    method: 'POST',
    body: JSON.stringify({ username: USER, password: PASS }),
  });
  if (status !== 200) throw new Error(`register failed: ${status} ${JSON.stringify(body)}`);
});

async function plantAuthCookie(page: Page) {
  const res = await fetch(`${BASE}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: USER, password: PASS }),
  });
  if (!res.ok) throw new Error(`login failed: ${res.status}`);
  const match = (res.headers.get('set-cookie') ?? '').match(/hr_session=([^;]+)/);
  if (!match) throw new Error('no hr_session cookie in login response');
  const url = new URL(BASE);
  await page.context().addCookies([
    { name: 'hr_session', value: match[1], domain: url.hostname, path: '/', httpOnly: true, secure: url.protocol === 'https:', sameSite: 'Lax' },
  ]);
  return match[1];
}

async function rigged(cookie: string, setup: Record<string, unknown>) {
  const created = await api<any>('/api/sessions', { method: 'POST', body: JSON.stringify({ seed: 777 }) }, `hr_session=${cookie}`);
  const sessionId = created.body.sessionId as string;
  const done = await api<any>(`/api/sessions/${sessionId}/debug-setup`, { method: 'POST', body: JSON.stringify(setup) }, `hr_session=${cookie}`);
  return done.body;
}

async function startRigged(page: Page, cookie: string, setup: Record<string, unknown>) {
  await page.route('**/api/sessions', async (route: Route) => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    const state = await rigged(cookie, setup);
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(state) });
  });
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: 'Vs Bot' }).click();
  await expect(page.locator('.game-table')).toBeVisible();
}

test('juice: faction combo, big buy, face damage', async ({ page }) => {
  const cookie = await plantAuthCookie(page);
  await startRigged(page, cookie, {
    hand: ['Taxation', 'Recruit'], gold: 10, combat: 8,
    market: ['Command', 'Taxation', 'Recruit', 'Spark', 'Fire Gem', 'Gold'],
  });

  // Play two Imperials -> combo banner + persistent badge.
  await page.locator('.hand-zone').getByRole('button', { name: 'Taxation', exact: true }).click();
  await page.waitForTimeout(300);
  await page.locator('.hand-zone').getByRole('button', { name: 'Recruit', exact: true }).click();
  await expect(page.locator('.juice-banner')).toContainText('Imperial synergy ×2');
  await expect(page.locator('.combo-badge')).toContainText('Imperial ×2');
  await expect(page.locator('.juice-banner')).toBeHidden({ timeout: 4000 });

  // Buy a 5-cost card -> big-buy fanfare.
  await page.locator('.market-row').getByRole('button', { name: /Command/ }).first().click();
  await expect(page.locator('.juice-banner')).toContainText('Command recruited');
  await expect(page.locator('.juice-banner')).toBeHidden({ timeout: 4000 });

  // Attack face -> floating damage number.
  await page.locator('.hp-wrap .hp-pill').click();
  await expect(page.locator('.floater')).toContainText('−8');
});

test('juice: destroying a champion celebrates', async ({ page }) => {
  const cookie = await plantAuthCookie(page);
  await startRigged(page, cookie, {
    hand: ['Gold'], gold: 0, combat: 6, opponentBoard: ['Myros, Guild Mage'],
  });
  await page.getByRole('button', { name: /Attack/ }).first().click();
  await expect(page.locator('.juice-banner')).toContainText('destroyed');
});
