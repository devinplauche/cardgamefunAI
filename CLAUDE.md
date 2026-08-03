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
- **True ISMCTS at 60ms wall clock** — negative, but *not* because the tree is
  useless. See the open thread below; this one is mis-stated if you shorten it.
- **RL observation repair** (faction, ally text, sacrifice keys, opponent deck)
  and **potential-based reward shaping** — both null held out.
- **Opponent specialists** — training against one fixed profile beats that
  profile no better than a generalist (+1.1pp ± 1.6). The plateau is not a
  generalization tax.
- **More search compute** — saturates by ~240ms; 960ms buys nothing.
- **Rollout horizon** 16 vs 24 vs 32 — null over 2800 games and four blocks.
- **Banning Fire Gem** — flips 20-30% of games, nets zero.

## The one open thread worth pulling

**ISMCTS was never fairly tested. Whether the tree actually helps is unresolved.**

Measured two ways, and they disagree in a way that is informative rather than
contradictory:

| protocol | ISMCTS d2 vs paired |
| --- | --- |
| 60ms wall clock | −2.5pp tuning, −2.5pp held out |
| fixed 40 simulations | **+4.8pp tuning, +1.8pp held out** (pooled +26/230 discordant, p=0.099) |

The sign flips because at a fixed wall clock ISMCTS runs fewer simulations than
paired mode for the same time, so it was being judged on a rigged comparison —
and against a ~4pp jitter floor that was not yet known. Give both the same
simulation count and the tree is positive on both blocks against a null of
exactly 0/0.

Not significant (p=0.099, and the effect decayed +19 → +7 held out, which is the
pattern that has been wrong six times). But it held *direction* on the disjoint
block, which none of the six did.

**Where the overhead actually is — profiled, not inferred.** At equal
simulations ISMCTS costs 13.7% more wall time (1903ms vs 1673ms for 960 sims).
Unit costs: `_rollout` 1.612 ms, `determinize_for_bot` 0.107 ms, `clone`
0.023 ms — so determinization is only **6.6% of a single rollout**, and its
share of search wall time is 2.2% in paired mode against 5.4% in ISMCTS. That
~3pp difference is a small part of the 14pp gap; **the rest is tree-descent
overhead** (`_search_actions` at every node, `_advance_to_decision`, node
bookkeeping).

So making determinization cheaper would recover about a fifth of the gap, not
all of it. An earlier version of this section claimed determinization was the
bottleneck; that was inferred from an iteration count without profiling, and is
wrong.

**Correct order of work:** settle whether the effect is real *before* optimising
anything, because a perfect optimisation only buys wall-clock ISMCTS its
fixed-iteration result, which is currently p=0.099. Needs ~1200 more games at
fixed iterations (net must clear ~1.96·√pairs; currently +26 over 230).

Depth matters and the mechanism explains it: at 60ms depth 2 builds ~12 interior
nodes and depth 3 builds ~29, which over ~50 iterations is ~4 visits per node
versus 1.7. Depth 3 measured −1.2pp; the tree becomes noise when spread that
thin.

Depth matters and the mechanism explains it: at 60ms depth 2 builds ~12 interior
nodes and depth 3 builds ~29, which over ~50 iterations is ~4 visits per node
versus 1.7. Depth 3 measured −1.2pp; the tree becomes noise when spread that
thin.

## Prior art worth knowing before inventing something

Gathered 2026-08-01. This project had explored almost entirely inward.

- **Tales of Tribute AI Competition** (arXiv 2305.08234) is the closest
  published analogue — a *two-player* deckbuilder. The 2023 winner used
  **root-parallelised MCTS with five trees, one per sampled seed**, feature
  weights tuned by an evolutionary algorithm. Its UCT took the **maximum rather
  than the average** on backup ("counterintuitive but tested better"). Its top
  three agents showed rock-paper-scissors behaviour with no clear winner, which
  mirrors this project's six-methods-one-band result.
- **Ensemble determinization** (Cowling et al., Magic: The Gathering) — multiple
  trees, one per determinization, combined only at the root; significant gains
  over basic determinized MCTS. Structurally *not* ISMCTS: ISMCTS pools
  statistics across worlds in one tree, ensemble keeps them separate and votes.
- **Dominion** (Springer 978-3-319-19066-2_5) — MCTS/UCT reached **67%** against
  a strong finite-state agent that moved first. Deckbuilder MCTS can reach far
  wider margins than the ~5pp seen here.
- **Temple Gates' shipped Dominion AI** — AlphaZero-style: a network supplies
  both value and branch priors, trained by self-play RL. Their reported
  breakthrough was an **embedding representing cards by attributes** rather than
  identity. (`hero_rl_env_v4` does that by hand and measured null, which weakly
  suggests the null was about the policy, not the features.)

Recurring theme: **MCTS coupled with a learned value function**, not MCTS with a
hand-written rollout. That combination is the main untried thing here — this
repo has built policies (V16-V21) and built search, and never joined them.
Slay the Spire work has largely moved to LLM agents and is less applicable.

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
