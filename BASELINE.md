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

### First root cause (fixed): the evaluation function punished deckbuilding

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

`_card_value` was defined in the same file and never called anywhere: the
deck-valuation primitive existed and was simply never wired in.

Fixed, but fixing it alone changed almost nothing (0.0% -> 0.8%), which is what
eventually pointed at the four further bugs below. The lesson worth keeping: two
very different objectives both produced ~0-3%, and that agreement was the signal
that the objective was not what was broken.

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

## Discard/sacrifice targeting was context-free (fixed)

`_find_worst_idx`/`_find_best_idx` in `hero_engine.py` decide which card gets
discarded, sacrificed, or returned from discard — real decisions in Hero
Realms, alongside buying and `or_choice`. They used a single fixed
`_card_score` (cost and raw stats only), with no idea whether the player
needs healing, is racing to close out a game, already has plenty of gold, or
has an ally on board that makes a card's `ally_*` fields real. This is an
engine-level fix, not an AI valuation nuance: these functions run in every
simulated game — RL training, heuristic AI opponents, and the MCTS bot alike.

Added `_contextual_card_value(card, player, opponent)`, which starts from
`_card_score` and adjusts for:

- **Combat**, scaled up as the opponent nears death (closing out beats chip
  damage at full HP).
- **Healing**, scaled up as the player's own HP drops.
- **Ally certainty** — full credit for `ally_*` fields once the matching
  faction is actually on the player's board, 0.2x credit otherwise, rather
  than the 0 credit `_card_score` gave every ally-dependent card regardless
  of board state.
- **Gold, diminishing returns** — discounted by the player's own gold
  density, mirroring the buy-side discount in `web/bot.py`.

The four starting cards (Gold/Shortsword/Dagger/Ruby) are exempt from every
adjustment and stay the default target under any circumstances, matching
`_worth_sacrificing`'s existing assumption.

`_worth_sacrificing` now accepts the same context and generalizes beyond only
the four starting cards: a redundant purchased card (e.g. a fifth economy
card in a gold-saturated deck) can become worth sacrificing too, not only
starting junk.

Verified against real cards before writing tests (the same discipline the
buy-side fixes needed twice): a combat card with no heal effect correctly
becomes the worst card to keep once the player is critically low, a gold card
correctly loses value as deck gold density rises while a non-gold card in the
same hand is unaffected, and an ally card gains value only once the matching
faction is actually on board. Covered by `tests/test_discard_targeting.py`.

**Open question, not yet resolved:** a 20-games/profile spot check right after
this landed (search eval, situational buy policy, 60ms) measured mcts 6.2% /
heuristic 33.8%, down from the 20.0% / 30.8% recorded earlier at the same
settings. At n=20 that is noisy (~+/-11pp per cell), and the or_choice and
sacrifice-optionality fixes landed between those two measurements too, so this
is not a controlled A/B and the drop cannot be attributed to this change
specifically. Needs a dedicated sweep (holding buy_policy/eval fixed, isolating
just this change) before drawing a conclusion either way.

## Ally abilities never triggered off actions (fixed)

Per the official rules an ally ability triggers "as soon as you have another
card of that faction in play", and Actions/Items stay in play until the
Discard Phase. `has_ally` only checked `player.board`, which holds champions
only. **21 of the 36 ally cards are actions**, so none of them could ever
trigger another: playing Profit then Intimidation (both Guild) in one turn
did nothing. Faction-stacking with actions - a core strategy - was
non-functional in every game this engine has simulated, RL training included.

Measured impact over 60 games, counting every ally check:

```
triggered under the old board-only rule:   102 / 1023  (10.0%)
triggered under the correct rule:          201 / 1023  (19.6%)
```

**Half of all ally bonuses in the game were being silently lost.** Fixed via
`HRPlayer.played_this_turn`, cleared at every per-turn reset, checked by
`has_ally` alongside the board.

### Allies are also retroactive (second fix)

> "The order in which you play your cards does not matter. As soon as you have
> two or more cards of the same faction in play, you may trigger all relevant
> Ally Abilities."

`play_card` evaluated `ally_bonus` **once, at play time**, and never revisited
it - so playing a lone Guild card and *then* a second Guild card fired only the
second one's ally. Cards whose ally is not yet live now queue in
`HRPlayer.pending_ally` and fire the moment a same-faction card enters play
(action or champion). Worth **+31% more ally firings** on its own (152 -> 199
over 60 games), on top of the in-play fix above.

### Fire Gem is the only market card that enables nothing

Of the 19 market cards with no printed ally ability, **18 still have a
faction**, so they turn on every other card of that faction; exactly one has no
faction at all - Fire Gem. `_holistic_card_score` scored those 18 identically
to Fire Gem on synergy (both zero), missing the reason Fire Gem is a weak buy
unless the market is all 6-7 cost. `_enabler_value` now prices a card's
contribution to *other* cards' allies: a plain Necros card scores 2.16 with
three Necros ally cards owned, Fire Gem scores 0.00.

Covered by `tests/test_ally_triggers.py`.

## The holistic buy valuation makes the bot *worse* (default reverted)

Three matched-seed A/Bs, and the gap widens as the scorer gets more
sophisticated:

| run | static | situational (`_holistic_card_score`) |
|---|---|---|
| pre-engine-fixes | 20.0% | 18.8% |
| post-engine-fixes | 20.6% | 18.1% |
| current HEAD | **22.5%** | 15.8% |

`BUY_POLICY` now defaults to `"static"`.

