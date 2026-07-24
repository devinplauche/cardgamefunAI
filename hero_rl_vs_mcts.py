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
        """run_bot_turn only drives the "bot" seat. When the agent is seated
        there, MCTS holds the "player" seat instead, so the session's sides are
        swapped for the duration of the call and swapped back after."""
        s = self.session
        swap = self.agent_side == "bot"
        if swap:
            s.player, s.bot = s.bot, s.player
            s.active_player = "bot" if s.active_player == "player" else "player"
            if s.winner is not None:
                s.winner = "bot" if s.winner == "player" else "player"
        try:
            s.run_bot_turn()
            s._check_winner()
            if s.winner is None and s.active_player == "bot":
                # run_bot_turn ends its own turn; guard against a stall so a
                # stuck bot hangs visibly rather than looping forever.
                s.end_turn()
        finally:
            if swap:
                s.player, s.bot = s.bot, s.player
                s.active_player = "bot" if s.active_player == "player" else "player"
                if s.winner is not None:
                    s.winner = "bot" if s.winner == "player" else "player"


def greedy_pick(env, _obs):
    table = env._action_table()
    return max(table, key=lambda k: table[k].get("priority", 0))


def run_match(policy, n_games, budget_ms, seed_base=500000):
    """Half the games from each seat. The seats are close to neutral for greedy
    (34.0% vs 33.3% over 150 games each), but that is a measured result rather
    than an assumption, and it need not hold for a different policy."""
    envs = {side: MCTSOpponentEnv(budget_ms=budget_ms, opponent_profile="balanced",
                                  agent_side=side)
            for side in ("player", "bot")}
    tally = {"player": [0, 0], "bot": [0, 0]}
    truncs = 0
    start = time.time()
    for ep in range(n_games):
        side = "player" if ep % 2 == 0 else "bot"
        env = envs[side]
        obs, _ = env.reset(seed=seed_base + ep // 2)
        done = truncated = False
        reward = 0.0
        while not (done or truncated):
            obs, reward, done, truncated, _ = env.step(policy(env, obs))
        if truncated:
            truncs += 1
        elif reward > 0:
            tally[side][0] += 1
        else:
            tally[side][1] += 1
    wins = tally["player"][0] + tally["bot"][0]
    losses = tally["player"][1] + tally["bot"][1]
    return wins, losses, truncs, time.time() - start, tally


if __name__ == "__main__":
    n_games = int(sys.argv[1]) if len(sys.argv) > 1 else 50
    budget_ms = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    model_path = sys.argv[3] if len(sys.argv) > 3 else "models_v16/v16_final"

    model = MaskablePPO.load(model_path)

    def rl_pick(env, obs):
        return model.predict(obs, action_masks=env.action_masks(), deterministic=True)[0]

    print(f"{n_games} games vs MCTS @ {budget_ms}ms/move\n")
    for label, policy in (("greedy", greedy_pick), (model_path, rl_pick)):
        w, l, t, secs, tally = run_match(policy, n_games, budget_ms)
        rate = w / max(w + l, 1)
        seats = "  ".join(f"{s}:{v[0]}-{v[1]}" for s, v in tally.items())
        print(f"  {label:24s} {w}W {l}L {t}T -> {rate:.1%} vs MCTS   [{seats}]  ({secs:.0f}s)")
