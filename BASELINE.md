> **⚠ Ruby was mis-encoded for the entire life of this project. Every number
> below it in this file was measured on a starting deck 29% poorer than the real
> one, and the MCTS-minus-heuristic delta more than halves when it is fixed.
> See "The Ruby bug" immediately below. Treat every historical figure here as
> describing a different game until re-baselined.**

---

# How to read this file

This is a **lab notebook**, in rough chronological order. Later sections
supersede earlier ones without saying so, and several earlier claims are now
known to be wrong. It is not the place to start.

- **Starting work?** Read `CLAUDE.md` instead. It holds the measurement
  protocol, the current defaults and their evidence, what has been ruled out,
  and the gotchas that have produced wrong numbers. It is ~120 lines.
- **Running an experiment?** Use `hero_ab.paired_experiment` and the
  `ab-experiment` skill. Do not hand-roll a harness; three of the five
  hand-rolled ones shipped bugs that produced confident wrong answers.
- **Adding a result here?** Record negatives too, with the arm table. Most
  results in this project are negative and this record is what stops them being
  re-run.

## Current state, at a glance

| | |
| --- | --- |
| MCTS vs same-seat heuristic | **~5pp** (was ~11pp before the Ruby fix) |
| Best RL model held out | ~48-50%, six methods in the same band |
| Search compute | saturates by ~240ms; 960ms buys nothing |
| Mirror match (equal players) | ~48.5%, so ~50% is the even-strength value |

**Known-stale claims below, corrected later in this file:**

- The champion-denial blind spot is described as the top open problem. It is
  **already fixed** - `_combat_search_actions` prunes face away when a champion
  is killable, so the snipe rate is 100% across all six champions where 0-35%
  is recorded.
- The horizon sweep's "+28pp at 200ms" chose `ROLLOUT_TURNS=16`. Re-measured at
  the shipped budget it is a **null** vs 24 and 32 over 2800 games.
- Any absolute win rate quoted from a single seed block carries ~±10pp.
- "~28 iterations per decision at 60ms" predates the clone/telemetry fixes; the
  real figure is ~66.

---

## The Ruby bug: the starting deck was 29% poorer than the real game

`RUBY` was defined in `hero_engine.py` as
`card_type="action", effects={"health": 1}`. The printed card is a **treasure
worth 2 gold**. So every player's starting deck produced **7 gold per cycle
instead of 9**, and carried a point of healing that does not exist.

### How it survived every audit

- `tools/audit_cards.py` compares printed text to the effects dict for the
  **55 cards in `data/hero_realms_cards.json`**. The five starting/Fire Gem
  cards are hardcoded in `hero_engine.py` and were never in its scope. The
  audit's conclusion, recorded in this file, was "the card data is clean".
- `RULES_COMPLIANCE.md`, `QA_FINAL_REPORT.md` and `QA_RULES_VERIFICATION.md`
  each tick "Starting deck: 7 Gold + 1 Shortsword + 1 Dagger + 1 Ruby". That
  verifies the deck's **composition** and never any card's **effects**.
- No test anywhere asserted Ruby's effect: fixing it broke **zero** of 301
  existing tests.

The one card checked by neither the automated audit nor the manual QA was the
one that was wrong. `tests/test_starting_cards.py` now pins all five faces and
the deck's aggregate economy.

### Two tuning constants were derived from the bug

Both were documented as following from the starting gold density, which read
0.7 instead of 0.9:

- `web/bot.py: STARTING_GOLD_DENSITY` 0.7 → 0.9
- `hero_engine.py: _GOLD_DENSITY_DISCOUNT_SCALE` 0.7*4 → 0.9*4

The Spark-vs-Taxation calibration recorded in `web/bot.py`'s comments was
carried out against the poorer deck and is not necessarily still right.

### Measured impact, same seeds (block 1000+, 400 games/arm, 60 ms)

| | buggy | corrected | change |
| --- | --- | --- | --- |
| heuristic | 46.0% | **53.8%** | +7.8pp |
| MCTS | 57.0% | **58.5%** | +1.5pp |
| **MCTS − heuristic** | **+11.0pp** | **+4.7pp** | **−6.3pp** |
| mean game length (turn_number) | 26.1 | 23.3 | −11% |

**More than half of search's measured advantage over the heuristic was an
artifact of the broken starting deck.** The heuristic gains 7.8pp from correct
economy; MCTS gains 1.5pp. A 29%-poorer deck makes games longer and leaves more
decisions live, which is the regime where search converts; restore the economy
and the game is faster and more decided by deck quality.

### Re-baseline confirmed on two disjoint blocks (100 games/profile each)

| block | heuristic | MCTS | delta |
| --- | --- | --- | --- |
| 1000+ | 53.8% | 57.8% | +4.0pp |
| 60000+ | 46.8% | 53.0% | +6.2pp |

Both land in the same 4-6pp range, down from 8.7-11.0pp pre-fix on these same
blocks. **The corrected reference delta for MCTS over the same-seat heuristic is
~5pp, not ~11pp.** Any future work should be judged against this, not the
figures below.

Consequences:

- Every MCTS-vs-heuristic figure recorded below was measured on the broken
  engine and overstates search's contribution.
- The override-gate curve (heuristic 46.0% → gated 57.0%) was measured on it
  too, so its +11pp headline is really ~+4.7pp. The *shape* of the curve - an
  inverted U peaking at the shipped setting - has not been re-measured.
- The RL results are affected identically, since `hero_rl_env_*` all drive the
  same engine.
- Anything calibrated against game length (`ROLLOUT_TURNS = 16` seat-turns,
  `EXPECTED_GAME_TURNS = 26`) is now mis-scaled: 26 was measured on the buggy
  engine and should be ~23.

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

## V16 — the warm start was the missing piece

Behavior-clone greedy (3000 episodes, 428k state-action pairs, BC loss
0.297 → 0.022), then fine-tune with the same MaskablePPO setup at a lower
learning rate (1e-4) and entropy (0.005).

| Stage | Win rate (eval seeds) |
| --- | --- |
| BC clone of greedy | 33.0% |
| + 150k fine-tune | 39.5% |
| + 350k fine-tune | 55.5% (best observed) |
| + 500k fine-tune (final) | 47.0% |

Validated on **held-out seeds 900000–900499** (n=500, never used in BC
collection or in-training eval):

| Opponent | V16 final | Greedy |
| --- | --- | --- |
| random (n=500) | **46.8%** | 30.6% |
| balanced | 43.3% | 32.0% |
| aggressive | 51.3% | 37.3% |
| economic | 52.0% | 32.0% |
| champion | 47.3% | 34.7% |

This is the first RL policy in the project to beat the heuristic, and it beats
it on every opponent profile, on seeds it never trained against.

The V15 hypothesis was therefore right in mechanism but wrong in emphasis: PPO
*can* improve on greedy in this action space, it just cannot find greedy's
region of policy space on its own from a terminal-only ±1 reward. Cloning
first and improving second works; exploring from random init does not.

Note greedy scores 37.5% on the eval seeds but 30.6% on the held-out set — the
heuristic is more seed-sensitive than the learned policy (46.8% vs 47.0%
across the same two sets). Compare policies within a seed set, never across.

**Process failure worth recording:** V16's phase 2 had an eval callback but no
checkpoint callback, so the best observed model (55.5% at 350k) was overwritten
and is unrecoverable. Only the 47.0% final survives. V17 pairs every eval with
a save for exactly this reason.

## V17 — more fine-tuning added nothing

Continued V16's fine-tune for 1.5M more steps, checkpointed every 50k. Peaked
at 51.0% by 100k, then oscillated 32–46% for the remaining 1.4M steps with no
trend. Re-evaluated from disk:

| Model | Eval seeds (n=200) | Held-out (n=400) |
| --- | --- | --- |
| `v16_final` | 48.0% | **49.8%** |
| `v17_best` | 49.0% | 47.2% |
| `v17_final` | 45.0% | 37.0% |

**V16 is still the best model.** V17's 1.5M steps produced no improvement.

`v17_best` is a worked example of checkpoint-selection bias: it was chosen
*because* it scored 51.0% on the eval seeds, re-evaluates at 49.0% on those
same seeds, and falls to 47.2% held out. Selecting on a seed set and then
reporting that set's score overstates by roughly two points. Model selection
and model reporting need different seeds, the same way BC data and eval data
already do.

## Where this leaves MCTS vs RL

The earlier read — that MCTS is simply the stronger engine — was based on RL
never beating a naive heuristic. V16 changes that premise and the conclusion
should move with it: a warm-started policy beats greedy comfortably and costs
one forward pass at inference, against MCTS's thousands of rollouts.

## V18 — self-play did not work

`hero_rl_selfplay.py`: the opposing seat is a frozen snapshot drawn from a pool
of past policies, seats randomized per episode, starting from V16 with V16 as
the initial pool anchor. Progress measured against fixed external references,
never the current opponent (a self-play win rate sits near 50% by construction
whether both sides are strong or both are terrible).