This is the known MCTS result that a stronger rollout policy does not imply a
stronger search: a more deterministic, greedier default policy narrows the
distribution of simulated outcomes and biases the value estimates, and that
costs more than the better play buys. Worth remembering before adding
"smarter" logic to a rollout again.

`_holistic_card_score` is not wasted - it decomposes into named, explainable
terms (opponent-HP urgency, ally certainty, thinning value, sacrifice bonus),
which is exactly what a coach needs to justify a recommendation. It belongs in
the explanation layer, not in the rollout.

## Engine-vs-rules audit (three more bugs)

Prompted by how many rules bugs kept surfacing one at a time. `tools/audit_cards.py`
compares every card's printed text to its parsed `effects` dict; it found the
**card data is clean** (55 cards, one false positive where `discard: 1`
correctly encodes "draw a card, then discard a card"). That was the useful
result: every bug found so far has been in **engine logic**, not data. So the
audit moved to engine-vs-rules semantics.

**1. Wolf Shaman counted only champions.** Its text reads "+1 combat for each
other {Wild} *card* you have in play" - not "champion". All eight other
`per_*` counting sites say champion or guard, so board-only is right for them;
this one is not. Wild actions in play now count.

**2. Champion damage carried over between turns.** The rules: *"Damage to
Champions does not carry over between turns."* `current_health` was set once in
`BoardChampion.__init__` and never reset, so chip damage accumulated
permanently and guards silently eroded across a game. Now reset at every
per-turn boundary (`hero_engine`, `web/session`, `hero_rl_env`).

**3. Stunned champions were destroyed instead of discarded.** The rules: *"Once
stunned, a Champion is placed in its owner's discard pile."* Every combat site
filtered dead champions off the board with a list comprehension, so the card
left the game entirely - effectively banishing it. That made every champion a
one-use card once attacked, and gutted champion-focused strategies. Now
centralised in `remove_stunned_champions`, which moves the card to its owner's
discard; ~3.4 champion cards per game are recoverable that previously vanished.

Covered by `tests/test_champion_rules.py`.

## Known structural limits

These cap what any amount of training can achieve here:

1. **Action space is buy-only** (7 actions: market slots 0–4, Fire Gem, pass).
   Card play, champion expends, guard targeting, and discard/sacrifice choices
   are auto-resolved by heuristics in `HeroRealmsEnv._resolve_turn`.
2. **Observation omits deck and discard composition entirely** — in a
   deckbuilder, the agent cannot see its own deck quality.
3. **Hand is observed post-auto-play**, and only the first 5 cards.

Limits 1–3 are addressed by `hero_rl_env_v2.py` (see below). **Fixing them did
not fix the win rate**, which relocates the problem rather than solving it.

## V14 — last buy-only run, first on the corrected engine

Every model v10–v13 was trained against a broken engine (54-card market deck,
non-retroactive allies, mandatory sacrifice, champion damage persisting across
turns, stunned champions destroyed rather than discarded, dead reanimate code).
Those checkpoints are invalid baselines and were not resumed from.

V14 (2M steps, Fire Gem penalty −0.01, buy-only): peak 24.0% at 1.7M, final
**19.5%** vs random profiles. No plateau, 15–24% band, no convergence.

## V15 — unified action space did not beat a naive heuristic

`hero_rl_env_v2.py` drives the real `GameSession`: play order, champion
expends, buys, and combat routing/targeting are all the policy's decisions,
illegal actions masked via `MaskablePPO` (sb3-contrib). Observation gains deck
composition (gold/combat/draw density, faction counts, sacrifice access).

Measured on identical eval seeds (100000–100199, `opponent_profile="random"`):

| Policy | Win rate |
| --- | --- |
| Uniform random legal action | 0.0% |
| **Naive highest-priority greedy** | **37.5%** |
| V15 @ 500k | 29.5% |
| V15 @ 900k (best checkpoint) | 36.5% |
| V15 @ 2M (final) | 19.0% |

**MaskablePPO never beat greedy.** The run oscillated 23–38% with no learning
trend across 2M steps and collapsed to 18% at the end — that is noise around a
naive baseline, not convergence.

Note the earlier "greedy 34%" figure was measured on seeds 0–49; on the eval
seeds it is 37.5%. Baselines and checkpoints must share a seed set to be
comparable — the two numbers are the same policy, not a change.

What this rules out and what it doesn't:

- **Ruled out:** that the buy-only action space was the binding constraint.
  It was a real limit (v14 could not learn targeting at all), but removing it
  moved the ceiling by ~0, so it was not what was holding the win rate down.
- **Not ruled out:** sparse terminal-only reward over ~69-step episodes across
  30 actions makes credit assignment hard; fixed heuristic opponents cap the
  skill ceiling; PPO from random init may simply need a warm start to find the
  region greedy already occupies; sacrifice/discard (still heuristic, and named
  by the project owner as among the game's most important decisions) may carry
  more of the value than buy/play/targeting combined.

The practical read: **MCTS remains the stronger engine for this game**, and
that conclusion is now supported by a full-action-space RL run rather than
only by the buy-only one.

## Rules corrections applied

Verified against the [official base-set rules](https://www.herorealms.com/base-game-rules/):

- Market row is 5 face-up cards — already correct in `HRMarket`.
- Fire Gem stack is **16** cards; `hero_engine.py` had 15. Fixed.
- 50 starting health, 7 Gold / Shortsword / Dagger / Ruby deck, first player
  draws 3 and second draws 5 — all already correct, now covered by tests.
