"""Does Hero Realms have a strategy-dependent best response?

The opponent-strategy-signal idea assumes rock-paper-scissors: racing beats
the slow sacrifice/economy decks, grinding beats something else, so which
stance is best *depends on the opponent*. If instead one fixed stance quietly
beats every opponent, then reading the opponent buys nothing and a classifier
is wasted effort.

This measures the payoff matrix directly. Each agent stance is a buy-valuation
weight override (reusing hero_weights); each opponent is one of the four
heuristic profiles, which pick buys through their own local _buy_val and are
unaffected by the agent's weights. Common seeds down each column so stance
differences are not swamped by the shuffle.

The number that matters:

    adaptation value = (mean win rate if you always pick the best stance for
                        the opponent) - (mean win rate of the single best fixed
                        stance)

If that gap is large and the matrix has a strong off-diagonal, the opponent
signal is worth building. If one stance dominates every column, it is not.
"""
import sys

import numpy as np

import hero_weights as W
from hero_rl_env_v2 import HeroRealmsMaskedEnv

PROFILES = ["aggressive", "economic", "champion", "balanced"]

# Stances as buy_* weight overrides. Defaults: buy_cost 1, buy_combat 2,
# buy_gold 2, buy_draw 2, buy_ally 0, buy_sacrifice 0.
STANCES = {
    "default": {},
    "race": {"buy_combat": 4.0, "buy_gold": 1.0, "buy_cost": 0.0,
             "buy_sacrifice": -2.0},
    "econ": {"buy_gold": 4.0, "buy_sacrifice": 4.0, "buy_ally": 2.0,
             "buy_combat": 1.0},
}


def greedy_vs(profile, stance_weights, n, seed_base, agent_side="player"):
    env = HeroRealmsMaskedEnv(opponent_profile=profile, agent_side=agent_side)
    W.reset()
    if stance_weights:
        W.set_weights(stance_weights)
    wins = decided = 0
    for i in range(n):
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
    W.reset()
    return wins / max(decided, 1)


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 200
    seed_base = 400000

    matrix = {}
    print(f"Win rate, agent stance (row) vs opponent profile (column), n={n}\n")
    header = "stance".ljust(10) + "".join(p[:6].rjust(9) for p in PROFILES) + "   mean   worst"
    print(header)
    for stance, weights in STANCES.items():
        row = [greedy_vs(p, weights, n, seed_base) for p in PROFILES]
        matrix[stance] = row
        print(stance.ljust(10)
              + "".join(f"{v:8.1%}" for v in row).replace("%", "% ")
              + f"  {np.mean(row):5.1%} {min(row):5.1%}")

    print()
    # Best single fixed stance: the one with the best mean (and its worst case).
    means = {s: float(np.mean(r)) for s, r in matrix.items()}
    best_fixed = max(means, key=means.get)
    fixed_mean = means[best_fixed]

    # Oracle adaptive: for each opponent, take the best stance's cell.
    per_profile_best = [max(matrix[s][j] for s in STANCES) for j in range(len(PROFILES))]
    adaptive_mean = float(np.mean(per_profile_best))

    print(f"best single fixed stance : {best_fixed}  (mean {fixed_mean:.1%})")
    print(f"oracle adaptive (best stance per opponent): {adaptive_mean:.1%}")
    print(f"adaptation value = {(adaptive_mean - fixed_mean) * 100:+.1f}pp")
    print()
    # Is the best stance opponent-dependent? That is the RPS test.
    best_per = {PROFILES[j]: max(STANCES, key=lambda s: matrix[s][j])
                for j in range(len(PROFILES))}
    print("best stance per opponent:", best_per)
    distinct = len(set(best_per.values()))
    print(f"distinct best stances across opponents: {distinct}"
          + ("  -> strategy-dependent (RPS present)" if distinct > 1
             else "  -> one stance dominates (no RPS)"))
