"""Held-out evaluation for masked-env agents (v2 / v3 / v4).

hero_rl_eval.py drives the *v1* buy-only env and cannot load these models at
all. Every masked-env number in BASELINE.md came from an evaluate() defined
inside whichever training script produced it, which means the reporting harness
and the model were never independently varied.

Discipline enforced here:
  - Held-out seeds (900000+) by default. Training and in-training eval use
    0+ and 100000+ respectively; reusing either overstates by ~2pp (BASELINE's
    V17 section measures exactly that).
  - The model's env version must be declared, because obs width differs between
    v2/v3/v4 and a mismatched load is a silent nonsense number rather than an
    error in some sb3 versions.
  - `greedy` is evaluated in the *same* env version as the model it is being
    compared against, on the same seeds. BASELINE already records greedy
    scoring 37.5% on one seed set and 30.6% on another; comparing across seed
    sets is the mistake that section warns about.
  - Win is read from session.winner, never the sign of the final reward, so
    shaped and unshaped arms are scored identically.

Usage:
    python hero_rl_eval_masked.py --env v4 --games 600 models_v21/v21_obs_s0_final
    python hero_rl_eval_masked.py --env v4 --games 600 greedy random
"""
from __future__ import annotations

import argparse
import math
import random

import numpy as np

HELDOUT_SEED_BASE = 900_000


def make_env(version, shaping=0.0, profile="random"):
    if version == "v2":
        from hero_rl_env_v2 import HeroRealmsMaskedEnv

        return HeroRealmsMaskedEnv(opponent_profile=profile, fire_gem_penalty=-0.01)
    if version == "v3":
        from hero_rl_env_v3 import HeroRealmsChoiceEnv

        return HeroRealmsChoiceEnv(opponent_profile=profile, fire_gem_penalty=-0.01)
    if version == "v4":
        from hero_rl_env_v4 import HeroRealmsRichObsEnv

        return HeroRealmsRichObsEnv(opponent_profile=profile, fire_gem_penalty=-0.01,
                                    shaping_weight=shaping)
    raise ValueError(f"unknown env version: {version}")


def policy_for(name, env):
    if name == "greedy":
        return lambda e, o: max(e._action_table(),
                                key=lambda k: e._action_table()[k].get("priority", 0))
    if name == "random":
        def act(e, o):
            legal = np.flatnonzero(e.action_masks())
            return int(random.choice(legal))
        return act
    from sb3_contrib import MaskablePPO

    model = MaskablePPO.load(name)
    expected = env.observation_space.shape[0]
    actual = model.observation_space.shape[0]
    if expected != actual:
        raise SystemExit(
            f"{name} expects obs_dim {actual} but --env gives {expected}; "
            "declare the env version the model was trained on"
        )
    return lambda e, o: model.predict(o, action_masks=e.action_masks(),
                                      deterministic=True)[0]


def evaluate(name, version, games, base, profile):
    env = make_env(version, profile=profile)
    policy = policy_for(name, env)
    wins = 0
    for episode in range(games):
        random.seed(base + episode)
        obs, _ = env.reset(seed=base + episode)
        done = truncated = False
        while not (done or truncated):
            obs, _, done, truncated, _ = env.step(policy(env, obs))
        wins += env.session.winner == env.agent_side
    env.close()
    return wins / games


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("models", nargs="+", help="checkpoint paths, or 'greedy' / 'random'")
    ap.add_argument("--env", choices=["v2", "v3", "v4"], required=True)
    ap.add_argument("--games", type=int, default=600)
    ap.add_argument("--seed", type=int, default=HELDOUT_SEED_BASE)
    ap.add_argument("--profile", default="random",
                    help="opponent profile, or 'random' for the seeded mixture")
    args = ap.parse_args()

    print(f"env={args.env} n={args.games} seeds {args.seed}+ opponent={args.profile}")
    standard_error = math.sqrt(0.25 / args.games)
    print(f"one SE at this n is {standard_error * 100:.1f}pp; a difference needs "
          f"~{1.96 * standard_error * math.sqrt(2) * 100:.1f}pp to clear noise\n")
    print(f"{'policy':<40}{'win rate':>10}")
    print("-" * 50)
    results = {}
    for name in args.models:
        rate = evaluate(name, args.env, args.games, args.seed, args.profile)
        results[name] = rate
        print(f"{name:<40}{rate:>9.1%}", flush=True)

    if len(results) == 2:
        (name_a, rate_a), (name_b, rate_b) = results.items()
        se = math.sqrt(rate_a * (1 - rate_a) / args.games
                       + rate_b * (1 - rate_b) / args.games)
        if se > 0:
            z = (rate_b - rate_a) / se
            print(f"\n{name_b} - {name_a} = {(rate_b - rate_a) * 100:+.1f}pp  "
                  f"z={z:.2f}  {'SIGNIFICANT' if abs(z) > 1.96 else 'not significant'}")


if __name__ == "__main__":
    main()
