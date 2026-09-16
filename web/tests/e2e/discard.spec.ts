import { test, expect, type Page, type Route } from '@playwright/test';

const BASE = process.env.E2E_BASE_URL || 'https://hero-realms-yokyhjajxq-uc.a.run.app';
const USER = `e2ediscard_${Date.now().toString(36)}`;
const PASS = 'e2e-discard-pass';

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

async function riggedWithDiscards(cookie: string) {
  const created = await api<any>('/api/sessions', {
    method: 'POST',
    body: JSON.stringify({ seed: 424242 }),
  }, `hr_session=${cookie}`);
  const sessionId = created.body.sessionId as string;
  await api(`/api/sessions/${sessionId}/debug-setup`, {
    method: 'POST',
    body: JSON.stringify({ hand: ['Gold'], discard: ['Spark', 'Elven Curse'] }),
  }, `hr_session=${cookie}`);
  const setup = await api<any>(`/api/sessions/${sessionId}/debug-setup`, {
    method: 'POST',
    body: JSON.stringify({ side: 'bot', discard: ['Orc Grunt'] }),
  }, `hr_session=${cookie}`);
  return setup.body;
}

test('discard piles viewable for both seats', async ({ page }) => {
  const cookie = await plantAuthCookie(page);
  await page.route('**/api/sessions', async (route: Route) => {
    if (route.request().method() !== 'POST') { await route.continue(); return; }
    const state = await riggedWithDiscards(cookie);
    await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(state) });
  });
  await page.goto(BASE, { waitUntil: 'domcontentloaded' });
  await page.getByRole('button', { name: 'Vs Bot' }).click();

  // Your pile.
  await page.getByRole('button', { name: /View your discard pile/ }).click();
  const sheet = page.getByRole('dialog', { name: /Your discard pile/ });
  await expect(sheet).toBeVisible({ timeout: 10_000 });
  await expect(sheet.getByRole('button', { name: /Inspect Spark/ })).toBeVisible();
  await expect(sheet.getByRole('button', { name: /Inspect Elven Curse/ })).toBeVisible();
  // Tapping a row inspects the card on top of the sheet.
  await sheet.getByRole('button', { name: /Inspect Spark/ }).click();
  await expect(page.getByRole('dialog', { name: 'Spark' })).toBeVisible({ timeout: 10_000 });
  await page.keyboard.press('Escape');
  await page.keyboard.press('Escape');
  await expect(sheet).toHaveCount(0, { timeout: 10_000 });

  // Opponent's pile.
  await page.getByRole('button', { name: /discard pile \(1 cards?\)/ }).first().click();
  const foeSheet = page.getByRole('dialog', { name: /discard pile/ });
  await expect(foeSheet).toBeVisible({ timeout: 10_000 });
  await expect(foeSheet.getByRole('button', { name: /Inspect Orc Grunt/ })).toBeVisible();
  await page.keyboard.press('Escape');
  await expect(foeSheet).toHaveCount(0, { timeout: 10_000 });
});
