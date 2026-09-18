# Task: replace root-only determinization with true Information Set MCTS

## Context you need before proposing anything

Read these first — do not plan before you have:

- `web/bot.py` — the whole search. Especially `choose_bot_action`,
  `_paired_root_rounds`, `_guarded_root_choice`, `_rollout`, `_search_utility`,
  and the block of tuning constants around `ROLLOUT_TURNS`.
- `web/session.py` — `determinize_for_bot`, `clone`, `legal_actions`.
- `web/opponent_profiles.py` — posterior inference over opponent buy profiles.
- `hero_mcts_bench.py` — the benchmark harness and its docstring on why the
  MCTS-minus-heuristic delta is the signal and the absolute number is not.
- `BASELINE.md` — the standing results and the discipline used to accept them.

## The actual problem

Despite the ISMCTS-flavoured comments, the current search is **not** ISMCTS. It
is flat Monte Carlo with root determinization:

- `_paired_root_rounds` samples one world, clones it once per root action, runs
  exactly one rollout per branch, and commits stats. The tree never goes deeper
  than depth 1.
- No statistics are shared across determinizations at interior nodes, because
  there are no interior nodes.
- `MCTS_BUY_ROOT_WIDTH = 3` and `PAIRED_ROOT_MAX_ACTIONS = 3` exist to stop
  visits being spread too thin — a symptom of having no tree to concentrate
  them in.
- Everything below the root is `_rollout`, a fixed greedy policy to
  `ROLLOUT_TURNS = 16`.

So the search cannot represent "buy this, and then next turn the position is
good *because of how I will play it*." It only measures "buy this, then play
greedily for 16 seat-turns."

## What to build

True ISMCTS (Cowling, Powley & Whitehouse, 2012 — single-observer ISMCTS is
the right variant here; justify if you disagree):

1. Determinize a world at the **start of each iteration**, from the bot's
   information set.
2. Descend a **persistent tree keyed by information sets**, not by concrete
   states, using UCB over only the actions legal in the current determinization
   (this is the subset-armed bandit that makes ISMCTS correct).
3. Expand, roll out with the existing `_rollout`, back up along the visited
   path.
4. Statistics **persist across determinizations** — that is the entire point,
   and the thing the current code does not do.

Requirements:

- Guard against strategy fusion. The tree must never assume the bot can
  condition on hidden information it does not have. Say explicitly how your
  node keying achieves this.
- Opponent nodes must exist and be handled correctly. Currently rollouts model
  the opponent with a sampled profile policy; decide whether the opponent gets
  real tree nodes or stays in the rollout, and justify it with a measurement,
  not a preference.
- Keep the existing knobs switchable so the old path remains an A/B control.
  Do not delete `_paired_root_rounds` — gate it.
- The 60ms interactive budget is the shipping constraint. A correct ISMCTS that
  is too slow to get meaningful iterations at 60ms is a loss, not a win.

## How results will be judged

This project has been repeatedly bitten by selection bias, and there is an
explicit discipline for it — follow it:

- Sweep/tune on one seed block, **confirm the winner on a disjoint held-out
  block.** Report a z-score.
- The comparison that matters is against the current committed search at the
  same budget, seat, and seeds — not against a strawman.
- `hero_mcts_bench.py` reports both `mcts` and `heuristic` in the same seat.
  The delta is the signal.
- Current standing to beat, 40 games/profile at 60ms:
  `mcts 51.9% (balanced 50.0 / aggressive 40.0 / economic 75.0 / champion 42.5)`
  vs `heuristic 45.6%`.
- The measured variance ceiling on this game is roughly 78% — see the variance
  ceiling work in `BASELINE.md`. Do not report a small delta as a win without
  the power to support it.
- A run whose wall-clock segments look wildly uneven probably had the machine
  sleep mid-run. Win rates are outcome-based and survive that, but say so
  rather than quietly reporting the timing.

## Ground rules

- Do not flip a default to a new value until it is confirmed on held-out seeds
  at the shipped budget.
- All 271 tests must keep passing; add tests for the information-set keying and
  the no-fusion property specifically.
- If ISMCTS does not beat the current search, say so plainly and keep the
  default. A negative result recorded honestly is the expected outcome of most
  of these experiments and is worth more than a flipped default that regresses.
- Long benchmark runs should be launched detached with output to a log file;
  they take hours.
