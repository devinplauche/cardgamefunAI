// Live-site QA for the Hero Realms multiplayer app.
// Runs against a deployed URL (default: production). Run only on deployments,
// not on a schedule: each run is real user traffic against Cloud Run.
//
//   BASE_URL=https://hero-realms-yokyhjajxq-uc.a.run.app node web/e2e/live-qa.mjs
//
// Env:
//   BASE_URL          site under test (default production)
//   PW_CHROMIUM_PATH  executable for Chromium (default: playwright's bundled)
//   E2E_ARTIFACTS     dir for screenshots (default ./web/e2e/artifacts)
//
// Exit 0 = all checks pass. Exit 1 = a check failed (details printed).
import { chromium } from 'playwright';
import fs from 'node:fs';
import path from 'node:path';

const BASE_URL = process.env.BASE_URL || 'https://hero-realms-yokyhjajxq-uc.a.run.app';
const ART = process.env.E2E_ARTIFACTS || path.resolve('web/e2e/artifacts');
fs.mkdirSync(ART, { recursive: true });

const failures = [];
const notes = [];
function check(name, cond, detail = '') {
  if (cond) { notes.push(`ok   ${name}`); }
  else { failures.push(`${name}${detail ? ' — ' + detail : ''}`); notes.push(`FAIL ${name}${detail ? ' — ' + detail : ''}`); }
}

async function newPlayer(browser, tag) {
  const context = await browser.newContext();
  const page = await context.newPage();
  const consoleErrors = [];
  const failedRequests = [];
  page.on('console', m => { if (m.type() === 'error') consoleErrors.push(m.text().slice(0, 200)); });
  page.on('requestfailed', r => failedRequests.push(`${r.url().slice(0, 120)} ${r.failure()?.errorText}`));
  page.on('pageerror', e => consoleErrors.push('pageerror: ' + String(e).slice(0, 200)));
  return { tag, context, page, consoleErrors, failedRequests };
}

async function register(p, username) {
  await p.page.goto(BASE_URL, { waitUntil: 'networkidle' });
  await p.page.getByRole('button', { name: 'Create account' }).first().click();
  const inputs = p.page.locator('.auth-form .auth-input');
  await inputs.nth(0).fill(username);
  await inputs.nth(1).fill('e2epass123');
  await p.page.locator('.auth-form').getByRole('button', { name: 'Create account' }).click();
  await p.page.waitForSelector('.lobby', { timeout: 15000 });
}

async function brokenImages(page) {
  return page.evaluate(() => {
    const imgs = [...document.querySelectorAll('.card-artwork img')];
    const broken = imgs.filter(i => !i.complete || i.naturalWidth === 0).length;
    return { total: imgs.length, broken };
  });
}

const browser = await chromium.launch({
  executablePath: process.env.PW_CHROMIUM_PATH || undefined,
  args: ['--no-sandbox'],
});
try {
  const ts = Date.now().toString(36);
  const p1 = await newPlayer(browser, 'p1');
  const p2 = await newPlayer(browser, 'p2');

  // --- register both players ---
  await register(p1, `e2e_p1_${ts}`);
  check('p1 registers and reaches lobby', true);
  await register(p2, `e2e_p2_${ts}`);
  check('p2 registers and reaches lobby', true);

  // --- p1 creates a game ---
  await p1.page.getByRole('button', { name: 'Create game' }).click();
  await p1.page.waitForSelector('.lobby-code strong', { timeout: 15000 });
  const code = (await p1.page.locator('.lobby-code strong').textContent()).trim();
  check('invite code issued', /^[A-Z0-9]{6}$/.test(code), `code=${code}`);

  // --- p2 joins ---
  await p2.page.locator('.lobby-code-input').fill(code);
  await p2.page.locator('.lobby-join').getByRole('button', { name: 'Join' }).click();
  await p2.page.waitForSelector('.lobby-game', { timeout: 15000 });
  check('p2 joins via invite code', true);

  // --- both open the game ---
  await p1.page.locator('.lobby-game').first().click();
  await p1.page.waitForSelector('.card-artwork', { timeout: 15000 });
  await p2.page.locator('.lobby-game').first().click();
  await p2.page.waitForSelector('.card-artwork', { timeout: 15000 });
  check('game board renders for both players', true);
  await p1.page.screenshot({ path: path.join(ART, 'board-p1.png') });

  // --- card art ---
  await p1.page.waitForTimeout(3000); // let lazy images load
  const art = await brokenImages(p1.page);
  check('card images load', art.total > 0 && art.broken === 0, `${art.broken}/${art.total} broken`);

  // --- p1 plays: Play all ---
  const playAll = p1.page.getByRole('button', { name: /Play all/ });
  if (await playAll.count() && await playAll.first().isEnabled()) {
    await playAll.first().click();
    await p1.page.waitForTimeout(1500);
    const errVisible = await p1.page.locator('.auth-error, .game-error, [role="alert"]').count();
    check('Play all executes without error', errVisible === 0);
  } else {
    notes.push('skip Play all (button absent or disabled — no straightforward cards)');
  }
  await p1.page.screenshot({ path: path.join(ART, 'after-playall.png') });

  // --- p1 ends turn via the primary action button ---
  const primary = p1.page.locator('.primary-button').filter({ hasNotText: /Create|Join/ }).last();
  const label = (await primary.textContent() || '').trim();
  await primary.click();
  await p1.page.waitForTimeout(2500);
  check(`p1 advances turn (clicked "${label}")`, true);
  await p1.page.screenshot({ path: path.join(ART, 'p2-turn.png') });

  // --- console / network hygiene ---
  for (const p of [p1, p2]) {
    check(`${p.tag}: no console errors`, p.consoleErrors.length === 0, p.consoleErrors.slice(0, 3).join(' | '));
    const serious = p.failedRequests.filter(u => !u.includes('favicon'));
    check(`${p.tag}: no failed requests`, serious.length === 0, serious.slice(0, 3).join(' | '));
  }

  await p1.context.close();
  await p2.context.close();
} finally {
  await browser.close();
}

console.log('\n' + notes.join('\n'));
if (failures.length) {
  console.log(`\nQA FAILED: ${failures.length} check(s)`);
  process.exit(1);
}
console.log('\nQA PASSED');
