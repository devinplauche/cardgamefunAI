# Browser ML Lab Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a polished browser-based Hero Realms lab that can run local ML/bot decisions, step games interactively, and let us inspect every chosen action in the browser.

**Architecture:** Keep the existing Python rules engine as the source of truth, add a tiny local HTTP API that owns game sessions and bot decisions, and build a React + Vite client that renders the board, controls, and decision log. The UI will be clean and minimal, with explicit manual controls for play, expend, combat target selection, buy, and end-turn, while the backend exposes a small JSON contract for state snapshots and actions.

**Tech Stack:** Python stdlib HTTP server, React 18, Vite, TypeScript, vanilla CSS modules or a single stylesheet, Playwright-style browser verification via the Codex browser plugin.

---

### Task 1: Create the backend session API

**Files:**
- Create: `web/backend.py`
- Create: `web/session.py`
- Modify: `hero_engine.py`
- Modify: `hero_ai.py`

- [ ] **Step 1: Write the failing test**

```python
def test_session_can_create_and_serialize_state():
    session = create_session(seed=7)
    state = session.get_state()
    assert state["turn_number"] == 1
    assert state["active_player"]["name"] in {"Player", "Agent"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/web/test_session_api.py::test_session_can_create_and_serialize_state -v`
Expected: fail because `web.session` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
def create_session(seed: int | None = None) -> GameSession:
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/web/test_session_api.py::test_session_can_create_and_serialize_state -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/backend.py web/session.py hero_engine.py hero_ai.py tests/web/test_session_api.py
git commit -m "feat: add browser game session api"
```

### Task 2: Add deterministic bot decision support

**Files:**
- Create: `web/bot.py`
- Modify: `hero_engine.py`
- Modify: `hero_ai.py`
- Create: `tests/web/test_bot.py`

- [ ] **Step 1: Write the failing test**

```python
def test_bot_returns_legal_action():
    session = create_session(seed=3)
    action = choose_bot_action(session.get_state())
    assert action["type"] in {"play", "buy", "expend", "combat", "end_turn"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/web/test_bot.py::test_bot_returns_legal_action -v`
Expected: fail because `web.bot` is missing.

- [ ] **Step 3: Write minimal implementation**

```python
def choose_bot_action(state: dict, budget_ms: int = 50) -> dict:
    ...
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/web/test_bot.py::test_bot_returns_legal_action -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/bot.py tests/web/test_bot.py hero_engine.py hero_ai.py
git commit -m "feat: add bot decision interface"
```

### Task 3: Scaffold the React browser client

**Files:**
- Create: `web/package.json`
- Create: `web/vite.config.ts`
- Create: `web/index.html`
- Create: `web/src/main.tsx`
- Create: `web/src/App.tsx`
- Create: `web/src/styles.css`
- Create: `web/src/api.ts`
- Create: `web/src/types.ts`

- [ ] **Step 1: Write the failing test**

```ts
// smoke check: main app renders the title and action bar
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run build`
Expected: fail because the frontend project does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```tsx
export function App() {
  return <main>Hero Realms ML Lab</main>;
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run build`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/package.json web/vite.config.ts web/index.html web/src
git commit -m "feat: scaffold browser client"
```

### Task 4: Build the polished game surface

**Files:**
- Modify: `web/src/App.tsx`
- Modify: `web/src/styles.css`
- Modify: `web/src/api.ts`
- Modify: `web/src/types.ts`

- [ ] **Step 1: Write the failing test**

```ts
// browser QA: board should show state, controls, and log sections
```

- [ ] **Step 2: Run test to verify it fails**

Run: `npm run build`
Expected: build may pass before polish, but browser QA will expose missing interactions.

- [ ] **Step 3: Write minimal implementation**

```tsx
// compose board, hand, market, selection rail, and decision log
```

- [ ] **Step 4: Run test to verify it passes**

Run: `npm run build`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/App.tsx web/src/styles.css web/src/api.ts web/src/types.ts
git commit -m "feat: build polished browser game surface"
```

### Task 5: Wire up browser verification

**Files:**
- Create: `tests/web/test_browser_smoke.py`
- Modify: `web/backend.py`

- [ ] **Step 1: Write the failing test**

```python
def test_health_endpoint():
    response = requests.get("http://127.0.0.1:8000/api/health")
    assert response.json()["ok"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/web/test_browser_smoke.py::test_health_endpoint -v`
Expected: fail until the backend is running.

- [ ] **Step 3: Write minimal implementation**

```python
if path == "/api/health":
    self._json({"ok": True})
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/web/test_browser_smoke.py::test_health_endpoint -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/web/test_browser_smoke.py web/backend.py
git commit -m "test: add browser smoke coverage"
```
