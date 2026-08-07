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
  (Street Thug and Cult Priest scored as if both mutually exclusive branches
  fire), not demonstrably useful: pooled **+11 over 113 discordant pairs,
  p=0.347** (+2 tuning, +9 held out). Disbelieved on effect size rather than
  p-value — it touches 2 of 55 cards, and a *perfect* narrowing selector is
  worth only 0.131 HP/decision, so there is no route to the +2.3pp the holdout
  suggests. Kept behind its flag for correctness, default False.
- **Refitting `_buy_priority`'s weights** (`hero_buy_fit.py`, zero-noise cached
  oracle, the fix for both failures diagnosed in `hero_cma_fit.py`). The
  top-3 already contains the oracle's best option **92.5%** of the time, so the
  narrowing loses **0.131 HP per buy decision out of 5.21 HP of stakes (2.5%)**.
  That 0.131 HP is the ceiling for a *perfect* selector — ~1.5 HP per game,
  below this project's noise floor. Not worth an A/B. The fit also reproduces
  the old CMA-ES sign-flip pathology (`buy_gold = −7.01`) with a different
  objective and a third of the parameters, which suggests it is a property of
  fitting this valuation rather than of that run's setup.
- **Exploitability against an exact best response (OpenSpiel).** The full game
  is ~10^177 histories against a ~10^7 budget, and no reduced variant that is
  still a deckbuilder fits either — see the dedicated section below for the
  scaling table and the one knob that actually drives the cost.

### The regret oracle cannot evaluate the override gate

`hero_regret.py`'s oracle is `choose_bot_action` at a high simulation count -
it *is* search. That is fine for "which card is better", where both candidates
are scored by the same yardstick and no bias falls between them. It is invalid
for "should I trust search or the heuristic", because the oracle systematically
agrees with search's own preference.

Measured, and the contradiction is the proof: by oracle regret, search alone
(0.550 HP) beats the shipped gate (0.939 HP), implying the gate should trust
search far more. By win rate, the gate sweep found an inverted U peaking at the
shipped ~9% override rate, with unguarded (41%) at 53.5% against the gate's
57.0%. Win rate is ground truth here; the oracle is measuring its own algorithm.

So gate calibration has no cheap ceiling measurement and would need win-rate
evidence, which at ~3pp effects needs thousands of games. The existing sweep
already indicates the global threshold is at or near its optimum, and the curve
is flat across 9-21% override rate (57.0 / 55.0 / 55.0), so the headroom for a
*learned* per-decision gate is real but unquantified and probably small.

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

## Exploitability via OpenSpiel: not computable at a useful scale

The motivation was sound and is still unaddressed: every number in this repo is
a win rate against four fixed heuristic profiles, which carries ~10pp
seed-block noise, saturates, and cannot say whether 58% is *good*. Exploitability
against an exact best response is an absolute measure that does not depend on
the opponent pool. OpenSpiel computes it. It cannot compute it here.

Reproduce every number below with `python hero_openspiel_probe.py all`.
`pip install open_spiel` resolves to 2.0.1 (cp314 win_amd64 wheel) and works;
that was never the obstacle.

