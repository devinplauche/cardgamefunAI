"""Reproducible evaluation harness for Hero Realms agents.

Every model is measured on the same seeded game set against each opponent
profile, alongside two reference points:

  heuristic  - the agent seat is driven by BalancedAI's own buy policy, so
               this is a mirror match. It isolates the seat disadvantage
               (agent goes first and draws 3) from actual policy skill, and
               is the number a trained agent has to beat to be worth using.
  random     - uniform random actions; the floor.

Usage:
    python hero_rl_eval.py                       # all *_final models
    python hero_rl_eval.py models_v12x/v12x_final heuristic random
    python hero_rl_eval.py --games 500 models_v13/v13_final
"""

from __future__ import annotations

import argparse
import glob
import random

import numpy as np

from hero_ai import _buy_val
from hero_engine import load_hero_cards
from hero_rl_env import OPPONENT_PROFILES, HeroRealmsEnv

CARDS_PATH = "data/hero_realms_cards.json"

# v11 was trained with the Fire Gem action disabled, so its policy head only
# emits 6 actions. Evaluating it in a 7-action env silently reinterprets
# "pass" as "buy Fire Gem" and the resulting number is meaningless.
NO_FIRE_GEM_MODELS = {"models_v11/v11_final"}


class RandomPolicy:
    n_actions = 7

    def predict(self, obs, deterministic=True):
        return random.randrange(self.n_actions), None


class HeuristicPolicy:
    """Mirror match: pick the slot BalancedAI would buy, else end the turn."""

    def __init__(self, env):
        self.env = env

    def predict(self, obs, deterministic=True):
        player = self.env.agent
        market = self.env.market
        # Same scoring rule as buy_balanced, applied one slot at a time so the
        # env's step() stays in control of the actual purchase.
        best_i, best_val = -1, -1
        for i, c in enumerate(market.row_cards()):
            if c is None or c.cost > player.gold:
                continue
            val = _buy_val(c, gold_weight=2, combat_weight=2, health_weight=1,
                           draw_weight=3, champ_weight=c.health // 2)
            val -= c.cost // 2
            if val > best_val:
                best_val, best_i = val, i
        if best_i >= 0:
            return best_i, None
        if player.gold >= 2 and market.can_buy_fire_gem():
            return 5, None
        return 6, None


def play_episode(policy, env, seed):
    random.seed(seed)
    np.random.seed(seed % (2**32))
    obs, _ = env.reset(seed=seed)
    done = truncated = False
    while not (done or truncated):
        action, _ = policy.predict(obs, deterministic=True)
        obs, _, done, truncated, _ = env.step(action)
    return env.winner == env.agent.name, truncated, env.turn


def evaluate(model_name, games, base_seed):
    allow_fg = model_name not in NO_FIRE_GEM_MODELS
    cards = load_hero_cards(CARDS_PATH)
    rows = {}
    for profile in OPPONENT_PROFILES:
        env = HeroRealmsEnv(cards, opponent_profile=profile, allow_fire_gem=allow_fg)
        if model_name == "heuristic":
            policy = HeuristicPolicy(env)
        elif model_name == "random":
            policy = RandomPolicy()
            policy.n_actions = env.action_space.n
        else:
            from stable_baselines3 import PPO
            policy = PPO.load(model_name)
        wins = truncs = 0
        turns = []
        for i in range(games):
            won, tr, t = play_episode(policy, env, base_seed + i)
            wins += won
            truncs += tr
            turns.append(t)
        rows[profile] = (wins / games, truncs, sum(turns) / len(turns))
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("models", nargs="*")
    ap.add_argument("--games", type=int, default=200)
    ap.add_argument("--seed", type=int, default=1000)
    args = ap.parse_args()

    models = args.models or (
        sorted(p.replace("\\", "/")[:-4] for p in glob.glob("models_v*/*_final.zip"))
        + ["heuristic", "random"]
    )

    print(f"{args.games} seeded games per opponent profile (seed base {args.seed})\n")
    header = f"{'model':<28}" + "".join(f"{p:>12}" for p in OPPONENT_PROFILES) + f"{'AVG':>9}"
    print(header)
    print("-" * len(header))
    for name in models:
        rows = evaluate(name, args.games, args.seed)
        avg = sum(r[0] for r in rows.values()) / len(rows)
        line = f"{name:<28}" + "".join(f"{rows[p][0]:>11.1%} " for p in OPPONENT_PROFILES)
        print(f"{line}{avg:>8.1%}")


if __name__ == "__main__":
    main()
