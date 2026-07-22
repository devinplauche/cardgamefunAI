# Verified Baseline — 2026-07-22

Authoritative agent-strength numbers. Supersedes the per-opponent tables in
`FINAL_SESSION_REPORT.md`, `V2_TRAINING_RESULTS.md`, `V1_VS_V2_COMPARISON.md`,
`SESSION_SUMMARY_2026_06_20.md`, and `QA_CRITICAL_FINDING_2026-06-20.md`, all of
which were produced with a broken evaluation harness (see below).

Reproduce with:

```bash
python hero_rl_eval.py --games 200
```

## Results

200 seeded games per cell. Win rate for the agent seat (goes first, draws 3).

| model | balanced | aggressive | economic | champion | **AVG** |
|---|---|---|---|---|---|
| models_v10/v10_final | 21.5% | 23.0% | 24.0% | 29.5% | 24.5% |
| models_v11/v11_final¹ | 17.0% | 18.0% | 21.5% | 23.0% | 19.9% |
| models_v12/v12_final | 38.5% | 36.5% | 37.0% | 43.5% | 38.9% |
| **models_v12x/v12x_final** | 41.5% | 42.0% | 46.0% | 50.0% | **44.9%** |
| models_v13/v13_final | 21.0% | 20.5% | 20.0% | 21.0% | 20.6% |
| **heuristic** (reference) | 48.5% | 50.0% | 55.0% | 60.5% | **53.5%** |
| random (floor) | 1.0% | 1.5% | 0.0% | 1.0% | 0.9% |

¹ v11 trained with `allow_fire_gem=False`, so it is evaluated in a 6-action env.
Its number is not strictly comparable to the rest.

## The headline

**No trained model beats the heuristic.** The best agent, v12x, wins 44.9% where
simply reusing `buy_balanced`'s own scoring rule in the agent seat wins 53.5%.
The RL pipeline currently costs 8.6pp against the baseline it was built to beat.

The `heuristic` row doubles as a harness sanity check: a true mirror match
(heuristic vs balanced) lands at 48.5%, i.e. ~50% minus the first-player
disadvantage of drawing 3. That is the expected value, so the harness is sound.

## Why the old numbers were wrong

`HeroRealmsEnv.__init__` accepted an `opponent_profile` argument, stored it in
`_requested_profile`, and then unconditionally assigned
`self._opponent_profile = OPPONENT_PROFILES["balanced"]`. Only `reset()`'s
`"random"` branch ever called `set_opponent_profile`. Passing `"aggressive"`
silently played BalancedAI.

`hero_rl_train_v2.py:160` and `:276` build evaluation envs exactly that way, so
every published per-opponent table was the same BalancedAI matchup reported four
times under four labels. `QA_CRITICAL_FINDING_2026-06-20.md` claimed to fix this;
the fix only covered the `"random"` path.

Fixed in `hero_rl_env.py`, guarded by `tests/test_rl_env.py`.

## Version lineage (the numbering is misleading)

`v12x` resumes from `models_v12/v12_1800000.zip` for 2M additional steps
(~3.8M cumulative). `v13` constructs a **fresh** `PPO(...)` and trains 2M steps
from scratch. v13 is not a successor to v12x — it is a shorter, independent run,
which is why it scores 24pp lower.

## Learned policies are degenerate

Action distributions over 60 deterministic episodes:

```
v12x:  slots 0-4 ≈ 10% each,  Fire Gem 45%,  end-turn 0%
v13:   slots 0-4 (28/14/14/27/18%),  Fire Gem 0%,  end-turn 0%
```

v12x learned to spam Fire Gem despite its −0.01 penalty; raising the penalty to
−0.02 in v13 collapsed the policy onto market slots by position. v13's flat win
rate across all four opponents (21.0/20.5/20.0/21.0) indicates its policy is not
conditioning on opponent state at all. Neither agent ever chooses to end its own
turn — both rely on the env auto-resolving when a buy fails.

## MCTS bot (web/bot.py)

```bash
python hero_mcts_bench.py --games 50 --budget 60
```

Different harness — the bot seat is the **second** player (draws 5) with the
full action space, because `evaluate_state` scores from `session.bot`'s
perspective. Not comparable to the table above; compare the two rows here.

30 seeded games per profile at 60 ms:

| algorithm | balanced | aggressive | economic | champion | **AVG** |
|---|---|---|---|---|---|
| mcts, search eval | 3.3% | 16.7% | 16.7% | 20.0% | **14.2%** |
| mcts, shaped eval | 20.0% | 26.7% | 23.3% | 10.0% | **20.0%** |
| heuristic (its own greedy fallback) | 43.3% | 43.3% | 33.3% | 40.0% | **40.0%** |

