// Per-card GUI suite: all 55 cards in data/hero_realms_cards.json.
//
// For each card the rig deals it (plus one Gold as fodder for discard /
// sacrifice choices) straight into the player's hand of a fresh vs-bot
// session, then the test drives the REAL UI: it taps the card, resolves any
// choice sheets the play triggers, and for champions taps the board champion
// and expends it. Generic assertions only - no card-specific rules
// expectations are encoded here (rulebook-vs-official-app behavior for ally
// abilities is still an open product decision).
//
// What each card asserts:
//   1. The card renders in hand with its art image loaded (no broken image,
//      no fallback glyph only).
//   2. Tapping the card plays it with no page JS errors / console errors.
//   3. The card leaves the hand (into play, the board, or wherever the
//      engine puts it).
//   4. Any "Discard a card" / "Sacrifice a card" choice sheet that appears is
//      resolvable, and any "Stun with ..." picker can pick a target.
//   5. Champions additionally: the played champion can be expended from the
//      board with no errors.
//
// The rig: page.route intercepts the app's POST /api/sessions and fulfills
// it with a session created + dealt via the backend's debug-setup endpoint
// (HR_DEBUG_SETUP=1). The rest of the session's API traffic goes to the real
// backend untouched.
import { test, expect, type Page, type Route } from '@playwright/test';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import path from 'node:path';

const WEB_DIR = path.dirname(fileURLToPath(import.meta.url)); // web/tests/e2e
const REPO_DIR = path.resolve(WEB_DIR, '..', '..', '..');
const CARDS: Array<{ name: string; type: string; faction: string }> = JSON.parse(
  readFileSync(path.join(REPO_DIR, 'data', 'hero_realms_cards.json'), 'utf8'),
).map((c: any) => ({ name: c.name, type: c.type, faction: c.faction as string }));

// Ally triggers only go live with another same-faction card in play, so the
// rig deals a faction partner (preferring an action, which needs no further
// driving) and the test plays it first. Fire Gem has no faction: no partner.
const PARTNER: Record<string, string | null> = {};
for (const card of CARDS) {
  if (!card.faction) { PARTNER[card.name] = null; continue; }
  const mate = CARDS.find((c) => c.faction === card.faction && c.name !== card.name && c.type === 'action')
    ?? CARDS.find((c) => c.faction === card.faction && c.name !== card.name);
  PARTNER[card.name] = mate ? mate.name : null;
}

const BASE = process.env.E2E_BASE_URL || 'https://hero-realms-yokyhjajxq-uc.a.run.app';
const USER = `e2ecards_${Date.now().toString(36)}`;
const PASS = 'e2e-cards-pass';

async function api<T>(p: string, init?: RequestInit, cookie?: string): Promise<{ status: number; body: T }> {
  // Fail fast: a hung backend must surface as an error now, not as a
  // 60s test timeout later.
  const res = await fetch(`${BASE}${p}`, {
    ...init,
    signal: AbortSignal.timeout(30_000),
    headers: { 'Content-Type': 'application/json', ...(cookie ? { Cookie: cookie } : {}), ...(init?.headers ?? {}) },
  });
  const body = (await res.json().catch(() => null)) as T;
  return { status: res.status, body };
}

test.beforeAll(async () => {
  // One throwaway account for the whole file; the cookie is planted in each
  // browser context so the app boots straight into the lobby.
  const { status, body } = await api<any>('/api/auth/register', {
    method: 'POST',
    body: JSON.stringify({ username: USER, password: PASS }),
  });
  if (status !== 200) throw new Error(`register failed: ${status} ${JSON.stringify(body)}`);
});

