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
- **Widening the buy root** (`MCTS_BUY_ROOT_WIDTH` 3 → 5 → unlimited) — costs
  **9-11pp**, monotone, two significant arms (p=0.002, p=0.001). The narrowing
  is load-bearing, not a constraint: at ~33 iterations/decision, splitting the
  budget over more branches starves all of them. Same breadth-vs-depth wall as
  ISMCTS and ensemble, on a depth-1 tree.
- **The `or_choice` double-count fix in `_buy_priority`** — genuinely a bug
  (Street Thug and Cult Priest were scored as if both mutually exclusive
  branches fire), genuinely worth nothing: nets +2, exactly the null. Two of 55
  cards is too little surface.
- **Refitting `_buy_priority`'s weights** (`hero_buy_fit.py`, zero-noise cached
  oracle, the fix for both failures diagnosed in `hero_cma_fit.py`). The
  top-3 already contains the oracle's best option **92.5%** of the time, so the
  narrowing loses **0.131 HP per buy decision out of 5.21 HP of stakes (2.5%)**.
  That 0.131 HP is the ceiling for a *perfect* selector — ~1.5 HP per game,
  below this project's noise floor. Not worth an A/B. The fit also reproduces
  the old CMA-ES sign-flip pathology (`buy_gold = −7.01`) with a different
  objective and a third of the parameters, which suggests it is a property of
  fitting this valuation rather than of that run's setup.

**Do not tune buy valuation again without first checking the ceiling.**
`hero_regret.py` and `hero_buy_fit.py` both answer "how much is even available
here" in about a minute. Four separate attempts have now died against a
headroom that was small before any of them started.

## ISMCTS is settled: negative, at equal simulation counts

Four independent blocks at a fixed 40 simulations per decision, where the search
is deterministic given the seed and a null replicate reads exactly 0/0:

| block | discordant (ismcts-heavy / paired-heavy) | pooled net | pooled p |
| --- | --- | --- | --- |
| TUNE | 72/53 | +19 | 0.107 |
| HOLDOUT | 56/49 | +26 | 0.099 |
| BLOCK-C | 81/101 | +6 | 0.805 |
| BLOCK-D | 93/106 | **−7** | **0.808** |

**Final: −7 net over 611 discordant pairs, p=0.808.** The effect looked real
through two blocks (p=0.099, the best-powered positive signal in the project all
session), then crossed zero and finished slightly negative. This is not "ISMCTS
doesn't pay for its wall-clock cost" - that was the earlier, weaker reading. At
*equal* simulation counts the tree provides no benefit at all. `ROOT_SAMPLING_MODE`
stays `paired`.

The lesson to keep, independent of ISMCTS specifically: **a result significant
through two blocks can still be a false positive.** Two positive blocks felt
like enough to call it, and it would have been wrong. Confirm on a disjoint
block is necessary; it is not always sufficient. When a pooled effect is close
to the threshold, run a third block before believing it.

Structurally, ISMCTS is not ruled out forever - only the specific choice of
pooling statistics in one tree across determinizations, at depth 2-3, with these
UCB settings, on this game.

**Ensemble determinization also lost.** N independent trees per determinization,
combined only at the root (`ROOT_SAMPLING_MODE="ensemble"`, the approach with
competition-winning precedent for a two-player deckbuilder) - swept at 3/5/10
trees, fixed 40 sims, both blocks. Every tree count lost to `paired` on every
block (pooled net −20 to −31, best p=0.066). Unlike ISMCTS this was never
positive, which makes it the more trustworthy negative of the two. Caveat: at
40 total sims split across even 3 trees, each tree gets only ~13 iterations,
likely too few to expand meaningfully - this rules out ensemble *at this
budget*, not necessarily at 200+ sims/decision, which has not been tested.
`ROOT_SAMPLING_MODE` stays `paired` either way.

So both ways of sharing information across determinizations - pool it in one
tree (ISMCTS), or don't pool it at all (ensemble) - lose to the simplest option,
a depth-1 fan with common random numbers, at the simulation counts this bot
actually gets. If this thread is picked up again, test ensemble at a
simulation count large enough for each tree to build real depth before
concluding the mechanism itself does not transfer.

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
hand-written rollout. That combination has now been tried (`hero_value_net.py`,
below) and lost. Slay the Spire work has largely moved to LLM agents and is
less applicable.

## The value network lost, but did not cleanly settle the question

`LEAF_EVAL_MODE="value_net"` replaces `_rollout`'s playout with a trained
network's forward pass — ~13x more iterations at 60ms (33 → 438), aimed
squarely at the sample-starvation that killed ISMCTS and ensemble
determinization. A/B, wall clock, 400 games/arm: **−5.3pp against a clean null**
(value_net 53.2% vs control 58.5%, discordant 42/63 vs null's 4/6, p=0.050).
`LEAF_EVAL_MODE` stays `rollout`.

This does **not** cleanly rule out the mechanism, only this network — 3000
positions, ~24 features, 0.309 held-out MAE against its own oracle, which was
already known to be a mediocre fit before the A/B ran. A materially
better-trained net (more positions, more rollouts/label, richer features) is a
different, untested claim. Given the size and clean separation of the loss,
inference — not a second measurement — says leaf noise compounds through UCB
faster than iteration count averages it out.

Two bugs found building it are worth knowing if this is revisited: the first
model load costs ~330ms, enough to eat an entire budgeted decision if not
warmed first (`warm_value_net()`); and the network's outputs legitimately fall
outside `_search_utility`'s nonterminal range `(0.1, 0.9)`, since training
labels include exact terminal 0/1 — the naive inverse-tanh crashed on this
within the first few games of the first real run.

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
