"""How much of a game's outcome is the shuffle, and how much is the play?

Four training runs (V15-V18) converged on ~48% against the heuristic profiles
regardless of method. That is either a limit of the optimizers or a property of
the game: Hero Realms has large deck-shuffle variance, and if a substantial
fraction of seeds are decided before either side makes a real decision, then
the addressable headroom is much smaller than the gap from 48% to 100%.

Method: play several policies of widely differing strength through the *same*
seeds and partition the seeds three ways.

  - always-won    every policy wins, including uniform-random play
  - always-lost   no policy wins, including the strongest available
  - contested     the outcome depends on who is playing

Contested is the only band where policy quality can matter, so

    ceiling ~= always-won + contested = 1 - always-lost

is an estimate of the best achievable win rate. It is an estimate and not a
proof: a policy stronger than any tested here might convert some always-lost
seeds. Running a deep-search MCTS over a sample of them (--probe) tests exactly
that, and tightens the claim.

This is only meaningful because the profile draw is now seeded. Before that
fix, "the same seed" did not mean the same opponent, and this partition would
have been measuring the profile lottery instead of the shuffle.

Usage:
    python hero_variance_ceiling.py [n_seeds] [--probe N]
"""
import random
import sys

from sb3_contrib import MaskablePPO

from hero_rl_env_v2 import HeroRealmsMaskedEnv

SEED_BASE = 900000
MODELS = [
    ("v16_final", "models_v16/v16_final"),
    ("v18_best", "models_v18/v18_best"),
    ("v18_final", "models_v18/v18_final"),
]


def play(env, seed, pick):
    obs, _ = env.reset(seed=seed)
    done = truncated = False
    reward = 0.0
    while not (done or truncated):
        obs, reward, done, truncated, _ = env.step(pick(env, obs))
    return bool(done and reward > 0)


def greedy_pick(env, _obs):
    table = env._action_table()
    return max(table, key=lambda k: table[k].get("priority", 0))


def random_pick(env, _obs):
    return random.choice(list(env._action_table()))


def model_pick(model):
    def pick(env, obs):
        return model.predict(obs, action_masks=env.action_masks(), deterministic=True)[0]
    return pick


def collect(n_seeds):
    env = HeroRealmsMaskedEnv(opponent_profile="random")
    policies = [("random", random_pick), ("greedy", greedy_pick)]
    for label, path in MODELS:
        try:
            policies.append((label, model_pick(MaskablePPO.load(path))))
        except Exception as exc:  # noqa: BLE001
            print(f"  (skipping {label}: {exc})")

    results = {}
    for label, pick in policies:
        wins = [play(env, SEED_BASE + i, pick) for i in range(n_seeds)]
        results[label] = wins
        print(f"  {label:12s} {sum(wins) / n_seeds:.1%}")
    return results


def partition(results, n_seeds):
    labels = list(results)
    strong = [l for l in labels if l != "random"]
    always_won, always_lost, contested = [], [], []
    for i in range(n_seeds):
        outcomes = [results[l][i] for l in labels]
        strong_outcomes = [results[l][i] for l in strong]
        if all(outcomes):
            always_won.append(i)
        elif not any(strong_outcomes):
            always_lost.append(i)
        else:
            contested.append(i)
    return always_won, always_lost, contested


def probe_unwinnable(seeds, budget_ms=960, limit=20):
    """Can a deep search win the seeds every cheap policy lost?

    If it cannot, those seeds are unwinnable in practice and the ceiling
    estimate holds. If it can, the ceiling is higher than the partition says.
    """
    import web.bot
    from hero_rl_vs_mcts import MCTSOpponentEnv

    web.bot.EVAL_MODE = "search"
    env = MCTSOpponentEnv(budget_ms=budget_ms, opponent_profile="random")
    won = 0
    sample = seeds[:limit]
    for seed in sample:
        if play(env, SEED_BASE + seed, greedy_pick):
            won += 1
    return won, len(sample)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    n_seeds = int(args[0]) if args else 300
    probe = 0
    if "--probe" in sys.argv:
        probe = int(sys.argv[sys.argv.index("--probe") + 1])

    print(f"Variance ceiling over {n_seeds} shared seeds (base {SEED_BASE})\n")
    results = collect(n_seeds)
    won, lost, contested = partition(results, n_seeds)

    print(f"\n  always-won (even random wins) {len(won) / n_seeds:6.1%}  ({len(won)})")
    print(f"  always-lost (no policy wins)  {len(lost) / n_seeds:6.1%}  ({len(lost)})")
    print(f"  contested (play decides)      {len(contested) / n_seeds:6.1%}  ({len(contested)})")
    print(f"\n  estimated ceiling = 1 - always-lost = {1 - len(lost) / n_seeds:.1%}")

    best = max((sum(v) / n_seeds, k) for k, v in results.items() if k != "random")
    print(f"  best measured policy: {best[1]} at {best[0]:.1%}")
    head = 1 - len(lost) / n_seeds - best[0]
    print(f"  remaining headroom:   {head:.1%}")

    if probe and lost:
        print(f"\nProbing {min(probe, len(lost))} always-lost seeds with MCTS @960ms...")
        w, n = probe_unwinnable(lost, limit=probe)
        print(f"  deep search won {w}/{n} of them")
        if w:
            print("  -> ceiling is higher than the partition suggests")
        else:
            print("  -> these seeds look genuinely unwinnable; ceiling estimate holds")