| Step | vs heuristics | vs frozen V16 | pool |
| --- | --- | --- | --- |
| 100k | 49.3% | 60.0% | 2 |
| 200k | **50.7%** | **63.3%** | 3 |
| 300k | 36.0% | 50.0% | 4 |
| 700k–1.4M | 34–45% | 40–57% | 8 |
| 1.5M (final) | 34.7% | 50.0% | 8 |

Two hundred thousand steps of real improvement — beating frozen V16 63.3% head
to head — then a collapse it never recovered from, ending below its own
starting point.

The obvious explanation, that the pool filled with weak descendants, does not
fit: the collapse begins at pool=4, before the cap, and the capped-pool mean
(41.2%) is higher than the 300k trough. No validated mechanism. Candidates not
yet tested: learning rate too high for a converged start, entropy driving drift
off the BC-anchored policy, or the pool needing far more diversity than eight
snapshots of one lineage.

## Evaluation was not reproducible (fixed)

`opponent_profile="random"` drew the profile with `random.choice` on the global
RNG. The episode seed fixed the deck shuffle but **not** which of the four
profiles was faced, so the same model on the same seeds scored 45.5% and 48.0%
in two separate runs.

Every "identical seeds" comparison recorded above this section carried that
unseeded component. Not a bias — profiles were drawn uniformly either way — but
the runs were noisier than claimed and small gaps between models meant less
than reported. Treat any difference under ~5pp in the sections above as
unresolved.

Unaffected: the MCTS head-to-head below, which uses the named `balanced`
profile (no random draw) and deterministic seat alternation.

Profile and self-play opponent/seat draws now derive from the episode seed.

### Reproducible standing (n=600, held-out seeds 900000+)

| Policy | Win rate |
| --- | --- |
| Greedy heuristic | 31.3% |
| **V16 (BC + fine-tune)** | **48.0%** |
| V18 best (self-play @ 200k) | **48.3%** |
| V18 final (self-play @ 1.5M) | 37.2% |

V16 and V18-best are indistinguishable at 0.3pp on n=600. **Four attempts to
improve on V16 — V17's extended fine-tune, V18's self-play, and both of their
best checkpoints — have produced nothing above noise.** The ~48% band is where
this setup tops out.

What has not been tried, and is where the remaining headroom most plausibly
sits: exposing sacrifice and discard targeting as real actions. Those are
currently resolved by engine heuristics, they are the decisions the project
owner identifies as among the most important in the game, and no amount of
training-loop variation reaches them.

## The variance ceiling: the plateau is not the game

Before spending more compute, measure whether ~48% is an optimizer limit or a
property of a high-variance game. `hero_variance_ceiling.py` plays policies of
widely differing strength through identical seeds and partitions them.

n=300 shared seeds, agent on the bot seat, opponents seeded and reproducible:

| Band | Share |
| --- | --- |
| always-won (even uniform-random wins) | 0.0% |
| always-lost (no policy wins) | 30.3% |
| contested (play decides) | 69.7% |
| **estimated ceiling** | **69.7%** |
| best measured policy | 40.3% |
| **remaining headroom** | **~29pp** |

Roughly 30 points of contested ground go unconverted by the best policy. **The
plateau is not deck variance** — there is real room, and further optimization
is justified. (A player-seat run gives 22.3% always-lost and a 77.7% ceiling;
absolute numbers shift with the seat, the conclusion does not.)

### The always-lost band is not actually unwinnable

Probing it with MCTS at 960 ms — same opponent, same seeds, only the agent's
strength changed — converts **8 of 30**, i.e. 26.7% (95% CI 10.8–42.5%). Those
seeds are hard, not lost. Correcting for it:

| | ceiling |
| --- | --- |
| partition alone (assumes always-lost is unwinnable) | 69.7% |
| corrected, low conversion (10.8%) | 73.0% |
| **corrected, point estimate (26.7%)** | **77.8%** |
| corrected, high conversion (42.5%) | 82.6% |

So the ceiling is ~78% and the headroom is **~37pp**, not 29. And that is still
a lower bound: MCTS at 960 ms is not optimal play either.

Note this reaches the same verbal conclusion as the *broken* first probe, which
swapped the opponent instead of the agent. That version's 11/25 was an artifact
of a different matchup and remains void; this one varies only the agent, which
is the comparison the claim requires.

Two bugs were fixed in this harness before its numbers meant anything:

- The probe swapped the **opponent** for MCTS instead of strengthening the
  **agent**. The always-lost seeds are defined against heuristic profiles, so
  it played a different matchup entirely; its 11/25 "these are winnable"
  result was meaningless. The corrected probe won 0/3 on a comparable sample.
- `evaluate_state` scores from `session.bot` and UCT alternates on
  `active_player == "bot"`, so MCTS only ever optimizes the bot seat. Probing
  from the player seat would have searched on behalf of the opponent.
  Partition and probe are now both pinned to the bot seat.

## V19 — sacrifice/discard targeting did not move the plateau

`hero_rl_env_v3` adds sacrifice and discard targeting at action indices 30-39
(v2's numbering is untouched, so its checkpoints stay loadable; models do not
transfer between the two). The engine defers these via
`HRPlayer.pending_choices` / `defer_choices`; with the flag off it resolves
inline exactly as before, verified byte-identical across 150 cases covering all
six choice-bearing cards.

Same BC + fine-tune recipe as V16. Held-out, n=600:

| Model | Win rate |
| --- | --- |
| greedy (v3) | 33.0% |
| V16 (v2) | 48.0% |
| **V19 best (v3)** | **50.0% ± 4.0pp** |

Difference **+2.0pp, 95% CI [-3.7, +7.7]** — not significant. An n=200 read
gave 51.5% and looked like a breakthrough; it did not survive n=600. Five
methods have now landed in the same band.

Caveat on V19 specifically: it trained in an env that deferred the *heuristic
opponent's* choices with nothing to answer them, silently deleting its
sacrifices and discards (~40 steps per game). That opponent was not the one the
v2 baselines were measured against. V19 still reads 50.0% against the corrected
opponent, so the distortion did not manufacture its result, but V20 reruns it
cleanly as the fair test.

## V20 — the clean rerun landed exactly on greedy

V19's caveat above (it trained against an opponent whose sacrifices and discards
were silently deleted) was retested with `defer_opponent` handled correctly.
Result, on the in-training eval seeds: BC clone 33.0%, fine-tuned **37.5%** —
**identical to greedy's 37.5% on the same seeds**, peaking at 43.0% around 450k
and oscillating with no trend for the remaining 550k steps.

So V19's +2.0pp was not reproduced by its own clean rerun. Six methods have now
landed in the ~45-50% band.

## V21 — the observation was broken, fixing it changed nothing

### The defects (real, and confirmed against the card set)

Every run from V15 to V20 shared v2's card encoding. Measured against the
96-card set:

| what | scope | status in v2 |
| --- | --- | --- |
| `ally_faction` | 55 of 96 cards | not encoded |
| `ally_*` payloads | 43 cards | not encoded |
| faction, per card | 80 of 96 cards | not encoded |
| `sacrifice_*` | 33 cards | counted as `c.get("sacrifice")` — **no such effect key exists**, so this input was a constant 0.0 since v15 |
| opponent deck composition | — | `_deck_features` called for self only |
| v3 choice candidates | actions 30-39 | actions exposed, candidates never encoded |

The last one predicts V20's result exactly: choosing among options the policy
cannot observe is choosing uniformly, and V20 finished at greedy's number. It
also reconciles with the play-data section above — Taxation, The Rot and Death
Touch all win on ally and sacrifice text, which is precisely what the policy
could never see.

`hero_rl_env_v4.py` repairs all six, keeping v3's action space byte-identical so
the comparison holds. Beyond raw one-hots it adds three derived features:
`has_ally(card, me)` (is the ally live *right now*, including cards played this
turn), own concentration in the card's faction, and own concentration in the
faction its ally needs. Verified live, not dead inputs: faction one-hots vary at
sd≈0.43, `ally_live` fires in 18.8% of states, opponent deck features at
sd≈0.20.

### The result

Three arms x three training seeds, V16's recipe otherwise unchanged, 500k
fine-tune steps. Held-out is seeds 900000+, n=600 per seed (1800 games per arm).

| arm | tuning (n=200) | held-out (n=600x3) | shift |
| --- | --- | --- | --- |
| A: v3 env (control) | 43.8% | **49.6% ± 1.3** | +5.8pp |
| B: v4 env, obs repair | 45.2% | **46.8% ± 2.6** | +1.6pp |
| C: v4 env + PBRS | 49.2% | **49.2% ± 1.6** | +0.1pp |
| V16 (v2 env) | — | 45.5% | |
| greedy (v3/v4 env) | — | 28.7% | |

- B − A = **−2.8pp**, SE 2.9, z=−0.98 — rules out effects beyond ±5.7pp
- C − A = **−0.4pp**, SE 2.1, z=−0.18 — rules out effects beyond ±4.1pp

**Neither the observation repair nor potential-based shaping moved held-out win
rate.** The control arm reproduces V19's 50.0%, which cross-checks the harness.
The defects were real and the information is now genuinely present in the
observation; the policy simply was not bottlenecked on it. `hero_rl_env_v4.py`
is kept as the correct env but is **not** promoted to default — nothing is
promoted without a confirmed held-out win.

