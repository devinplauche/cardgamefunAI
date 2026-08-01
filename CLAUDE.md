# cardgamefunAI — working notes

Hero Realms engine + MCTS bot + RL training stack. `BASELINE.md` is the full
experimental record (1500+ lines, chronological). This file is the part you need
*before* running anything, so it does not get rediscovered every session.

## Read this before measuring anything

This project's history is mostly **false positives that did not survive a second
seed block**. Six candidate wins died that way in a single session. The cause is
not bad luck; it is that win rate here carries several independent noise floors
that are larger than the effects being chased.

**Measured noise floors — do not re-derive these:**

| source | size | notes |
| --- | --- | --- |
| seed block | **~10pp** | the same *fully deterministic* heuristic scores 45.6% / 39.4% / 51.0% on blocks 1000+ / 60000+ / 300000+ |
| wall-clock jitter | **~4-5pp** | a byte-identical MCTS config re-run scores up to 5.3pp apart; 18% of games change outcome |
| RL training seed | **~6pp** | two seeds of one config differ 3.7-8.4pp held out |

Consequences:

- **Never compare absolute win rates across seed blocks.** A single block cannot
  pin an absolute better than ~±10pp. The stable quantity is a *paired delta
  within one block*.
- **Always include a null arm** — a byte-identical duplicate of the control.
  Duplicate arms have exposed a noise floor four times when deliberate controls
  found nothing. It is the cheapest control available.
- **Prefer `--iterations` over `--budget`** whenever the question is about search
  *mechanism* rather than shipped wall-clock performance. Fixed simulations make
  the search deterministic given the seed: the null replicate goes from 72
  discordant games to exactly **0**, and detectable effects from ~5pp to ~1pp.
  Check first that the change does not alter simulation count (report sims/decision).
- **Use paired McNemar on discordant games**, not marginal win rates. Seed
  difficulty cancels exactly.
- **Sweep on one block, confirm on a disjoint one.** A tuning-block lead that
  shrinks on held-out is the signature that has cost this project six wins.
- **Never run a wall-clock benchmark concurrently with anything else.** CPU
  contention starves the search and corrupts it. Step-count-based RL runs are safe
  to parallelise; MCTS benchmarks are not.

**Win rate is a poor instrument here.** It needs thousands of games to see 3pp.
Decision-level regret (score every option in ~30 sampled positions with a heavy
oracle) sees the same thing in about a minute, and localises *which* decisions
are lost. Prefer it for diagnosis; use win rate only for final acceptance.

## What has been ruled out (do not retry without a new mechanism)

- **Domain knowledge in the rollout policy.** Three attempts, three negatives
  (situational buy scoring, routed buy policy, game-phase term). A greedier,
  more informed default policy narrows the simulated outcome distribution and
  biases the value estimates more than the better play gains.
- **True ISMCTS** at 60ms wall clock — builds a real tree, changes nothing.
- **RL observation repair** (faction, ally text, sacrifice keys, opponent deck)
  and **potential-based reward shaping** — both null held out.
- **Opponent specialists** — training against one fixed profile beats that
  profile no better than a generalist (+1.1pp ± 1.6). The plateau is not a
  generalization tax.
- **More search compute** — saturates by ~240ms; 960ms buys nothing.
- **Rollout horizon** 16 vs 24 vs 32 — null over 2800 games and four blocks.
- **Banning Fire Gem** — flips 20-30% of games, nets zero.

## Current defaults and how well each is evidenced

| knob | value | evidence |
| --- | --- | --- |
| `ROOT_SAMPLING_MODE` | `paired` | ISMCTS tested and rejected |
| `MCTS_OVERRIDE_MARGIN` | `0.10` | **strong** — inverted U with peak here; heuristic-only loses 22-66 paired |
| `ROLLOUT_TURNS` | `16` | confirmed null vs 24/32 at fixed iterations |
| `BUY_POLICY` | `static` | situational lost three A/Bs |
| `GAME_PHASE_WEIGHT` | `0.0` | monotone worse as tilt increases |
| `DENY_BOARD_WEIGHT` | `0.0` | **never confirmed**; aimed at a blind spot that pruning already closed |

The override gate is the one mechanism with a confirmed win behind it. Ungated,
search wants to overrule the heuristic on **41%** of decisions; the gate admits
**9%**, and that is the optimum. The other ~32% are deviations search believes in
that cost win rate.

## Stale information warning

**Everything in `BASELINE.md` predating the Ruby fix describes a different game.**
`RUBY` was encoded as a 1-health action instead of a 2-gold treasure, so starting
decks produced 7 gold per cycle instead of 9. Correcting it moved the
MCTS-minus-heuristic delta from **+11pp to ~5pp** — more than half of search's
apparent advantage was an artifact. Game length dropped 26.1 → 23.3 turns.

Also stale: `BASELINE.md` lists the champion-denial blind spot as the top open
problem. It is **already fixed** — `_combat_search_actions` prunes face away when
a champion is killable, so the snipe rate is 100% across all six champions where
0-35% is recorded.

## Gotchas that have produced confidently wrong numbers

- **`market.fire_gems_remaining = 0` does not ban Fire Gem.** It leaves 16
  phantom cards in `_inventory_counts`, so `determinize_for_bot` raises and every
  search **fails closed to the heuristic**. Remove them from `_full_inventory`
  too, and assert search still runs.
- **`choose_bot_action` returns `algorithm: "mcts"` with `iterations: 0`** on that
  fail-closed path, and `algorithm: "heuristic"` with `iterations: 1` for
  auto-resolved phases. Counting "searched decisions" needs both filters.
- **`tools/audit_cards.py` only covers `data/hero_realms_cards.json`.** The five
  starting/Fire Gem cards are hardcoded in `hero_engine.py` and outside its scope
  — see `tests/test_starting_cards.py`.
- The engine is a reimplementation. Card data has been wrong before; verify
  against the printed card, not against the engine.

## Layout

- `hero_engine.py` — rules. `web/session.py` — game state, cloning, determinization.
- `web/bot.py` — MCTS. `hero_mcts_bench.py` — the benchmark (bot seat = second player).
- `hero_rl_env_v2/v3/v4.py` — RL envs (v4 has the repaired observation).
- `hero_*_ab.py` — A/B harnesses; all use paired McNemar and take `--iterations`.
- Tests: `python -m pytest -q` (310 passing).
