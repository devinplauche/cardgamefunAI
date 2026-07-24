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