### Two methodology traps this run walked into, recorded so the next one does not

**1. The in-training eval set cannot rank arms.** On tuning seeds the order was
C (49.2) > B (45.2) > A (43.8). Held out it was A (49.6) ≈ C (49.2) > B (46.8).
The ordering fully reversed, and every arm shifted upward by a different amount.
At n=200 one SE is 3.5pp while the arm differences were 1-5pp, so the sweep was
underpowered from the start. Rank arms on held-out seeds or not at all.

**2. Complete separation across training seeds is not a permutation test.** On
the tuning block every C seed (47.5 / 49.5 / 50.5) beat every A seed (40.5 /
44.5 / 46.5), which looks like an exact p=0.05. It did not survive held-out, and
the reason is structural: **training seeds vary the run, not the evaluation
set.** All three seeds of an arm are measured on the same 200 eval seeds, so any
arm-level bias on those seeds is common to all of them and the seeds are not
independent samples of the arm's performance. Between-seed spread understates
total uncertainty. Use disjoint eval seeds, or vary the eval set per seed.

### A bound worth keeping

Pending sacrifice/discard choices occur in **2.9% of decision states**. Even
perfect targeting there can only touch 3% of the policy's decisions, which caps
what V19/V20/v3's premise could ever have been worth and is consistent with all
three measuring nothing.

Tooling: `hero_rl_env_v4.py`, `hero_rl_train_v21.py` (parameterized, `--seed`
for independent runs), `hero_rl_eval_masked.py` (the first held-out evaluator
for masked envs — every earlier number came from an `evaluate()` defined inside
the training script that produced it), `hero_rl_summarize.py`,
`run_v21_ablation.sh`.

## The ceiling probe: search converts ~15pp, then saturates at ~55%

The standing claim above is a ~78% ceiling against ~50% best measured play, i.e.
~28pp unconverted. That correction rests on probing 30 always-lost seeds and
converting 8. This tests it a different way: instead of partitioning seeds by
whether *any* policy wins, give the strongest available agent more compute on
one fixed held-out block and see how much it actually converts.

Bot seat, held-out seeds 60000+, 40 games/profile (160/arm), same harness and
same seeds throughout:

| agent | balanced | aggressive | economic | champion | AVG | s/game |
| --- | --- | --- | --- | --- | --- | --- |
| heuristic (greedy) | 40.0% | 40.0% | 40.0% | 37.5% | **39.4%** | 0.03 |
| MCTS 60 ms (shipped) | 55.0% | 42.5% | 60.0% | 35.0% | **48.1%** | 0.80 |
| MCTS 240 ms | 55.0% | 57.5% | 62.5% | 50.0% | **56.2%** | 3.12 |
| MCTS 960 ms | 55.0% | 52.5% | 60.0% | 50.0% | **54.4%** | 12.21 |

| comparison | delta | z |
| --- | --- | --- |
| heuristic → 960 ms | **+15.0pp** | **2.72 (significant)** |
| heuristic → 60 ms | +8.7pp | 1.57 |
| 60 ms → 240 ms | +8.2pp | 1.46 |
| 240 ms → 960 ms | **−1.8pp** | −0.33 |

Two conclusions, and they point in opposite directions:

**1. Headroom above greedy is real and search converts it.** +15.0pp from
heuristic to MCTS at depth, z=2.72. This is the one clean positive measurement
in a long run of negatives, and it is a *search* result, not a training one.

**2. It saturates hard between 240 ms and 960 ms.** A 4x compute increase past
240 ms buys −1.8pp. The marginal value of search compute reaches zero at roughly
a quarter second per action, at about 55%.

So the ~78% ceiling is not reachable by more of this search, and the "~37pp of
headroom" framing should not be read as 37pp that more compute will collect.
What this bounds is *this algorithm's* asymptote (~55%), not what is achievable
in principle — the variance-ceiling partition measures a different quantity
(whether any policy in a set wins a seed) and is not refuted by this. But any
plan whose payoff depends on search converting the gap between 55% and 78% now
has a measurement against it.

### The budget lead did not replicate, and the reason matters

The obvious reading above was that the shipped 60 ms sits on the steep part of
the budget curve and leaves ~8pp on the table. Confirmed on a *disjoint* block
(300000+, 100 games/profile, 400/arm, 2.5x the power):

| budget | balanced | aggressive | economic | champion | AVG |
| --- | --- | --- | --- | --- | --- |
| heuristic | 47.0% | 53.0% | 54.0% | 50.0% | **51.0%** |
| MCTS 60 ms | 52.0% | 58.0% | 62.0% | 59.0% | **57.8%** |
| MCTS 240 ms | 56.0% | 58.0% | 56.0% | 58.0% | **57.0%** |

**60 ms → 240 ms = −0.8pp, z=−0.23.** The effect is gone. The +8.2pp on block
60000+ was that block's *60 ms arm reading low*, not its 240 ms arm reading
high. `budget_ms` stays at 60.

## The seed-block effect is ~10pp and invalidates cross-block absolutes

This is the most important measurement in this section and it was found by
accident. The same **fully deterministic** heuristic, same seat, same harness,
same opponents, n=160-400:

| seed block | heuristic | MCTS 60 ms | delta |
| --- | --- | --- | --- |
| 1000+ | 45.6% | 50.0% | +4.4pp |
| 60000+ | 39.4% | 48.1% | +8.7pp |
| 300000+ | 51.0% | 57.8% | +6.8pp |

The heuristic spans **11.6pp across blocks with no randomness in it at all**, and
MCTS spans 9.7pp. The paired *delta* is far more stable (4.4 / 8.7 / 6.8, mean
~6.6pp), which is exactly what `hero_mcts_bench.py`'s docstring already says:
the MCTS-minus-heuristic delta is the signal and the absolute number is not.

Consequences, and they are not small:

- **A single block cannot pin an absolute win rate to better than about
  ±10pp** at these sample sizes. Many absolutes recorded in this file are
  single-block numbers and should be read with that band.
- **Any comparison of two configurations measured on different blocks is
  worthless.** This is the mechanism behind both this session's false
  positives: ISMCTS d1 (+4.4pp tuning, −2.5pp held out) and the budget lead
  (+8.2pp on one block, −0.8pp on another).
- The right unit of measurement here is a **paired delta within one block**,
  never an absolute across blocks.

So the corrected reading of the ceiling probe: what search buys over greedy is
roughly **+6.6pp at 60 ms**, and more search buys approximately nothing. The
+15.0pp heuristic→960 ms figure above is inflated by block 60000+ having an
unusually weak heuristic arm, and should not be quoted on its own.