**The budget.** Best response is O(#histories) — `BestResponsePolicy.value`
memoises on `state.history_str()`, so OpenSpiel has **no transposition table**
and pays separately for every action order that reaches the same state.
Measured throughput: 33k histories/s (leduc, C++ game), 25k/s (liar's dice),
8.5k/s for a Python game class. A Python game doing real card logic lands
below that, so "computable in minutes" means **~10^6–10^7 histories**.

**Wall 1 — the full game is ~10^177 histories.** Driven through the shipped
engine at 20.1 turns/game, 184.7 decisions/game, branching 5.90, 19.1 shuffles:
10^127.3 action histories x 10^49.3 chance outcomes. Information states never
repeat — 110,062 visits across 400 random-play games produced 110,062 distinct
information states, ratio pinned at 1.0000, no sign of saturating. A
combinatorial lower bound on three provably independent components alone (HP
pair x market row x both acquired decks) is 10^35.5. The gap is ~170 orders of
magnitude, which no engineering closes.

**Wall 2 — a reduced variant does not rescue it.** This is the part worth
keeping, because the blocker is not where you would guess:

| knob | cost |
| --- | --- |
| **+1 turn** | **~115x**, stable across the whole ladder |
| +1 market card | ~1.0–2.8x (4 cards cost 4.6x over 1) |
| +1 hand card | 3.5–14x above hand size 3 |

The market is nearly free; HP matters only through how many turns a game lasts.
Cost is driven by game *length* interacting with the free-order Main phase —
k commuting actions generate k! histories, and OpenSpiel pays for all of them.

Canonicalising the order of commuting actions is sound (plays → expends →
sacrifices → buys, with an attack closing the segment so buy-then-act and
attack-then-buy stay reachable; the probe asserts the reachable *state* set is
byte-identical either way) and buys 112–442x. Not close to enough:

| variant | free-order histories | canonical | BR time |
| --- | --- | --- | --- |
| 6 HP, 1 market card, 4 turns | 2.41e9 | 2.14e7 | 71 min |
| 8 HP, 2 market cards, 4 turns | 5.95e10 | 1.35e8 | 7.5 h |
| 6 turns, 1 market card | — | 3.20e11 | **2.0 yr** |

**The floor is set by when deckbuilding starts existing.** A bought card enters
the discard pile; with a 4-card deck and a 3-card hand it becomes drawable only
after a reshuffle — game turn 5–6 before it can be played and matter. Below
that, "deckbuilding" is buying cards you never see. Six turns with four market
cards is ~1.5e12 histories, about a decade of best response. The variants that
*do* fit in minutes (3 turns, or a single market card) cannot pose any of the
three questions this was for: exploitability of the shipped policy, whether the
override gate survives a best response, whether `MCTS_BUY_ROOT_WIDTH=3`
survives. Narrowing 4 buy options to 3 is not the same claim as narrowing 55.

**No game class was written, so there is no parity risk to carry.** The probe
sizes the tree with a compact model; nothing in it feeds a shipped number.

**What keeps the property that made this attractive.** Pool-independence does
not require *exact* best response. Freeze the shipped policy and train an
exploiter against it in the real engine (`hero_rl_train_v*.py`,
`hero_rl_vs_mcts.py`); the exploiter's win rate is a lower bound on
exploitability, measured on the real game with no reimplementation and
therefore none of the divergence risk that the Ruby bug and the phase ratchet
are warnings about. Untested — this is a direction, not a result.

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

## The phase ratchet — FIXED in d046b9e, and it moved the numbers

**Status: fixed.** `FREEFORM_TURN = True` in `web/session.py`; `MAIN_PHASE`
offers play/expend/sacrifice/buy/attack in any order, as many times as able.
The rest of this section is kept because it is the clearest worked example in
the project of a rules bug outranking every algorithm change, and because the
contamination it caused is still in the record.

**It cost search most of its remaining edge.** `rebaseline_main_phase.log`,
post-fix: heuristic **55.5%**, MCTS **56.8%** — a **+1.3pp** delta where the
post-Ruby reference was ~5pp. Same shape as the Ruby fix: correct the rules and
search's apparent advantage largely evaporates. Caveat before quoting it — one
seed block, marginal win rates, not paired McNemar. It needs a paired
confirmation before it replaces ~5pp as the reference delta. But do not quote
~5pp as if it were current either; both figures are now in doubt.

If the ~1.3pp holds it reframes the plateau: the gap between search and a
hand-written heuristic on this game may be about one point, in which case most
of the search-mechanism work in this file was chasing effects smaller than the
noise floor it was measured against.

### What the ratchet did while it was live

`GameSession` enforced `play → champion → buy → combat` one-way. The printed
rules have **Main → Discard → Draw**, and inside Main you may play, expend,
buy and attack **in any order, as many times as able**.

Measured consequence: Deception's Guild ally (`to_hand`) set
`next_buy_to_hand` correctly and the bought card really did land in hand — but
by then only `buy_card` and `advance_phase` were legal, so it could never be
played and was discarded unused. **The ally was a no-op.** Bribe and Rasmus
(`top_of_deck`) were *degraded* rather than dead — the card survived to next
turn's draw but lost the same-turn replay. Any line that wanted to buy-then-use,
or attack before buying, was unrepresentable.

These are precisely the hard-to-assemble, high-payoff Guild tempo lines (they
need Guild in play *plus* enough gold for a worthwhile target), so the loss was
concentrated in the plays that matter most when they land.

**Everything measured under the ratchet is contaminated, not just the card
audit.** `hero_card_audit.py` found Bribe overrated (policy 0.56 vs oracle
0.06, the table's largest gap) — but the oracle is search running in the
ratcheted engine, so it was correctly pricing a diminished card. That table
needs re-running. More broadly: every A/B in this file that predates `d046b9e`
was scored on a turn model that forbade buy-then-use and attack-then-buy, so
any result sensitive to action *sequencing* — which includes the override gate
sweep and the buy-root-width sweep — was measured on a different game.

**Corollary for testing:** this was found by a human playing the UI for ten
minutes, after 2800+ benchmark games missed it — along with a broken
champion-id in the frontend that made expend and champion-targeted combat fail
outright, and a Fire Gem the human literally could not buy. Benchmarks drive
the engine directly and feed its own action dicts back in, so they cannot see
anything in the UI layer or anything about whether the *rules* are right.
Play the game occasionally.

The sharper version of that test: **play a turn and insist on making every
decision yourself** — play, expend, activate, buy, attack, sacrifice, discard,
and every "choose one". Anything the game resolves without asking you is a
decision your agent also never gets to make. That is how both of this
project's real wins were found, and it is the check the next section came from.

## Decisions the engine still makes for the agent

The ratchet was one instance of a general failure: a decision that exists in
the printed rules but is unreachable in the engine cannot be searched, learned,
or A/B'd. It does not show up as a worse policy. It shows up as a plateau.

**`defer_choices` defaults to `False`, and only `hero_rl_env_v3.py` sets it.**
The MCTS bot never does. So `_find_worst_idx` — which by the note at
`hero_engine.py:342` fires **14.1 times per game** — is still choosing
sacrifice and discard targets *for* the bot. `hero_engine.py:142` describes
these as "the decisions a strong player spends the most thought on".

That is ~14 decisions per game, in a ~20-turn game, that search never sees.
`b06cff2` fixed the same class for `or_choice` and self-sacrifice. `auto_expend_all`
is worth auditing next on the same grounds.

Before tuning search again, check what search is allowed to decide. Twelve
algorithm interventions in this file are null or negative; the two changes that
actually moved the numbers were both "the agent could not do this at all".

### Audited: all 34 decision-bearing cards, driven through the live backend

`AGENT_CHOOSES_SACRIFICE` (`hero_engine.py`, default **False**) makes optional
sacrifices the agent's decision. Off, everything below behaves exactly as every
existing baseline measured it.

| effect | cards | who decides |
| --- | --- | --- |
| `or_choice` | Cult Priest, Street Thug, Darian, Tithe Priest | **agent** (both branches offered) |
| `sacrifice_combat` | Fire Gem, Influence, Word of Power, Nature's Bounty | **agent** under the flag (`sacrifice_played`) |
| `sacrifice_for_combat` | Lys, Krythos | **agent** under the flag (one action per victim) |
| `sacrifice_card` | Dark Reward, Death Touch, Life Drain, The Rot | **agent** under `AGENT_CHOOSES_TARGETS` |
| `discard` / `draw_up_to` | Elven Gift, Grak, Rampage | **agent** under `AGENT_CHOOSES_TARGETS` |
| `opponent_discard` | Elven Curse, Spark, Wolf Form, Torgen | engine, and it picks the *opponent's* card |
| `recycle` / `reanimate` | Smash and Grab / Varrick | engine |
| `sacrifice_up_to` | Tyrannor | engine, **deliberately** |

`AGENT_CHOOSES_TARGETS` (`hero_engine.py`, default **False**) turns on
`defer_choices` for a session's players and exposes the pending-choices queue
as `resolve_choice` actions — one per candidate card, plus a decline branch
when the printed text says "you may". While a choice is pending it is the
**only** legal action, so a half-resolved effect blocks everything else; that
is what makes it a decision point rather than a preference. Verified the bot
does not deadlock on it: 20/20 seeds faced the choice and resolved it
(`test_bot_can_play_a_whole_turn_with_targeting_on` spies on the action list so
it cannot pass vacuously).

Tyrannor is the cautionary one: gating `sacrifice_up_to` on the flag without an
action to replace it made the ability do *nothing*. "Sacrifice up to two cards"
is a multi-card selection that one expend action cannot express. **A dead
ability is strictly worse than an engine-resolved one** —
`test_sacrifice_up_to_still_fires_under_the_flag` pins it.

Every effect the engine resolves by itself now writes to `HRPlayer.effect_log`,
which `web/session.py` drains into the visible event log. Before this, Lys
removed a card from your hand and Fire Gem banished itself with nothing in the
log either time. Switched off for simulation clones (`log_effects`), since
`play_card` runs ~25k times per MCTS decision.

**Verified working, first time end to end:** Deception's `to_hand` ally. An
acquired card lands in hand and is playable the same turn — the effect the
phase ratchet made a no-op. `d046b9e` really did restore it.

**Settled rules question: guards must be stunned first.** `_attack_targets`
serves both combat and stun, so a stun offers only guards while any are alive.
That looked like the Guard keyword leaking into a non-attack ability; confirmed
against the printed cards that it is correct. Do not "fix" it.

**Still open: ally payload on expend** (`hero_engine.py`, "Ally effects on
expend"). `play_card` already pays a card's ally, immediately or retroactively
via `pending_ally`, so a champion played with a faction partner in play may be
paid there *and* again on every expend. Observed: Cult Priest paid +4 combat at
expend with no payout at play. Same shape as the `or_choice` double-count.
Needs the printed card before anything changes.

**Testing any card on demand:** start the backend with `HR_DEBUG_SETUP=1` and
`POST /api/sessions/{id}/debug-setup` with `hand`/`deck`/`discard`/`board`/
`opponentBoard`/`market`/`gold`/`combat`/`hp`. It took Fire Gem from twelve
turns of play to one call. Unknown card names raise rather than silently
dealing an empty hand. Off by default — it can rewrite any zone of a live game.
Match actions on `type` + `cardId`, never on `label`: stun cards label
themselves `"Fire Bomb → Wolf Shaman"`, which made them invisible to the first
sweep.

## Stale information warning

**There have now been two of these.** `BASELINE.md` predating the Ruby fix
describes a different game; everything in *either* file predating `d046b9e`
(the Main-phase fix) describes another one again. The MCTS-minus-heuristic
delta has read +11pp, then ~5pp, and post-Main-phase reads +1.3pp on one
unpaired block. Do not quote any of them as current without re-measuring.

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
- Tests: `python -m pytest -q` (355 passing, 69 subtests).