MCTS originally lost **all 200 games** at 60 ms. Five separate fixes were needed
to reach the numbers above, and at this budget it is still worse than the greedy
fallback it ships alongside. See the budget sweep below: at 960 ms it matches
the heuristic.

### Root cause: the evaluation function punishes deckbuilding

`evaluate_state` has no term for deck quality or acquired cards, but scores
`(player.gold - opponent.gold) * 1.0`. So spending gold is pure loss and
passing is always optimal. Measured at a real decision point with 4 gold:

```
buy Elven Curse (cost 3)  ->  delta -3.00
advance_phase (pass)      ->  delta +0.00
```

It also scores `(len(player.hand) - len(opponent.hand)) * 0.75`, so *playing* a
card is penalised too, and `market.fire_gems_remaining * 0.05` rewards not
buying Fire Gems.

The search is behaving correctly; the objective is wrong. Over a full game the
bot played 3 cards, bought **nothing** (deck never left its starting 10 cards),
never attacked (opponent finished on 50 HP), and advanced the phase 28 times.

Fixing this means giving `evaluate_state` a deck-quality term — economy and
board development have to outweigh the gold spent to get them. Until then the
MCTS row is not a measure of search quality.

### Search-priced vs shaped evaluation, by budget

```bash
python hero_mcts_bench.py --games 20 --budget 960 --eval search --profiles balanced champion
```

20 games per cell on `balanced` and `champion` only, so each cell carries about
+/-11pp of sampling error. Read the trend, not the individual cells.

| budget | search-priced | shaped |
|---|---|---|
| 60 ms | 10.0% | 27.5% |
| 240 ms | 10.0% | 25.0% |
| 960 ms | **42.5%** | 35.0% |

Heuristic reference on these two profiles: ~41.7%.

**The two evaluators cross over between 240 ms and 960 ms.** Search-priced
evaluation asserts no exchange rate between gold, combat and board development
and lets rollouts price them, which is only possible once there are enough
rollouts to resolve anything: it sits at the floor until the budget arrives,
then jumps 10% -> 42.5% and matches the heuristic for the first time. Shaped
evaluation gets a dense signal from every card and is close to flat, so extra
search buys it comparatively little.

The 10% -> 42.5% climb is >4 standard errors and is real. The search-vs-shaped
gap at 960 ms (42.5 vs 35.0) is about 1 standard error and is not.

Practical consequence: the right default depends on the budget. At the 60 ms the
web UI uses, shaped is clearly better. Search-priced is the better objective and
the one worth investing in, but it needs roughly 16x more rollouts per decision
than the interactive budget currently allows.

### Three bugs fixed to make the benchmark runnable

1. **`legal_actions()` offered illegal attacks.** Guard targets were listed
   whenever guards existed, without checking `player.combat > 0`;
   `attack_target_action` then raised `ValueError("No combat remaining")`.
   This crashed the live web app too, not just the benchmark.
2. **MCTS cached actions across stochastic redraws.** `end_turn()` draws 5
   cards at random, so replaying an action sequence does not reproduce the
   state, and cached tree actions went stale — an intermittent
   `ValueError("Card not found in hand")` mid-search. Selection and expansion
   now re-check legality against the sampled state.
3. **Telemetry in the search hot loop.** `clone()` deep-copied `history` (80
   entries, each holding a full state snapshot) and `log`, and `record_event`
   re-serialised full state on every action inside rollouts. Clone cost went
   8.0 ms -> 0.61 ms and search went 9.1 -> 28.0 iterations per decision at the
   same 60 ms budget. Note even 28 iterations is far too few for a real MCTS.

Covered by `tests/web/test_bot_search.py`.

## Known structural limits

These cap what any amount of training can achieve here:

1. **Action space is buy-only** (7 actions: market slots 0–4, Fire Gem, pass).
   Card play, champion expends, guard targeting, and discard/sacrifice choices
   are auto-resolved by heuristics in `HeroRealmsEnv._resolve_turn`.
2. **Observation omits deck and discard composition entirely** — in a
   deckbuilder, the agent cannot see its own deck quality.
3. **Hand is observed post-auto-play**, and only the first 5 cards.

## Rules corrections applied

Verified against the [official base-set rules](https://www.herorealms.com/base-game-rules/):

- Market row is 5 face-up cards — already correct in `HRMarket`.
- Fire Gem stack is **16** cards; `hero_engine.py` had 15. Fixed.
- 50 starting health, 7 Gold / Shortsword / Dagger / Ruby deck, first player
  draws 3 and second draws 5 — all already correct, now covered by tests.