Reproduce with `ceiling_probe.log`'s three commands (`hero_mcts_bench.py
--games 40 --seed 60000 --budget {60,240,960}`), run sequentially: the budget is
wall-clock, so running them concurrently corrupts the result.

## Specialists: the plateau is not a generalization tax

Every run from V15 to V21 trained against `opponent_profile="random"` - one
policy against a mixture of four deterministic opponents. So nothing in this
repo separated "this is as well as the game can be played from this seat" from
"this is as well as one policy can play four opponents at once". The opponents
are deterministic given state, so they are exploitable in principle.

Four specialists, each trained 500k steps against a single fixed profile, two
training seeds each, v4 env. Measured against *that same profile* on held-out
seeds 900000+, n=300, alongside the three generalists from V21 arm B:

| profile | specialist | generalist | delta |
| --- | --- | --- | --- |
| balanced | 43.5% | 40.7% | +2.8 |
| aggressive | 46.3% | 41.8% | +4.5 |
| economic | 49.2% | 52.0% | −2.8 |
| champion | 46.2% | 46.2% | −0.1 |
| **mean** | | | **+1.1pp ± 1.6** |

**Training against nothing but one opponent does not beat that opponent any
better than training against all four.** Signs go both ways. So the plateau is
not a generalization tax, and these opponents are not sitting un-exploited.

Together with the ceiling probe this is two independent agents - a search agent
given 16x compute, and a learner given a single fixed target - stopping in the
same place.

### Training-seed noise is ~6pp, and it is not in any earlier number

The two training seeds of a *single* specialist configuration, on the same
held-out seeds, differ by:

| config | spread between two seeds |
| --- | --- |
| balanced | 8.4pp |
| economic | 7.0pp |
| aggressive | 6.0pp |
| champion | 3.7pp |

Every RL result in this file from V15 onward is **one training seed reported as
a point estimate**. So roughly ±6pp of each is run-to-run variance rather than
method. Combined with the ~10pp seed-block effect recorded above, this largely
explains why five or six methods "all landed in the same band": a good part of
the band is measurement, not the methods agreeing.

Minimum standard going forward: >= 3 training seeds, held-out evaluation, and
report the spread.

### A latent env bug found by pinning the opponent

`hero_rl_env_v3.py` could deadlock on an *unanswerable* deferred choice - a
sacrifice with nothing left in hand or discard. That choice sat at the head of
`pending_choices` and blocked everything: `_action_table()` returned empty while
the game was still live, so greedy crashed on `max()` over it, and a policy fell
through `action_masks`' ADVANCE fallback, which never clears the choice, burning
the episode to `max_steps=1000`.

This is latent in v3, the env **V19 and V20 both trained on**. With the
4-profile mixture it is rare enough to have gone unnoticed; pinning the opponent
to `economic` for all 3000 BC episodes hit it immediately. Any episode that
triggered it during V19/V20 contributed ~1000 steps of garbage. It does not
explain their results, but it is contamination that was not known about.

Fixed in `_pending()` by dropping choices with no legal candidate, matching the
engine's inline behaviour (an effect with no legal target resolves to nothing).
Covered by `tests/test_choice_actions.py::TestUnanswerableChoice`, including a
test that drives 40 full episodes asserting the action table is never empty
mid-game.

## The game-phase term made the bot worse (default unchanged)

Every Hero Realms strategy source consulted states the same timing rule as the
most important one: economy carries "a two-deck delay from the time you purchase
the economy card to the time you can play the card you purchased", so gold
bought late is never converted, while damage scales into the endgame. The bot
could not express this. `_resource_weights` ramps gold down and combat up, but
only against *opponent HP* - a proxy that fails exactly where it matters, since
two players at high HP on turn 20 are in a grind where gold is nearly worthless
and the proxy scores that identically to turn 2.

`GAME_PHASE_WEIGHT` (default 0.0) adds an explicit progress term:
`_game_progress` takes whichever is further along of turn count (against a
*measured* `EXPECTED_GAME_TURNS = 26`; median final turn_number 24.5, mean 26.1
over 48 games) and total HP depleted. Applied to `_resource_weights`, to
`_adaptive_buy_action` (the default *rollout* policy, so it reaches every MCTS
evaluation), and to the thinning bonus.

400 games/arm at 60 ms, within-block paired against a control in the same block:

| arm | balanced | aggressive | economic | champion | avg | delta |
| --- | --- | --- | --- | --- | --- | --- |
| w=0.0 (control) | 59.0% | 48.0% | 72.0% | 49.0% | **57.0%** | — |
| w=0.3 | 57.0% | 49.0% | 61.0% | 52.0% | 54.8% | −2.2 |
| w=0.6 | 58.0% | 50.0% | 62.0% | 46.0% | 54.0% | −3.0 |
| w=0.9 | 52.0% | 46.0% | 65.0% | 48.0% | 52.8% | −4.2 |
| heuristic (ref) | 45.0% | 40.0% | 56.0% | 43.0% | 46.0% | |

Monotone dose-response **in the wrong direction**, so this is a real effect and
not noise. `GAME_PHASE_WEIGHT` stays 0.0.

The likely mechanism is one this file already documents twice: the term was
applied to the rollout policy, and "a stronger rollout policy does not imply a
stronger search" (static 22.5% vs situational 15.8%). A greedier, more
domain-aware default policy narrows the distribution of simulated outcomes and
biases the value estimates. That is now three separate attempts to put domain
knowledge into the rollout, all negative. **The rollout is not the place to add
knowledge in this codebase.**

## The override gate is the mechanism that works, and it is already tuned

The shipped bot does not replace the heuristic with search. It runs the
heuristic as the default policy and lets MCTS deviate only when it clears
`_guarded_root_choice`. That is the only mechanism here with a confirmed win
behind it (49/80 vs 39/80, discordant 12-2, exact paired p=.013), and it had
never been swept.

`hero_override_ab.py`, 400 games/arm at 60 ms, tuning block, every arm on the
same seeds and compared by **exact McNemar on discordant games** rather than by
marginal win rate. Ordered by how often each gate actually lets search deviate:

| override rate | gate | win rate | vs shipped |
| --- | --- | --- | --- |
| 0.0% | heuristic (never) | 46.0% | 22-66, p<0.0005 |
| 3.1% | confidence z=2.0 | 50.0% | 26-54, p=0.002 |
| 4.0% | margin 0.15 | 50.5% | 13-39, p<0.0005 |
| **8.9%** | **margin 0.10 (shipped)** | **57.0%** | — |
| 16.8% | confidence z=1.0 | 55.0% | 35-43, p=0.428 |
| 20.8% | margin 0.05 | 55.0% | 43-51, p=0.470 |
| 41.4% | unguarded (-1.0) | 53.5% | 71-85, p=0.298 |

**An inverted U with the peak at the shipped setting.** Deviating on ~9% of
decisions beats both never deviating (46.0%) and deviating whenever search
prefers something else (53.5%). No arm beat the shipped gate. The good region is
a plateau over override rates of roughly 9-21%, not a knife edge, and the
failure is asymmetric: **tightening the gate hurts far faster than loosening
it.**

Ungated, search wants to overrule the heuristic on ~41% of decisions. The gate
admits 9%. The remaining ~32% are deviations that search believes in and that
cost win rate - at ~66 rollouts per decision, most are sampling noise.

Also worth knowing: `MCTS_OVERRIDE_MARGIN = 0.20` fires **0.0%** of the time -
it is silently identical to the pure heuristic. Anyone sweeping that value would
"discover" the heuristic twice.

### margin 0.00 is the same policy as unguarded, and it calibrated the harness

`proposed` is chosen as the max-mean-utility root child and `baseline_child` is
one of those same children, so `advantage = proposed_mean - baseline_mean` is
**always >= 0**. A margin of 0.00 therefore never blocks anything, exactly like
-1.0. Measured override rates confirm it: 41.1% vs 41.4%.

Those two identical policies scored **48.2% and 53.5%**, and against the shipped
arm gave **p=0.006 and p=0.298**. The same policy landed in two different
significance classes.

So **paired McNemar removes seed difficulty but not wall-clock jitter.** The
budget is wall-clock, so iteration counts drift with machine load and the same
configuration picks different moves between runs. Every p-value in the table
above is uncalibrated for that.

The fix, verified: run gate comparisons with `--iterations` instead of
`--budget`. Under a fixed simulation count the search is deterministic given the
seed - a same-config null replicate produces **0/0 discordant games**, and
margin 0.00 and unguarded become bit-identical as they must. `--null-control`
adds that replicate arm permanently, because a harness whose null is not
measured cannot support a p-value.

This is the third time a duplicate arm has exposed a noise floor here (ISMCTS
d1 vs d1+oppnodes, 2.5pp; the budget confirmation's block effect, ~10pp; this,
5.3pp). Duplicate arms have been more informative than any deliberate control.

## Play data vs the engine's valuation

Four months of real play (936 games, baseline **56.84%**; 2026 61.71% over 538,
2025 50.25% over 398). Per-card lift over the lifetime baseline, largest block:

| Card | n | lift | z | |
| --- | --- | --- | --- | --- |
| Taxation | 97 | **+23.2pp** | +5.7 | *** |
| The Rot | 74 | +11.2pp | +2.1 | ** |
| Death Touch | 107 | +9.2pp | +2.0 | ** |
| Influence / Spark / Profit / Recruit | ~90 | +5 to +7pp | ~1.0–1.4 | ns |
| Intimidation / Death Cultist / Elven Gift | ~78 | +1 to −5pp | ~0 | ns |

All three significant cards win on effects the engine priced at **zero**:
Taxation's Imperial ally grants 6 health; The Rot and Death Touch carry
`sacrifice_card`. `_card_score` and `_buy_priority` had no term for any
`ally_*` effect or for sacrifice access — 55 of 96 cards carry printed value
neither function could see. With default weights the engine ranks Taxation
**#54 of 55** and Death Touch **#53**.

Rank correlation between engine valuation and observed win rate:
`_card_score` −0.077, `_buy_priority` −0.196, `_holistic_card_score` +0.245.
The two without ally terms are flat-to-negative; the one with `_enabler_value`
is the only positive.

Caveat: these are win rates *conditional on purchase*, not causal effects, and
the two years pool different skill levels (50.25% → 61.71%).

## CMA-ES weight fitting did not work

`hero_weights.py` parameterizes both valuation functions (defaults reproduce
the original integer formulas exactly). `hero_cma_fit.py` fits them on
simulated win rate with common random numbers and rotating seed blocks.

**The fit is not credible and should not be adopted.** 25 generations x 120
games: held-out 32.0% → 34.3%, which is 0.6 standard errors. The trajectory
never converged (best-in-generation bounced 29–43% with no trend), and the
fitted vector prices **gold at −4.56, draw at −1.22, ally_health at −6.21** —
sign flips that contradict the game. 250 evaluations for 17 parameters at
~4.5pp noise each is far too faint a signal for CMA-ES to follow.

Testing the hypothesis directly with 2 parameters instead of 17, n=400
held-out:

| Weights | win rate | vs default |
| --- | --- | --- |
| default | 31.8% | — |
| + sacrifice terms | 31.8% | +0.0pp (ns) |
| + ally terms | 31.0% | −0.8pp (ns) |
| + both | 30.5% | −1.3pp (ns) |
| CMA-fitted | 32.5% | +0.8pp (ns) |

The CMA-fitted weights regressed from +2.3pp (n=300) to +0.8pp (n=400) —
regression to the mean, confirming noise.

**Power matters for reading this.** At n=400 per arm only effects above ~9pp
are detectable; ~2.6pp needs n=5000, ~1.3pp needs n=20000. So this rules out
*large* gains from ally/sacrifice pricing, not small ones. The play data's
+23pp on Taxation is a per-card conditional rate, not a claim that any single
weight change moves overall win rate by that much.

The likely blocker is the objective, not the optimizer: greedy win rate
against heuristic profiles appears too insensitive to buy ordering to fit
against at any affordable sample size. A margin-based fitness (HP differential
rather than binary win/loss) has far lower variance and is the obvious next
attempt before spending more compute on the search itself.

### Margin-based fitness (tried; also negative)

HP margin correlates 0.89 with winning and carries a continuous per-game
signal, so it should resolve differences binary win/loss cannot. It did, in
the fit loop: 40x150 games, mean −11.9 → −5.6hp, real convergence rather than
the win-rate version's noise. It did not transfer. Paired on identical held-out
seeds (n=600, same seed plays default and fitted):

  margin diff +0.87hp, SE 1.31, **z=0.67, ns**; fitted better in 42.5% of
  games, worse in 38.7%, tied 18.8% — a coin flip.

Both objectives now agree: tuning buy/card valuation does not move greedy's
result against these opponents.

### Why, most likely — reconciling with the variance ceiling

The ceiling section shows ~30-37pp of *contested* headroom, and a deep-search
MCTS converts some of it. But MCTS searches combat routing, sacrifice
targeting and tempo — not just buy ordering. CMA-ES here only tunes card
valuation, which feeds the *buy* decision. The coherent reading is that the
headroom lives in how cards are played, not primarily in which are bought in
what order: buy ordering is close to saturated for greedy, while play/combat
decisions are where the contested ground is. That matches the one thing that
did move the plateau being the full-action-space work, not any valuation
change.

### Domain caveat (added after seeing real game logs)

The play data that motivated all of this comes from the digital client's
**Hero** mode: custom hero starting decks (Cat Familiar, Fire Staff, Ignite,
Spell Components, Calm Channel/Channel) plus cards this engine does not model
(12 distinct ones seen in two logged games). The base engine starts every
player with `7 Gold + Shortsword + Dagger + Ruby` and no hero. So the card-lift
figures (Taxation +23pp, etc.) describe a richer game than the one being fit,
and are not expected to transfer cleanly. The code-level finding — that the
valuation has no ally or sacrifice term — is independent of this and stands.

The same logs independently **validate** several rules fixes against the real
client: first player draws 3 / second draws 5, Taxation's Imperial ally
auto-grants 6 health retroactively, The Rot's Necros ally adds +3 combat
retroactively (twice in one turn), stunned champions return the next turn, and
sacrifice_card banishes a card. All match this session's changes.

## Opponent-adaptation / RPS test (and a harness bug that voided the first run)

An opponent-strategy classifier only helps if the game has a strategy-dependent
best response — rock-paper-scissors. Tested with a six-strategy round-robin: the
four heuristic profiles plus two coherent archetypes (`rush` = cheap combat,
all-face, race; `sac_engine` = acquire sacrifice enablers, thin, go long).

**The first run was invalid.** `hero_roundrobin.py`'s turn loop discarded the
hand but never moved `played_this_turn` to the discard pile (the real
`GameSession.end_turn` does this via `discard_played_cards`). So every card
played vanished after one use, decks decayed to starters, combat collapsed to
0 by turn 4, and games ran 80+ turns. It produced a confident but fictional
conclusion — "champion dominates, no burst, needs Heroes." The project owner
caught it from game sense alone (real games last 15–25 turns; Elven Curse +
Elven Gift is 13 combat via Wild allies, not the 8 max my sim showed). The
engine itself was never wrong — only this standalone harness. RL results are
unaffected: the RL env drives the real `GameSession`, which recycles played
cards correctly.

With the fix (games now 11–14 turns), n=200, common seeds, agent draws 3 /
moves first. Mean win rate as agent: balanced 63%, aggressive 61%, champion 53%,
sac_engine 53%, economic 51%, rush 43%.

Aggression/tempo is strongest, which inverts the broken run. The claimed cycle
(rush beats the engine, engine beats grinders) still does not cleanly appear —
rush vs sac_engine is 45.5%, and sac_engine vs the grinders is 51.7% (even) —
but rush is now a viable racer (11-turn games) rather than a pass-bot. Best
response is aggressive or balanced depending on opponent (2 distinct), which is
a soft edge, not a strong cycle.

Given how badly the first version misled, no strong claim is drawn here about
whether opponent-adaptation is worth building. What is solid: the corrected base
game rewards tempo/aggression, and does not obviously exhibit the sharp
rush-vs-engine RPS an expert reports from Hero mode — which may still be a
Hero-mode property, but that is now a hypothesis, not a measured conclusion.

Tooling: `hero_archetypes.py`, `hero_roundrobin.py`, `hero_stance_matrix.py`.
The automated "distinct best-responses > 1 → RPS" flag is too loose (fires on a
near-dominant single response); read the matrix, not the flag.

## Champion denial is the biggest lever found (+~20pp)

Re-examining the corrected round-robin, seat-balanced (each pair played both
directions, n=250x2/cell, ~±2.2pp): balanced 59.8%, aggressive 59.0%,
sac_engine 49.7%, economic 47.9%, champion 45.3%, rush 38.3%. First-player
advantage is real and uneven (economic +10pp from moving first, aggressive ~0),
so seat-balancing was necessary — the raw "always agent A" numbers overstated
the slow strategies.

The interesting anomaly: pure aggression (rush) is the *worst*, below the slow
decks. Isolating why, with a clean A/B — `rush` (all-face) vs `rush_snipe`
(identical buys, but spends leftover combat clearing non-guard champions):

| opponent | rush | rush_snipe | delta |
| --- | --- | --- | --- |
| aggressive | 34.4% | 54.8% | +20.4 |
| economic | 38.6% | 61.2% | +22.6 |
| champion | 42.0% | 65.2% | +23.2 |
| sac_engine | 41.2% | 63.6% | +22.4 |
| balanced | 35.2% | 53.2% | +18.0 |

**Clearing enemy champions is worth ~20pp** — larger than any RL, self-play,
BC, or valuation effect measured this session. And it is *denial, not racing*:
game lengths are identical (~11–13 turns) and rush is the fastest at 11.4 while
still worst. The loss comes entirely from letting the opponent keep recurring
non-guard champions (gold/health engines that pay every turn). This is the
project owner's "almost never beneficial to let your opponent leave champions
out," measured.

It also re-explains the ranking: balanced/aggressive win because `attack_weakest`
already snipes champions; rush loses because `attack_rush` ignores them. The
strong heuristics already capture this. The open question is whether the
shippable MCTS bot does — its default `evaluate_state` is pure HP-diff and its
rollout horizon ends at its own turn, so it is theoretically blind to the
future-turn value an enemy champion denies.

## MCTS blind spot: it under-clears economy champions (confirmed)

Controlled combat-decision test: bot in the combat phase with enough combat to
kill one non-guard enemy champion and still hit face (not lethal), 20 trials per
champion at 300ms. Measured how often MCTS snipes the champion vs hits face,
against what the greedy `attack_weakest` fallback does.

| champion | recurring value | MCTS snipes | heuristic |
| --- | --- | --- | --- |
| Broelyn, Loreweaver | 2 gold / turn | **0%** | 100% |
| Rasmus, the Smuggler | 2 gold | 15% | 100% |
| Cult Priest | gold + combat | 25% | 100% |
| Tithe Priest | 1 gold | 35% | 100% |
| Cron, the Berserker | **5 combat** | 100% | 100% |
| Rayla, Endweaver | 3 combat | 90% | 100% |

The split is clean and matches the mechanism exactly. `evaluate_state` is pure
HP-diff and the rollout horizon is short, so a champion whose expend deals
*combat* shows up (the rollout takes that damage → worse HP-diff → MCTS kills
it, ~95-100%). A champion whose expend makes *gold* does not (economy denial has
no HP signature in the horizon → the search is indifferent → 0-35%). The greedy
fallback clears everything.

This is the ~20pp champion-denial lever, located inside the shippable bot: MCTS
systematically leaves enemy economy engines alive, and on this class of decision
its own greedy fallback plays better than the search. Fix path: give
`evaluate_state` (or the combat rollout) a term for enemy non-guard board value
so denial is priced, then A/B the win-rate delta. Not yet built — `evaluate_state`
is deliberately pure HP-diff (see its docstring), so changing it is a real design
decision, and the win-rate gain of the fix is inferred from the round-robin, not
yet directly measured.

## Fixing the blind spot: shaping term vs. longer horizon

Two approaches to the economy-champion blind spot, both targeting the same
controlled test (bot has spare combat over a lethal-safe threshold; how often
does it snipe a non-guard economy champion vs hit face).

**(a) Board-denial shaping term** (`DENY_BOARD_WEIGHT`, default 0). Prices the
recurring own-minus-enemy board output HP-diff misses. Weight 15 lifted Broelyn
0%→~40% and, in a first A/B (search eval, 60ms, 50 games/profile), scored +2pp
on tuning and +6pp on held-out — but held-out was z=1.40, **not significant**.
A powered confirmation was started, then pre-empted for approach (b); not yet
resolved. Weight 30 backfired (champion 10%), so over-shaping biases the search.

**(b) Longer rollout horizon** (`ROLLOUT_TURNS`, default 4). The more principled
fix: let the rollout run long enough that a surviving economy champion's gold
converts to cards → combat → HP, so pure HP-diff prices denial with no shaping.
Confirmed at the mechanism level (denial term off, 400ms):

| horizon | Broelyn (2 gold) | Tithe (1 gold) | Cron (5 combat) |
| --- | --- | --- | --- |
| 4 (current) | 0% | 35% | 100% |
| 8 | 50% | 45% | 100% |
| 12 | **85%** | 70% | 95% |
| 16 | 75% | 40% | **35%** |

Horizon 12 makes the search value economy denial on its own — this is the "gold
eventually converts into attack" mechanism, measured. But the horizon is not
free: `budget_ms` is wall-clock, so a longer rollout means fewer of them, and at
horizon 16 / 400ms the search starves so badly it stops clearing even the Cron
combat threat (100%→35%). Deeper buys depth at the cost of breadth; the sweet
spot is budget-dependent (~12 at 400ms).

### Horizon win-rate sweep — large, significant gain (at 200ms)

`hero_horizon_ab.py`, search eval, 200ms, 40 games/profile (160/arm). Win rate
climbs monotonically with horizon:

| horizon | balanced | aggressive | economic | champion | avg (tuning) |
| --- | --- | --- | --- | --- | --- |
| 4 (current) | 32.5% | 32.5% | 35.0% | 35.0% | 33.8% |
| 8 | 45.0% | 45.0% | 57.5% | 55.0% | 50.6% |
| 12 | 57.5% | 62.5% | 52.5% | 65.0% | **59.4%** |

Held-out confirmation (seeds 60000+, 160/arm): horizon 4 = 20.6%, horizon 12 =
48.8%, **+28.1pp, z=5.53, significant**. The delta is consistent on both seed
sets (+25.6pp tuning, +28.1pp held-out), so it is not selection bias. Horizon 4
here (20.6% held-out) matches its historical search-eval numbers, which
cross-checks the harness.

**This is the first confirmed win-rate improvement on the shippable bot in the
session** — and it is the project owner's idea, not a training-loop tweak.
Expanding the rollout so gold converts to attack is worth ~28pp at 200ms.

Caveats, held honestly:
- **Budget-specific.** Measured at 200ms; the interactive default is 60ms, where
  a horizon-12 rollout gets far fewer samples and may starve (the horizon-16 /
  400ms starvation shows the failure mode). The gain must be re-verified at the
  shipped budget before `ROLLOUT_TURNS` is changed — not yet done.
- **A sleep anomaly during the run.** Wall-clock segments were 895s / 12210s /
  1030s; the horizon-8 segment is ~12x horizon-12's, consistent with the machine
  sleeping mid-run. Win rates are game outcomes and independent of wall-clock,
  and the headline horizon-4-vs-12 comparison uses the two clean segments (895s,
  1030s), so the result stands — but horizon 8's row may have a few starved games
  and is treated as trend, not a precise number.

Next: sweep horizon at the 60ms interactive budget to find the budget-matched
sweet spot before adopting a new default.

## True ISMCTS did not beat root determinization (default unchanged)

The search had ISMCTS-flavoured comments but was not ISMCTS: `_paired_root_rounds`
sampled one world, cloned it once per root action, ran exactly one rollout per
branch and committed. The tree never went below depth 1, so no statistics were
ever shared across determinizations at an interior node — there were no interior
nodes. `MCTS_BUY_ROOT_WIDTH = 3` and `PAIRED_ROOT_MAX_ACTIONS = 3` existed to
stop visits spreading too thin, which is a symptom of having no tree to
concentrate them in.

Built proper single-observer ISMCTS (Cowling, Powley & Whitehouse 2012) behind
`ROOT_SAMPLING_MODE = "ismcts"`: one determinization per iteration, a persistent
tree keyed by information sets, UCB restricted to the actions legal in the
current determinization, expand / roll out / back up. Single-observer is the
right variant here because only one seat is being played and the opponent is
already a known policy class with a public posterior over it (see
`web/opponent_profiles.py`), so there is no second agent whose information sets
need their own tree — and at 60 ms there is budget for one tree, not two.

**No strategy fusion, structurally.** A node's identity is `info_key`: the
sequence of public actions from the root and nothing else. No sampled card, no
opponent hand, no draw order, no other product of determinization enters it, so
every determinization consistent with an action sequence lands on the same node.
The tree has nowhere to store "buy A when the hidden hand is X, B when it is Y".
The key is deliberately a *coarsening* of the bot's true information partition
(opponent public actions are left out to stop statistics fragmenting at 60 ms);
a coarsening averages, only a refinement past the information set would be
fusion. Covered by `tests/web/test_bot_search.py::TestISMCTS`.

### Budget reality, measured first

12 games at 60 ms/action. The committed search gets **65.6 rollouts per
decision**, not the ~28 recorded earlier in this file — that figure predates the
clone/telemetry fixes. So a tree is affordable. What each mode buys:

| mode | rollouts/decision | interior nodes/decision |
| --- | --- | --- |
| paired (committed) | 65.6 | **0** (by construction) |
| ismcts depth 2 | 49.0 | 12.3 |
| ismcts depth 3 | 50.6 | 29.3 |

ISMCTS loses ~25% of its iterations because it pays one determinization per
iteration where paired amortizes one across the ~2.7-action root fan. That is an
inherent cost of the method, not an implementation artifact.

Note depth 3 spreads ~50 iterations over ~29 interior nodes: **~1.7 visits per
interior node.** The tree is real but the statistics in it are not.

### Result: no configuration separated from the control

`hero_ismcts_ab.py`, 40 games/profile (160/arm), 60 ms/action, bot seat, tuning
seeds 1000+. Control is the committed `paired` search at the same budget, seat
and seeds — not a strawman.

| arm | balanced | aggressive | economic | champion | avg |
| --- | --- | --- | --- | --- | --- |
| **paired (committed control)** | 50.0% | 40.0% | 70.0% | 40.0% | **50.0%** |
| ismcts d1 (builds no tree) | 57.5% | 37.5% | 65.0% | 57.5% | **54.4%** |
| ismcts d1 +oppnodes (≡ d1) | 57.5% | 35.0% | 60.0% | 55.0% | **51.9%** |
| ismcts d2 | 55.0% | 32.5% | 62.5% | 40.0% | **47.5%** |
| ismcts d2 +oppnodes | 47.5% | 40.0% | 62.5% | 60.0% | **52.5%** |
| ismcts d3 | 52.5% | 42.5% | 67.5% | 35.0% | **49.4%** |
| ismcts d3 +oppnodes | 50.0% | 45.0% | 60.0% | 52.5% | **51.9%** |
| heuristic (same seat) | 42.5% | 37.5% | 57.5% | 45.0% | **45.6%** |

The four arms that actually build a tree (d2, d3, ±oppnodes) average **50.3%
over 640 games** against the control's 50.0% — z=0.07. **The tree buys nothing
at this budget.**

Held-out confirmation of the selected best arm (d1), seeds 60000+:

| arm | avg |
| --- | --- |
| paired (committed) | 50.0% |
| ismcts d1 | 47.5% |

**+4.4pp on tuning → −2.5pp held out, z=−0.45.** Textbook selection bias, and
the reason the sweep-then-confirm discipline exists. `ROOT_SAMPLING_MODE` stays
`"paired"`.

### The noise floor, measured accidentally and worth keeping

At depth 1 the descent breaks before `_advance_to_decision` is ever called, and
`ISMCTS_OPPONENT_NODES` is only read inside it — so `d1` and `d1 +oppnodes` are
the *same algorithm*. They scored 54.4% and 51.9% on identical seeds. That 2.5pp
(4-game) spread is pure wall-clock jitter changing how many iterations each
60 ms slice buys.

**Any MCTS arm in this harness carries ~2.5pp of irreducible noise that seeds do
not control for**, on top of sampling error. The `heuristic` row is unaffected
(45.6%, reproducing the standing figure exactly) because it is deterministic and
does not consume the budget. Two consequences: never read a sub-3pp MCTS gap as
real here, and prefer `--iterations` over `--budget` when the question is about
search *mechanism* rather than shipped performance.

Per-arm wall clock was 126–139 s across all nine segments, so this run has no
sleep anomaly of the kind that affected the horizon sweep.

### Opponent nodes: measured, and they stay in the rollout

Opponent nodes are implemented and gated (`ISMCTS_OPPONENT_NODES`, default off),
swept as their own arms rather than argued from preference. They land at 52.5%
(d2) and 51.9% (d3) against 47.5% and 49.4% without — inside the noise floor
above, so the measurement does not support turning them on.

The mechanism agrees with that read. Single-observer ISMCTS pools every opponent
information set sharing a public history, so the searched opponent cannot
condition on its own hidden hand, and it expands in the engine's public buy
priority order rather than as the sampled profile. It is therefore a *weaker and
differently-behaved* opponent than the profile posterior the rollout already
uses — while costing budget. Keeping the opponent in the rollout is both the
measured and the principled choice.

### Re-measured at fixed iterations: the tree was never fairly tested

The A/B above ran at a 60ms wall clock, which handicaps ISMCTS twice over. It
pays one `determinize_for_bot` per iteration where paired mode amortises one
across the whole root fan, so it ran **49 simulations to paired's 65.6** - a 25%
sample deficit before the algorithm acted - and it was scored against a ~4pp
wall-clock jitter floor that was not yet known.

Re-run at a fixed 40 simulations per decision, where the search is deterministic
given the seed and the null replicate reads exactly 0/0:

| arm | TUNE | vs paired | HOLDOUT | vs paired |
| --- | --- | --- | --- | --- |
| paired (control) | 55.2% | — | 53.2% | — |
| paired (null) | 55.2% | 0/0, p=1.000 | 53.2% | 0/0, p=1.000 |
| **ismcts depth 2** | **60.0%** | **72/53, p=0.107** | **55.0%** | **56/49, p=0.558** |
| ismcts depth 3 | 54.0% | 54/59, p=0.707 | — | — |

Pooled: **+26 net over 230 discordant pairs, p=0.099** (need +30 for p<0.05).

**The sign flipped.** At wall clock ISMCTS d2 was −2.5pp on both blocks; at equal
samples it is positive on both. Not significant, and the effect decayed +19 → +7
held out - but it held direction on the disjoint block, which none of this
session's six other candidates did.

Depth 3 measuring worse matches the earlier node-count measurement: ~12 interior
nodes at depth 2 versus ~29 at depth 3, i.e. ~4 visits per interior node versus
1.7. The tree becomes noise when spread that thin, and the result agrees with the
mechanism rather than being a post-hoc pick from a sweep.

**Reading:** the tree mechanism is probably mildly positive; it does not pay for
its determinization cost at 60ms. The actionable target is therefore making
`determinize_for_bot` cheaper or amortising it across iterations - it rebuilds a
Counter over ~100 cards and reshuffles on every call - not abandoning the tree.
`ROOT_SAMPLING_MODE` stays `paired` until that is resolved.

### Settled: negative, at equal simulation counts

Two more independent blocks at fixed 40 simulations per decision, following up
the +26/230 (p=0.099) reading above:

| block | discordant (ismcts/paired) | pooled net | pooled p |
| --- | --- | --- | --- |
| TUNE | 72/53 | +19 | 0.107 |
| HOLDOUT | 56/49 | +26 | 0.099 |
| BLOCK-C | 81/101 | +6 | 0.805 |
| BLOCK-D | 93/106 | **−7** | **0.808** |

**Final: −7 net over 611 discordant pairs, p=0.808.** The effect held through
two blocks - the best-powered positive signal measured all session - then
crossed zero and finished slightly negative. At equal simulation counts the tree
provides **no benefit**. This supersedes the "probably mildly positive" reading
above; `ROOT_SAMPLING_MODE` stays `paired`.

Worth keeping as the canonical illustration of why this file insists on a
disjoint confirmation block: two positive blocks in a row, at good power, still
missed a coin flip. See `CLAUDE.md` for the corresponding operating-manual note.

Structurally this rules out pooling statistics in one tree across
determinizations at depth 2-3 with these UCB settings - not determinization
sharing in general. See "Ensemble determinization" below for the other design
point in the same space.

## Ensemble determinization also lost - and lost cleanly

The other point in the determinization-sharing space: N independent trees, one
per determinization, combined only at the root (no statistics shared below it -
the opposite tradeoff from ISMCTS). This is the approach with actual external
evidence - it won the 2023 Tales of Tribute AI competition (a two-player
deckbuilder) as root-parallelised MCTS over five per-seed trees, and Cowling et
al. report it working for Magic: The Gathering.

`ROOT_SAMPLING_MODE="ensemble"`, `ENSEMBLE_TREES` controlling the split. A/B at
fixed 40 simulations (the null replicate reads exactly 0/0), swept over 3/5/10
trees, both blocks:

| trees | TUNE | HOLDOUT | pooled net | p |
| --- | --- | --- | --- | --- |
| x3 | 52.2% | 48.5% | −31 | 0.075 |
| x5 | 54.0% | 49.5% | −20 | 0.185 |
| x10 | 52.0% | 50.2% | −25 | 0.066 |

**Every tree count lost to `paired` on every block.** Unlike ISMCTS this never
had a positive phase - it read negative on the very first arm of the very first
block, which makes it a more trustworthy negative despite neither individual
result clearing significance alone.

Caveat worth keeping: at 40 total simulations split across even 3 trees, each
tree gets only ~13 iterations - likely too few to expand meaningfully before the
budget is gone. So this rules out ensemble *at this simulation budget*, not the
mechanism in general; a result at 200+ simulations per decision (splitting to a
still-workable ~20-65 per tree) has not been measured and would be needed before
concluding the competition-winning approach genuinely does not transfer here.
`ROOT_SAMPLING_MODE` stays `paired`.

### What this does and does not rule out

- **Ruled out:** that root-only determinization was the binding constraint on
  the shipped bot at 60 ms. It is not. The tree was built, it reaches depth 2–3,
  and it changes nothing.
- **Not ruled out:** that ISMCTS pays off at a larger budget. Every number here
  is at 60 ms, where the tree gets ~1.7 visits per interior node at depth 3. The
  horizon work already showed this bot's behaviour is strongly budget-dependent
  and crosses over between 240 ms and 960 ms. A fixed-iteration comparison at
  960 ms would answer the mechanism question the 60 ms budget cannot.
- **Not tested:** persisting the tree *across* decisions within a turn. Each
  `choose_bot_action` currently rebuilds the root from scratch, so the ~50
  iterations bought at the buy node are discarded before the combat node.

`_paired_root_rounds` is gated, not deleted; all three modes remain switchable
via `hero_mcts_bench.py --root-sampling`.

## The value network: cheap-and-noisy loses to slow-and-good

Prior art research pointed at the one combination never tried here: MCTS paired
with a learned value function, the mechanism behind every strong published
deckbuilder result (Dominion's shipped AlphaZero-style AI, the Tales of Tribute
competition winner's tuned weights). Built as `hero_value_net.py` -
`LEAF_EVAL_MODE="value_net"` replaces `_rollout`'s playout with a trained
network's forward pass, default off.

The target was never leaf accuracy - the horizon work above already showed
truncated HP-diff is a *good* estimator of the eventual outcome. The target was
**cost**: `_rollout` is ~1.6ms, the network is ~50us in isolation. Measured
whole-decision speedup at 60ms: **~13x** (33 iterations -> 438) - real, but far
short of the isolated-cost ratio, since cloning/apply_action/node bookkeeping
cost the same regardless of which leaf evaluator runs. Still the mechanism that
starved ISMCTS and ensemble determinization (as few as ~13 iterations/tree).

Two real bugs surfaced building this, both now regression-tested. The first
`TinyMLP.load` call costs ~330ms - enough to consume an entire 60ms budget on
its own, and `_paired_root_rounds` discards an incomplete round rather than
commit partial stats, so an unwarmed first call didn't run slow, it silently
returned `iterations=0`. And `_search_utility`'s nonterminal branch maps into
the *open* interval (0.1, 0.9), not (0,1); training labels average in exact
0.0/1.0 from rollouts that reach a real terminal (82-99% of them at
ROLLOUT_TURNS=16), so the network legitimately predicts outside (0.1, 0.9)
whenever confident, and the naive inversion crashed on `math.atanh` within the
first few games of the first real run.

Training itself needed real regularization: a first pass (200 positions, 8
rollouts/label) overfit badly enough that held-out MAE (0.34) was *worse* than
predicting a constant (0.11) - labels are strongly bimodal, so a handful of
noisy averages is not enough signal. Fixed with L2, a real validation split, and
early stopping. The shipped model (3000 positions, 20 rollouts/label) beat a
constant-prediction baseline on a held-out test split (0.309 vs 0.411 MAE) but
that is a modest margin, not a strong fit.

### Result: negative, cleanly

`hero_value_net_ab.py`, wall clock (the actual premise - more iterations at a
fixed time budget), 400 games/arm, seed block 1000+:

| arm | win rate | vs control | p |
| --- | --- | --- | --- |
| rollout (control) | 58.5% | - | - |
| rollout (null) | 58.0% | 4/6 | 0.754 |
| **value_net** | **53.2%** | **42/63** | **0.050** |

**−5.3pp against a clean null (4-6 discordant, p=0.754).** The harness's
own stopping rule ended it here rather than spending a holdout block on an arm
that lost on tuning. 13x more iterations of the cheap evaluator did not buy back
what each sample lost in fidelity - the same saturation shape as the 60->240ms
budget experiment, arrived at from the opposite direction (quantity vs quality
instead of raw compute).

**What this does and does not establish.** It shows *this* network - 3000
positions, ~24 hand-picked features, 0.309 held-out MAE against its own
training oracle - is not accurate enough to win back its speed advantage. It
does not cleanly separate "the value-net approach doesn't help this game" from
"this particular network is too inaccurate" - a substantially better-trained net
(more positions, more rollouts per label, or a richer feature set) has not been
ruled out, only this one. Given the size of the loss (5.3pp, not a coin flip)
and that model quality (MAE ~0.31) was already known to be mediocre going in,
the mechanism read is that leaf noise compounds through UCB selection faster
than raw iteration count can average it out - but that is inference, not a
second measurement.

## Root narrowing is load-bearing: widening it costs ~10pp

`_root_search_actions` narrows buy options to the top `MCTS_BUY_ROOT_WIDTH`
(default 3) by `_buy_priority` before the tree runs. Measured first: **48.5% of
buy decisions have more than 3 affordable options, and in every one of those at
least one legal card is excluded from search entirely** - MCTS never sees it,
at any iteration count.

That looked like a constraint worth removing. It is the opposite.
`hero_buy_priority_ab.py`, wall clock, 400 games/arm, block 1000+:

| arm | win rate | vs control | p |
| --- | --- | --- | --- |
| width=3 (SHIP) | 58.0% | - | - |
| null replicate | 58.5% | 18/16 | 0.864 |
| or_choice fix | 58.5% | 30/28 | 0.896 |
| **width=5** | **48.8%** | 47/84 | **0.002** |
| **width=0 (unlimited)** | **47.0%** | 62/106 | **0.001** |

Monotone (58.0 -> 48.8 -> 47.0), two independently significant arms, against a
null floor of +2 discordant games. At ~33 iterations per decision, three
branches is already thin; five or unlimited splits the budget past the point
where any branch accumulates enough visits to mean anything. **The same
breadth-versus-depth wall that killed ISMCTS and ensemble determinization, now
measured on the simplest possible tree.** `MCTS_BUY_ROOT_WIDTH` stays 3.

The conclusion inverts rather than closing the thread: since the bot *must*
narrow to three, **which three survive is critical**, and `_buy_priority` is
what decides that. See `hero_buy_fit.py`.

### Refitting _buy_priority: the ceiling is 0.13 HP, so there is nothing here

The narrowing being load-bearing implied *which* three options survive matters,
and `_buy_priority` decides that. `hero_buy_fit.py` fits its six weights against
a cached oracle - zero-variance objective (score every option once with
`MCTS_BUY_ROOT_WIDTH=0`, then evaluating a weight vector is a dot product),
minimising the value the top-K narrowing throws away. This is the fix for both
failures `BASELINE.md` diagnosed in `hero_cma_fit.py` (4.5pp noise per
evaluation; 17 parameters where only 6 touch buy ordering).

It works as designed and the answer is that the quantity barely exists. Over 400
sampled positions, oracle at 480 sims, no narrowing:

| | |
| --- | --- |
| top-3 by `_buy_priority` contains the oracle's best option | **92.5%** |
| top-1 by `_buy_priority` **is** the oracle's best option | 55.0% |
| value lost by width-3 narrowing | **0.131 HP** per buy decision |
| total stakes in a buy decision (best minus worst option) | 5.21 HP |
| → narrowing throws away | **2.5%** of available value |

**0.131 HP per decision is the ceiling**, reachable only by a perfect selector.
At ~12 buy decisions per game that is ~1.5 HP out of 50 - far below anything
this project can resolve, since the wall-clock noise floor alone is worth
several HP. No A/B was run: the ceiling makes the result a foregone conclusion
and an hour of benchmarking would only confirm it slowly.

The fit itself overfits in the textbook way - 4.7x improvement on the fit set
(0.00217 → 0.00046) against 1.07x held out (0.00194 → 0.00180) - and produces
`buy_gold = -7.01`, a *negative* weight on gold. That is the same sign-flip
pathology recorded for the original CMA-ES run ("prices gold at −4.56, draw at
−1.22 ... sign flips that contradict the game"), reproduced with a different
objective and a third of the parameters, which suggests the pathology is a
property of fitting this valuation at all rather than of that run's setup.

This also explains `hero_card_audit.py`'s finding. Mean |gap| of 0.26 in
within-position percentile ranking is real, but percentile mis-ranking is
almost irrelevant when the top-3 still contains the best option 92.5% of the
time. Bribe being overrated and Elven Gift underrated changes the *order*
inside the surviving set, not usually its *membership*, and the tree re-ranks
the survivors anyway.

### The or_choice double-count fix is correct and not demonstrably useful

`_buy_priority` summed mutually exclusive `or_choice` branches, scoring Street
Thug and Cult Priest as if both fired every activation. Fixed behind
`FIX_OR_CHOICE_DOUBLE_COUNT`. It changes real behaviour - 58 discordant games
on tuning against the null's 34.

| block | fix wins | control wins | net | p |
| --- | --- | --- | --- | --- |
| TUNE | 30 | 28 | +2 | 0.896 |
| HOLDOUT | 32 | 23 | +9 | 0.281 |
| **pooled** | 62 | 51 | **+11 / 113** | **0.347** |

Positive on both blocks, needs net > 21 for p<0.05 and has 11. **Not
promotable**, and the reason to disbelieve it is mechanistic rather than
statistical: the fix touches 2 of 55 cards, while a *perfect* narrowing
selector - the absolute ceiling for this whole class of change - is worth
0.131 HP per buy decision, roughly 1.5 HP per game out of 50. There is no route
by which a two-card ordering tweak is worth the +2.3pp the holdout block shows.
That is the shape of ISMCTS's false positive (+19, +26 pooled, p=0.099, then
−7 over 611 pairs), and the effect-size implausibility is the stronger tell.

Keep the fix for correctness. Default stays False; flipping it needs a reason
better than a p=0.35 that contradicts a measured ceiling.

## RL vs MCTS, head to head

`hero_rl_vs_mcts.py`, 30 games per policy, sides split evenly, MCTS in its
**best documented configuration** (960 ms, search-priced eval — the budget
where the sweep above shows it becoming competitive):

| Policy | vs MCTS | as player seat | as bot seat |
| --- | --- | --- | --- |
| Greedy heuristic | 43.3% | 26.7% | 60.0% |
| **V16 (BC + fine-tune)** | **60.0%** | 46.7% | 73.3% |

MCTS beats greedy at 960 ms (56.7–43.3), which matches the crossover in the
budget sweep. **V16 beats MCTS at MCTS's best budget**, at one forward pass per
move against ~960 ms of search.

At 300 ms with search eval — i.e. below the crossover — the same harness gives
greedy 58.3% and V16 70.0%. That configuration runs MCTS near its floor and
should not be quoted as a fair result; it is recorded only to show the budget
dependence.

### The seat matters enormously against MCTS

Against heuristic profiles the seat is nearly neutral (greedy 34.0% as player
vs 33.3% as bot). Against MCTS it swings by 27–33 points for both policies:
MCTS is far weaker in the player seat (moves first, 3-card opening) than in the
bot seat it was developed and benchmarked in — `evaluate_state` scores from
`session.bot`'s perspective, and every earlier MCTS number in this file comes
from that seat.

Any MCTS benchmark that does not split seats is measuring the seat. The
original version of this harness did not split them, and its docstring claimed
it did.

## Where this leaves MCTS vs RL

An earlier revision of this file claimed MCTS was "still the strongest thing
here". That was never supported by the data already recorded above: at the
60 ms budget the web UI uses, MCTS scores 14–20% against heuristic profiles
while its own greedy fallback scores 40%. MCTS only reaches parity with the
heuristic at 960 ms.

Corrected standing, by inference cost:

| | Strength | Cost per move |
| --- | --- | --- |
| Greedy heuristic | baseline | ~0 |
| MCTS @ 60 ms | **below** greedy | 60 ms |
| MCTS @ 960 ms | ~matches greedy, beats it head-to-head | 960 ms |
| **V16 RL** | beats greedy and beats MCTS@960ms | one forward pass |

The warm-started RL policy is the strongest option in the repo at interactive
speed. This reverses the earlier read, which rested on RL never having cleared
a naive heuristic — true of v14 and v15, not of v16.

Caveats that keep this provisional: 30 games per cell is roughly ±9pp, all RL
training used fixed heuristic opponents, and MCTS still searches only buy and
attack decisions (play/expend stay heuristic from the sample-starvation fix),
so a better-budgeted or fuller-search MCTS is not ruled out.

## Rules corrections applied

Verified against the [official base-set rules](https://www.herorealms.com/base-game-rules/):

- Market row is 5 face-up cards — already correct in `HRMarket`.
- Fire Gem stack is **16** cards; `hero_engine.py` had 15. Fixed.
- 50 starting health, 7 Gold / Shortsword / Dagger / Ruby deck, first player
  draws 3 and second draws 5 — all already correct, now covered by tests.
