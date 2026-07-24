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


def greedy_win_rate(n_games, seed_base, agent_side="player"):
    env = HeroRealmsMaskedEnv(opponent_profile="random", agent_side=agent_side)
    wins = decided = 0
    for i in range(n_games):
        env.reset(seed=seed_base + i)
        done = truncated = False
        reward = 0.0
        while not (done or truncated):
            table = env._action_table()
            action = max(table, key=lambda k: table[k].get("priority", 0))
            _, reward, done, truncated, _ = env.step(action)
        if done:
            decided += 1
            wins += reward > 0
    return wins / max(decided, 1)


def evaluate(vector, n_games, seed_base):
    """CMA-ES minimizes, so return negative win rate."""
    W.set_weights(W.from_vector(vector))
    try:
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

    x0 = W.to_vector(W.DEFAULTS)
    baseline = greedy_win_rate(300, HOLDOUT_SEED_BASE)
    print(f"Fitting {len(x0)} weights, {generations} generations x {n_games} games")
    print(f"  default weights, held-out (n=300): {baseline:.1%}\n", flush=True)

    es = cma.CMAEvolutionStrategy(x0, 3.0, {"popsize": 10, "seed": 7, "verbose": -9})
    best_vec, best_fit = None, 0.0
    start = time.time()

    for gen in range(generations):
        # Rotate the seed block so the search cannot settle into one sample.
        seed_base = FIT_SEED_BASE + gen * n_games
        candidates = es.ask()
        losses = [evaluate(c, n_games, seed_base) for c in candidates]
        es.tell(candidates, losses)

        gen_best = min(losses)
        if gen_best < best_fit:
            best_fit = gen_best
            best_vec = candidates[int(np.argmin(losses))]
        print(f"  gen {gen + 1:2d}/{generations}  best-in-gen {-gen_best:.1%}  "
              f"mean {-np.mean(losses):.1%}  ({time.time() - start:.0f}s)", flush=True)

    fitted = W.from_vector(best_vec if best_vec is not None else es.result.xbest)
    print("\nFitted weights:")
    for k, v in fitted.items():
        print(f"  {k:16s} {W.DEFAULTS[k]:7.2f} -> {v:7.2f}")

    W.set_weights(fitted)
    held = greedy_win_rate(300, HOLDOUT_SEED_BASE)
    W.reset()

    print(f"\nHeld-out (n=300, unseen by the search):")
    print(f"  default weights {baseline:.1%}")
    print(f"  fitted weights  {held:.1%}   ({(held - baseline) * 100:+.1f}pp)")

    before, after, total = empirical_check(fitted)
    print(f"\nRank among {total} unique cards (never a fit target):")
    for name in before:
        print(f"  {name:12s} #{before[name]:2d} -> #{after[name]:2d}")

    with open("fitted_weights.json", "w") as fh:
        json.dump(fitted, fh, indent=2)
    print("\nSaved to fitted_weights.json")
