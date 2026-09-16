import { defineConfig } from '@playwright/test';

// End-to-end suite for the Hero Realms web app.
//
// Runs against a deployed site (default: production). These tests drive the
// real UI against real Cloud Run traffic, so they run ONLY on deployments
// (see the `e2e` job in .github/workflows/ci.yml), never per-push and never
// on a schedule.
//
// The per-card rig works by intercepting the frontend's POST /api/sessions
// call and fulfilling it with a session whose hand was dealt by the
// backend's debug-setup endpoint (guarded by HR_DEBUG_SETUP=1, enabled only
// for the test window). No product code changes were needed for the rig.
//
//   E2E_BASE_URL=https://hero-realms-yokyhjajxq-uc.a.run.app npx playwright test
//
// The sandbox reaches the internet through an egress proxy (plain env vars,
// which Chromium ignores). Read it here so the browser can get out; on CI
// there is no proxy env and this stays undefined (direct connection).
//
// Sandbox quirk: this machine's Chromium cannot speak to the egress proxy
// directly (all external TCP returns ERR_EMPTY_RESPONSE), so for local runs
// start /tmp/fwd-proxy.mjs (a loopback forward proxy that relays through the
// egress proxy) and set E2E_VIA_FORWARDER=1. The proxy also MITMs TLS, hence
// ignoreHTTPSErrors below - harmless on CI where there is no proxy.
// The sandbox also can't use Playwright's own browser downloader, so local
// runs additionally set E2E_LOCAL_BROWSER=1 to use the manually fetched
// binary (see launchOptions below); CI omits it and Playwright launches the
// browser it installed itself.
function egressProxy() {
  if (process.env.E2E_VIA_FORWARDER === '1') {
    return { server: 'http://127.0.0.1:3129' };
  }
  const raw = process.env.HTTPS_PROXY || process.env.https_proxy;
  if (!raw) return undefined;
  try {
    const url = new URL(raw);
    return {
      server: `${url.protocol}//${url.host}`,
      username: decodeURIComponent(url.username) || undefined,
      password: decodeURIComponent(url.password) || undefined,
      bypass: process.env.NO_PROXY || process.env.no_proxy || undefined,
    };
  } catch {
    return undefined;
  }
}

export default defineConfig({
  testDir: './tests/e2e',
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  expect: { timeout: 10_000 },
  reporter: [['list'], ['json', { outputFile: 'tests/e2e/results.json' }]],
  use: {
    baseURL: process.env.E2E_BASE_URL || 'https://hero-realms-yokyhjajxq-uc.a.run.app',
    proxy: egressProxy(),
    // The sandbox egress proxy MITMs TLS; CI has no proxy so this is a no-op there.
    ignoreHTTPSErrors: true,
    // Browser binary: on CI, let Playwright launch the browser it installed
    // itself - its registry knows the exact extracted layout (the
    // Chrome-for-Testing builds moved it from chrome-linux/ to
    // chrome-linux64/, which a hardcoded path gets wrong). The sandbox
    // can't use Playwright's own downloader, so local runs set
    // E2E_LOCAL_BROWSER=1 to use the manually fetched binary instead.
    launchOptions: {
      ...(process.env.E2E_LOCAL_BROWSER === '1'
        ? {
            executablePath: `${process.env.HOME}/.cache/ms-playwright/chromium-1243/chrome-linux/chrome`,
          }
        : {}),
      args: ['--no-sandbox'],
    },
    // Devin plays on iPhone: run the suite at a mobile-ish viewport with a
    // mobile user agent and touch enabled (Chromium only; the iPhone device
    // descriptor would pull in WebKit).
    viewport: { width: 390, height: 844 },
    userAgent:
      'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
    hasTouch: true,
    isMobile: true,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
});
