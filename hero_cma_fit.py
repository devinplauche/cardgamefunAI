"""Fit the card-valuation weights with CMA-ES.

Objective is **simulated win rate**, not a fit to the 936-game card table.
That table has ~10 usable rows with standard errors around 5pp and only three
significant entries; fitting 18 parameters to it would model its noise. Its
proper role is what it already did - telling us which terms were missing
(ally effects, sacrifice access) - plus an independent check afterwards: if
the fitted weights are picking up something real, they should rank Taxation,
The Rot and Death Touch above where the originals put them, without having
been shown those numbers.

Two things make the search tractable against a noisy objective:

  - **Common random numbers.** Every candidate in a generation plays the
    identical seed set, so differences between candidates are not swamped by
    which decks they happened to draw. Without this, a 120-game evaluation
    (SE ~4.5pp) cannot resolve the differences CMA-ES needs to follow.
  - **Rotating seeds per generation.** Fixing one seed set for the whole run
    would let CMA-ES overfit to those particular games. The seed block moves
    each generation, and the final comparison uses a held-out block neither
    the fit nor the model selection ever touched.

Usage:
    python hero_cma_fit.py [generations] [games_per_eval]
"""

import json
import sys
import time

import cma
import numpy as np

import hero_weights as W
from hero_rl_env_v2 import HeroRealmsMaskedEnv

FIT_SEED_BASE = 200000      # seeds used during the search
HOLDOUT_SEED_BASE = 900000  # never seen by the search or by model selection


MARGIN_CLAMP = 15  # hp; beyond this a game is decided, so do not reward overkill


def _play_greedy(env, seed):
    env.reset(seed=seed)
    done = truncated = False
    reward = 0.0
    while not (done or truncated):
        table = env._action_table()
        action = max(table, key=lambda k: table[k].get("priority", 0))
        _, reward, done, truncated, _ = env.step(action)
    me, foe = env._seats()
    return (reward > 0) if done else None, me.hp - foe.hp


def greedy_win_rate(n_games, seed_base, agent_side="player"):
    env = HeroRealmsMaskedEnv(opponent_profile="random", agent_side=agent_side)
    wins = decided = 0
    for i in range(n_games):
        won, _ = _play_greedy(env, seed_base + i)
        if won is not None:
            decided += 1
            wins += won
    return wins / max(decided, 1)


def greedy_margin(n_games, seed_base, agent_side="player"):
    """Mean clamped HP margin. Correlates 0.89 with winning but carries a
    continuous per-game signal where win/loss carries one bit, so a fixed
    game budget resolves policy differences the binary objective cannot.
    Clamped to +/-MARGIN_CLAMP so the fit sharpens the win boundary rather
    than rewarding 40-hp blowouts that are already decided wins."""
    env = HeroRealmsMaskedEnv(opponent_profile="random", agent_side=agent_side)
    total = 0.0
    for i in range(n_games):
        _, margin = _play_greedy(env, seed_base + i)
        total += max(-MARGIN_CLAMP, min(MARGIN_CLAMP, margin))
    return total / n_games


def evaluate(vector, n_games, seed_base, objective="margin"):
    """CMA-ES minimizes, so return the negated objective."""
    W.set_weights(W.from_vector(vector))
    try:
        if objective == "margin":
            return -greedy_margin(n_games, seed_base)
        return -greedy_win_rate(n_games, seed_base)
    finally:
        W.reset()


def empirical_check(weights):
    """Independent sanity check the search never optimized against.

    Reports where the three significant cards from the play data land in the
    engine's own ranking, before and after. Not a fit target - if these move
    up without having been shown, the fitted weights found the same thing the
    play data did.
    """
    from hero_engine import load_hero_cards, _card_score

    cards = load_hero_cards("data/hero_realms_cards.json")
    unique = {}
    for c in cards:
        unique.setdefault(c.name, c)
    targets = ["Taxation", "The Rot", "Death Touch"]

    def ranks():
        ordered = sorted(unique.values(), key=lambda c: -_card_score(c))
        pos = {c.name: i + 1 for i, c in enumerate(ordered)}
        return {t: pos[t] for t in targets}, len(ordered)

    W.reset()
    before, total = ranks()
    W.set_weights(weights)
    after, _ = ranks()
    W.reset()
    return before, after, total


if __name__ == "__main__":
    generations = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    n_games = int(sys.argv[2]) if len(sys.argv) > 2 else 120
    objective = sys.argv[3] if len(sys.argv) > 3 else "margin"

    x0 = W.to_vector(W.DEFAULTS)
    baseline = greedy_win_rate(300, HOLDOUT_SEED_BASE)
    print(f"Fitting {len(x0)} weights, {generations}x{n_games} games, objective={objective}")
    print(f"  default weights, held-out (n=300): {baseline:.1%}\n", flush=True)

    es = cma.CMAEvolutionStrategy(x0, 3.0, {"popsize": 10, "seed": 7, "verbose": -9})
    unit = "hp" if objective == "margin" else ""
    scale = 1.0 if objective == "margin" else 100.0
    incumbents = []  # per-generation best; ranked on a disjoint block afterwards
    start = time.time()

    for gen in range(generations):
        # Rotate the seed block so the search cannot settle into one sample.
        seed_base = FIT_SEED_BASE + gen * n_games
        candidates = es.ask()
        losses = [evaluate(c, n_games, seed_base, objective) for c in candidates]
        es.tell(candidates, losses)
        incumbents.append(candidates[int(np.argmin(losses))])
        print(f"  gen {gen + 1:2d}/{generations}  best-in-gen {-min(losses) * scale:.1f}{unit}  "
              f"mean {-np.mean(losses) * scale:.1f}{unit}  ({time.time() - start:.0f}s)", flush=True)

    # Per-generation bests were each scored on a different rotating block, so
    # they are not comparable to one another - the earlier version's rolling
    # best just picked the luckiest seed block. Re-rank the incumbents plus the
    # CMA mean on one validation block, disjoint from both fit and held-out.
    VAL_SEED_BASE = 500000
    pool = incumbents + [es.result.xbest]
    val = [-evaluate(v, 200, VAL_SEED_BASE, objective) for v in pool]
    best_vec = pool[int(np.argmax(val))]
    print(f"\n  selected on validation block: {max(val) * scale:.1f}{unit}", flush=True)
    fitted = W.from_vector(best_vec)
    print("\nFitted weights:")
    for k, v in fitted.items():
        print(f"  {k:16s} {W.DEFAULTS[k]:7.2f} -> {v:7.2f}")

    W.reset()
    base_margin = greedy_margin(300, HOLDOUT_SEED_BASE)
    W.set_weights(fitted)
    held = greedy_win_rate(300, HOLDOUT_SEED_BASE)
    held_margin = greedy_margin(300, HOLDOUT_SEED_BASE)
    W.reset()

    print(f"\nHeld-out (n=300, unseen by the search or selection):")
    print(f"  default  win {baseline:.1%}   margin {base_margin:+.2f}hp")
    print(f"  fitted   win {held:.1%}   margin {held_margin:+.2f}hp")
    print(f"  delta        {(held - baseline) * 100:+.1f}pp        {held_margin - base_margin:+.2f}hp")

    before, after, total = empirical_check(fitted)
    print(f"\nRank among {total} unique cards (never a fit target):")
    for name in before:
        print(f"  {name:12s} #{before[name]:2d} -> #{after[name]:2d}")

    with open("fitted_weights.json", "w") as fh:
        json.dump(fitted, fh, indent=2)
    print("\nSaved to fitted_weights.json")
