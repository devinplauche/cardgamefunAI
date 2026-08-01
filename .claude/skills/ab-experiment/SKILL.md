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

## Sizing

400 games/arm (100 per profile) is the working default; a wall-clock arm is
~6 minutes. Under fixed iterations, power scales normally, so more games help.
Under a wall clock they do not below ~5pp, because the noise is inside the arms.

## Diagnose before you measure

Win rate needs thousands of games to see 3pp. **Decision-level regret** sees the
same in a minute and localises *which* decisions are lost: sample ~30 positions,
score every option with a heavy-rollout oracle (`max_iterations=1320`), and
compare each policy's pick to the oracle's. That measurement found buy decisions
are worth ~3.6 HP and combat ~0.6 HP, which explains a great deal of this
project's history. Use it to decide whether a win-rate A/B is even worth running.

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