async function plantAuthCookie(page: Page) {
  // Log in through the API in Node, then hand the session cookie to the
  // browser context so the SPA boots authenticated.
  const res = await fetch(`${BASE}/api/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username: USER, password: PASS }),
  });
  if (!res.ok) throw new Error(`login failed: ${res.status}`);
  const setCookie = res.headers.get('set-cookie') ?? '';
  const match = setCookie.match(/hr_session=([^;]+)/);
  if (!match) throw new Error('no hr_session cookie in login response');
  const url = new URL(BASE);
  await page.context().addCookies([
    {
      name: 'hr_session',
      value: match[1],
      domain: url.hostname,
      path: '/',
      httpOnly: true,
      secure: url.protocol === 'https:',
      sameSite: 'Lax',
    },
  ]);
}

// Deal [card, faction partner, Gold] into the player's hand via the rig,
// returning the state payload used to fulfill the app's createSession call.
async function riggedSessionState(cardName: string): Promise<any> {
  const created = await api<any>('/api/sessions', {
    method: 'POST',
    body: JSON.stringify({ seed: 424242, algorithm: 'mcts', budgetMs: 60 }),
  });
  if (created.status !== 200) throw new Error(`create session failed: ${created.status}`);
  const sessionId = created.body.sessionId as string;
  const partner = PARTNER[cardName];
  const hand = partner ? [cardName, partner, 'Gold'] : [cardName, 'Gold'];
  const setup = await api<any>(`/api/sessions/${sessionId}/debug-setup`, {
    method: 'POST',
    body: JSON.stringify({ hand }),
  });
  if (setup.status !== 200) {
    throw new Error(`debug-setup failed for "${cardName}": ${setup.status} ${JSON.stringify(setup.body)}`);
  }
  return setup.body;
}

// Fail-fast rig handle: the route handler below runs detached from the
// test, so a throw inside it can't reach the test directly. The handler
// records the REAL rig error here (instead of swallowing it behind a
// generic 500), and the test rethrows it right after the session request
// resolves — no test ever runs against an un-rigged backend.
type Rig = { error: Error | null };

async function installRig(page: Page, cardName: string): Promise<Rig> {
  const rig: Rig = { error: null };
  await page.route('**/api/sessions', async (route: Route) => {
    if (route.request().method() !== 'POST') {
      await route.continue();
      return;
    }
    try {
      const state = await riggedSessionState(cardName);
      await route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(state) });
    } catch (err) {
      rig.error = err instanceof Error ? err : new Error(String(err));
      // Fulfill (don't hang) so the page's request resolves; the test
      // throws rig.error immediately instead of timing out on locators.
      await route.fulfill({
        status: 500,
        contentType: 'application/json',
        body: JSON.stringify({ error: rig.error.message }),
      });
    }
  });
  return rig;
}

type ConsoleIssue = string;

function watchConsole(page: Page): { issues: ConsoleIssue[] } {
  const issues: ConsoleIssue[] = [];
  page.on('console', (m) => {
    if (m.type() === 'error') issues.push(`console.error: ${m.text().slice(0, 300)}`);
  });
  page.on('pageerror', (e) => issues.push(`pageerror: ${String(e).slice(0, 300)}`));
  page.on('requestfailed', (r) => {
    const url = r.url();
    if (url.includes('/cards/')) issues.push(`art request failed: ${url.slice(-40)} ${r.failure()?.errorText}`);
  });
  return { issues };
}

// Click the first enabled action in the open action sheet whose title
// matches, then wait for the sheet to close.
async function resolveSheet(page: Page, title: string, preferNonDecline = false): Promise<boolean> {
  const sheet = page.getByRole('dialog', { name: title });
  if ((await sheet.count()) === 0) return false;
  const buttons = sheet.getByRole('button').filter({ hasNotText: /^cancel$/i });
  // The rig deals a Gold as fodder for exactly these sheets: spend it before
  // any other card, so a partner's setup play never discards or sacrifices
  // the card under test (e.g. Dark Reward's "sacrifice a card" or Elven
  // Gift's "discard a card" would otherwise burn it and the test would time
  // out waiting for it in hand).
  // Backend labels are "<Kind> <Card>" (e.g. "Sacrifice Gold",
  // "Discard Elven Curse"), so match the card name inside the label.
  let pick = buttons.filter({ hasText: /\bgold\b/i }).first();
  if ((await pick.count()) === 0) {
    pick = preferNonDecline
      ? buttons.filter({ hasNotText: /decline|keep everything|stop here/i }).first()
      : buttons.first();
  }
  if ((await pick.count()) === 0) return false;
  const pickedLabel = ((await pick.textContent()) ?? '').trim().replace(/\s+/g, ' ');
  await pick.click();
  // Multi-pick choices (Tyrannor's "up to two") reopen the same sheet
  // for the next pick instead of closing it; a single pick closes it.
  // Either way the picked option is gone once the click lands - the
  // settle loop re-resolves a reopened sheet.
  if (pickedLabel) {
    await expect(sheet.getByRole('button', { name: pickedLabel }))
      .toHaveCount(0, { timeout: 10_000 })
      .catch(() => {});
  }
  await page.waitForTimeout(400);
  return true;
}

// Ally abilities are user-triggered (official-app behavior): after playing,
// the UI offers a trigger per card with a live ally - a dedicated button on
// the played strip, an action in the champion sheet. The harness fires every
// offered trigger so the ally payload also runs through the UI with no
// errors. No-op when no trigger is offered.
async function triggerAllyIfOffered(page: Page) {
  for (let i = 0; i < 6; i++) {
    const btn = page.locator('button.played-chip-ally').first();
    if ((await btn.count()) === 0 || !(await btn.isEnabled())) break;
    const before = await page.locator('button.played-chip-ally').count();
    await btn.click();
    // Wait for the trigger to fire (a button goes away) or a picker to open,
    // instead of a fixed sleep that races the backend under load.
    await expect(async () => {
      const fired = (await page.locator('button.played-chip-ally').count()) < before;
      const picker = (await page.getByRole('dialog').count()) > 0;
      expect(fired || picker).toBe(true);
    }).toPass({ timeout: 15_000 });
    await settleOverlays(page);
  }
}

// Champion sheets carry the ally trigger as a "⚡ Ally: ..." action. Open
// the sheet for the board champion and fire it when present.
async function triggerChampionAllyIfOffered(page: Page, cardName: string) {
  const boardChamp = page.getByRole('button', { name: cardName, exact: true }).first();
  if ((await boardChamp.count()) === 0) return;
  await boardChamp.click();
  const sheet = page.getByRole('dialog', { name: cardName });
  if ((await sheet.count()) === 0) return;
  const allyAct = sheet.getByRole('button', { name: /^⚡ Ally/ }).first();
  if ((await allyAct.count()) > 0 && (await allyAct.isEnabled())) {
    await allyAct.click();
    await page.waitForTimeout(600);
    await settleOverlays(page);
  } else {
    await page.keyboard.press('Escape');
  }
}

// After playing a card, resolve whatever the engine throws at us: choice
// sheets (discard/sacrifice/recycle/reanimate) and the stun picker. Loops
// because resolving one sheet can reveal another.
async function settleOverlays(page: Page, expectLateSheet = false) {
  // A choice sheet can open a beat AFTER the played card leaves the hand
  // (the payload can land in a separate render), so after a play we keep
  // polling for late-opening sheets instead of exiting on the first quiet
  // check. Without this, the sheet opens after we've looked, blocks the
  // next tap, and the test times out on a 60s click.
  const deadline = Date.now() + 12_000;
  let lastChange = Date.now();
  for (;;) {
    let acted = false;
    if (await resolveSheet(page, 'Discard a card')) acted = true;
    else if (await resolveSheet(page, 'Sacrifice a card', true)) acted = true;
    else if (await resolveSheet(page, 'Recycle a card', true)) acted = true;
    else if (await resolveSheet(page, 'Reanimate a champion')) acted = true;
    const stun = page.getByRole('dialog', { name: /^Stun with / });
    if ((await stun.count()) > 0) {
      await stun.getByRole('button').first().click();
      await expect(stun).toHaveCount(0, { timeout: 10_000 });
      acted = true;
    }
    if (acted) {
      lastChange = Date.now();
      await page.waitForTimeout(400);
      continue;
    }
    // Nothing open. If a late sheet is expected and we haven't been quiet
    // long, keep watching; otherwise we're settled.
    if (expectLateSheet && Date.now() - lastChange < 2000 && Date.now() < deadline) {
      await page.waitForTimeout(250);
      continue;
    }
    break;
  }
}

async function handCardArtOk(page: Page, cardName: string): Promise<{ ok: boolean; detail: string }> {
  // Art images are lazy-loaded: wait for the img to finish before judging.
  try {
    await page.waitForFunction(
      (name) => {
        const el = document.querySelector(`.hand-zone [aria-label="${CSS.escape(name)}"]`);
        const img = el?.querySelector('.card-artwork img') as HTMLImageElement | null;
        return !!img && img.complete;
      },
      cardName,
      { timeout: 10_000 },
    );
  } catch {
    // fall through to the diagnostic read below
  }
  return page.evaluate((name) => {
    const el = document.querySelector(`.hand-zone [aria-label="${CSS.escape(name)}"]`);
    if (!el) return { ok: false, detail: 'card not found in hand' };
    const img = el.querySelector('.card-artwork img') as HTMLImageElement | null;
    if (!img) return { ok: false, detail: 'no art img rendered (fallback glyph only)' };
    if (!img.complete || img.naturalWidth === 0)
      return { ok: false, detail: `art img broken: ${img.currentSrc.split('/').pop()}` };
    return { ok: true, detail: `art ok: ${img.currentSrc.split('/').pop()}` };
  }, cardName);
}

for (const card of CARDS) {
  test(`${card.name} — GUI smoke`, async ({ page }) => {
    const { issues } = watchConsole(page);
    await plantAuthCookie(page);
    const rig = await installRig(page, card.name);

    await page.goto(BASE, { waitUntil: 'domcontentloaded' });
    // Wait for the rigged session request BEFORE clicking: waitForResponse
    // only sees responses that arrive after it starts listening.
    const sessionResp = page.waitForResponse(
      (r) => r.url().includes('/api/sessions') && r.request().method() === 'POST',
      { timeout: 30_000 },
    );
    // Lobby -> Vs Bot tab. The bot game auto-starts a match, which our
    // route interception fulfills with the rigged session.
    await page.getByRole('button', { name: 'Vs Bot' }).click();
    await sessionResp.catch(() => {});
    // Fail fast with the REAL rig error (e.g. "debug-setup failed: ...")
    // instead of burning 20s timeouts on the card locators below.
    if (rig.error) throw rig.error;

    const handCard = page.locator('.hand-zone').getByRole('button', { name: card.name, exact: true });
    await expect(handCard, `card "${card.name}" dealt to hand`).toBeVisible({ timeout: 20_000 });

    // 1. Art loads.
    const art = await handCardArtOk(page, card.name);
    expect(art.ok, `art: ${art.detail}`).toBe(true);

    // 2. Play the faction partner first so the card's ally trigger goes live
    // (allies need another same-faction card in play). Then tap the card.
    const partner = PARTNER[card.name];
    if (partner) {
      const partnerCard = page.locator('.hand-zone').getByRole('button', { name: partner, exact: true });
      await expect(partnerCard, `partner "${partner}" dealt to hand`).toBeVisible({ timeout: 10_000 });
      await partnerCard.click();
      // Wait for the play to land (the card leaves the hand) instead of a
      // fixed sleep: under load the backend can take longer than any sleep.
      // A choice sheet can still open a beat after the card is gone, so
      // settleOverlays keeps watching for late sheets (expectLateSheet).
      await expect(partnerCard, `partner "${partner}" played`).toHaveCount(0, { timeout: 15_000 });
      await settleOverlays(page, true);
      await triggerAllyIfOffered(page);
    }
    await handCard.click();
    await expect(handCard, `"${card.name}" played`).toHaveCount(0, { timeout: 15_000 });
    await settleOverlays(page, true);
    // Ally payloads never auto-fire: trigger when the UI offers it.
    await triggerAllyIfOffered(page);

    if (card.type === 'champion') {
      // 4. Champions: tap the board champion and expend it. Champions whose
      // expend only adds gold/combat expend themselves on play, so the button
      // is then spent (disabled) - that is the expected state, not a failure.
      const boardChamp = page.getByRole('button', { name: card.name, exact: true }).first();
      await expect(boardChamp, `champion "${card.name}" on board`).toBeVisible({ timeout: 10_000 });
      await boardChamp.click();
      const sheet = page.getByRole('dialog', { name: card.name });
      await expect(sheet, 'champion action sheet').toBeVisible({ timeout: 10_000 });
      const expend = sheet.getByRole('button', { name: /^Expend/ }).first();
      await expect(expend, 'expend action').toBeVisible({ timeout: 10_000 });
      if (await expend.isEnabled()) {
        await expend.click();
        // Wait for the expend to land (the sheet closes; a choice sheet may
        // open in its place) instead of a fixed sleep that races the backend.
        await expect(sheet, 'expend resolved').toHaveCount(0, { timeout: 15_000 });
        await settleOverlays(page);
      } else {
        // Disabled means already spent via auto-expend: nothing left to do,
        // but the sheet is still open - dismiss it before moving on.
        await page.keyboard.press('Escape');
        await expect(sheet, 'champion action sheet closed').toHaveCount(0, { timeout: 10_000 });
      }
      await triggerAllyIfOffered(page);
      // Champions can also carry an ally trigger on their own sheet.
      await triggerChampionAllyIfOffered(page, card.name);
    }

    // 5. No JS errors anywhere in the flow.
    expect(issues, `JS/network issues: ${issues.join(' | ')}`).toEqual([]);
  });
}
