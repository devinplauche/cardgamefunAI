---
name: ab-experiment
description: Run or design an A/B experiment on the Hero Realms bot - comparing search settings, valuation knobs, rollout policies, card changes, or RL configs by win rate. Use whenever measuring whether a change to web/bot.py, hero_engine.py, or an RL env actually helps, or when writing a new hero_*_ab.py harness.
---

# Measuring a change to the Hero Realms bot

**Do not hand-roll a harness.** Use `hero_ab.paired_experiment`. Five hand-rolled
A/B scripts exist in this repo and three shipped bugs that produced confident,
plausible, wrong numbers.

```python
import web.bot as B
from hero_ab import Arm, paired_experiment
from hero_mcts_bench import play_game

def horizon(n):
    def setup():
        B.ROLLOUT_TURNS = n
    return setup

paired_experiment(
    arms=[Arm("horizon 16 (SHIP)", horizon(16)),   # arms[0] is always the control
          Arm("horizon 24", horizon(24))],
    play=lambda p, s: play_game(p, "mcts", 60, s, max_iterations=40)[0] == "bot",
    preflight=lambda a: f"ROLLOUT_TURNS={B.ROLLOUT_TURNS}",
    restore_module=B, restore_names=("ROLLOUT_TURNS",),
)
```

It inserts a null arm, pairs by seed, runs exact McNemar on discordant games,
reports the noise floor, and confirms any winner on a disjoint block.

## Decide this first: fixed iterations or wall clock?

| the question is about | use | why |
| --- | --- | --- |
| search *mechanism* (tree shape, gate, horizon, eval) | `max_iterations=40` | deterministic given seed; null arm goes to exactly 0 discordant; resolves ~1pp |
| shipped *wall-clock* performance | `budget_ms=60` | the real constraint, but carries a ~4-5pp jitter floor no sample size removes |

Default to fixed iterations. Before using it, confirm your change does not alter
the simulation count - report simulations per decision per arm. (Rollout horizon
does not alter it: rollouts nearly always end in a real result before reaching
their limit. Determinization strategy does: ISMCTS pays one per iteration.)

## Non-negotiables

1. **Null arm.** A byte-identical duplicate of the control. `paired_experiment`
   adds it automatically - never remove it. It has caught a noise floor four
   times when deliberate controls caught nothing, once reading +4.0pp at
   p=0.076, and once putting two provably identical policies into different
   significance classes (p=0.006 vs p=0.298).
2. **Never compare absolutes across seed blocks.** The same fully deterministic
   heuristic scores 45.6% / 39.4% / 51.0% on blocks 1000+ / 60000+ / 300000+.
   Only paired deltas within one block are meaningful.
3. **Confirm on a disjoint block.** Six candidate wins have died here. A tuning
   lead that shrinks held out is not a small win, it is a null.
4. **Preflight.** Assert the arm is doing what its label says. Prefer something
   observable - the config value, simulations per decision, a rate that should
   move. A Fire Gem "ban" once disabled search entirely and reported it as a
   card result.
5. **Exclusive CPU for wall-clock runs.** Contention starves the search. Launch
   detached, one at a time. Step-count RL runs parallelise safely.

## Profile before attributing a cost

`preflight` catches "is this arm configured the way its label says". It does not
catch "is my explanation for the result correct", which is a separate and
equally expensive mistake.

Worked example: ISMCTS ran 49 simulations to paired's 65.6 at a fixed wall
clock. The obvious story was that it pays one `determinize_for_bot` per
iteration where paired amortises one across the root fan, so the fix was to make
determinization cheaper. A two-minute `cProfile` showed determinization is 6.6%
of a single rollout and only ~3pp of a 14pp overhead gap - the rest is
tree-descent cost. The optimisation would have recovered a fifth of what was
claimed.

If a result rests on "X is expensive", measure X before acting on it. Unit costs
worth knowing here: `_rollout` ~1.6 ms, `determinize_for_bot` ~0.11 ms,
`clone` ~0.02 ms, `legal_actions` ~8 us and called ~250k times per profiled run.

Also: do not optimise toward an unconfirmed effect. Establish that the effect is
real first, or the best case is making an artifact shippable.

## Sizing

400 games/arm (100 per profile) is the working default; a wall-clock arm is
~6 minutes. Under fixed iterations, power scales normally, so more games help.
Under a wall clock they do not below ~5pp, because the noise is inside the arms.

## Diagnose before you measure — run `hero_regret.py` first

Win rate needs thousands of games to see 3pp. **Decision-level regret** resolves
in about a minute, has no game-outcome variance, and localises *which* decisions
are lost.

```bash
python hero_regret.py                      # buy and combat, 25 positions each
python hero_regret.py --positions 40 --oracle 2000
```

It reports, per phase: **stakes** (the oracle's best option minus its worst, so
how much choosing well is worth at all), **regret** (what each policy gives up),
and agreement with the oracle — all in HP, against a 50 HP starting total.

Use it to decide whether a win-rate A/B is worth running at all. If stakes at
the decision you are changing are ~0.5 HP, no policy change there will show up
in win rate and you should not spend an hour finding that out. Measured:

    phase     n   stakes   search regret   heuristic regret
    buy      25   3.6 HP          0.3 HP             1.2 HP
    combat   25   0.6 HP          0.1 HP             0.5 HP

Caveat: the oracle uses the same rollout the search does, so this is the
objective's opinion of itself. Near-zero stakes means *this objective does not
separate these options*, which is not the same as the options being equivalent —
they differ exactly when the objective is wrong. Combat reads 0.6 HP partly
because `_combat_search_actions` resolves the high-stakes cases by rule before
search ever sees them.

## Interpreting

- Effect below the null arm's separation: **not real**, whatever the p-value.
- Positive on tuning, gone on holdout: **null**. Do not promote.
- Positive on both, p > 0.05: pool the discordant counts and consider a third
  block. Watch for the effect shrinking as blocks arrive - that is a null
  revealing itself.
- Flips many games but nets ~zero: real behavioural change, no value. Worth
  recording; it usually means the thing is fungible.

Record outcomes in `BASELINE.md`, including negatives. Most results here are
negative and the record is what stops them being re-run.
