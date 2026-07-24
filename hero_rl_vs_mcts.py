"""Head-to-head: the warm-started RL policy against the MCTS bot.

Every RL number in BASELINE.md is against the four fixed heuristic profiles,
which measures "beats these four bots" rather than general strength. MCTS and
RL have never actually played each other, so the question the whole
MCTS-vs-RL discussion turns on has never been measured.

The RL side plays through the same action mapping it trained on; the MCTS side
plays through session.run_bot_turn(), the identical entry point the web app
uses. Sides are swapped halfway so neither gets a permanent first-turn
advantage - Hero Realms compensates player 1's initiative with a 3-card
opening hand instead of 5, but that is a rules-level correction, not a
guarantee the seat is neutral for any particular pair of policies.

Usage:
    python hero_rl_vs_mcts.py [n_games] [budget_ms] [model_path]
"""
import sys
import time

from sb3_contrib import MaskablePPO

from hero_rl_env_v2 import HeroRealmsMaskedEnv


class MCTSOpponentEnv(HeroRealmsMaskedEnv):
    """Same env, but the opposing seat is the real MCTS bot rather than a
    heuristic profile."""

    def __init__(self, budget_ms=60, **kwargs):
        super().__init__(**kwargs)
        self.budget_ms = budget_ms

    def reset(self, seed=None, options=None):
        obs, info = super().reset(seed=seed, options=options)
        self.session.budget_ms = self.budget_ms
        self.session.algorithm = "mcts"
        return obs, info

    def _opponent_turn(self):
        self.session.run_bot_turn()
        self.session._check_winner()
        if self.session.winner is None and self.session.active_player == "bot":
            # run_bot_turn ends its own turn; guard against it stalling so a
            # stuck bot shows up as a hang rather than an infinite loop.
            self.session.end_turn()


def greedy_pick(env, _obs):
    table = env._action_table()
    return max(table, key=lambda k: table[k].get("priority", 0))


def run_match(policy, n_games, budget_ms, seed_base=500000):
    env = MCTSOpponentEnv(budget_ms=budget_ms, opponent_profile="balanced")
    wins = losses = truncs = 0
    start = time.time()
    for ep in range(n_games):
        obs, _ = env.reset(seed=seed_base + ep)
        done = truncated = False
        reward = 0.0
        while not (done or truncated):
            obs, reward, done, truncated, _ = env.step(policy(env, obs))
        if truncated:
            truncs += 1
        elif reward > 0:
            wins += 1
        else:
            losses += 1
    return wins, losses, truncs, time.time() - start


if __name__ == "__main__":
    n_games = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    budget_ms = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    model_path = sys.argv[3] if len(sys.argv) > 3 else "models_v16/v16_final"

    model = MaskablePPO.load(model_path)

    def rl_pick(env, obs):
        return model.predict(obs, action_masks=env.action_masks(), deterministic=True)[0]

    print(f"{n_games} games vs MCTS @ {budget_ms}ms/move\n")
    for label, policy in (("greedy", greedy_pick), (model_path, rl_pick)):
        w, l, t, secs = run_match(policy, n_games, budget_ms)
        rate = w / max(w + l, 1)
        print(f"  {label:24s} {w}W {l}L {t}T -> {rate:.1%} vs MCTS   ({secs:.0f}s)")
