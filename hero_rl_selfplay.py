"""Self-play environment: the opposing seat is a frozen copy of the policy.

Every RL number so far is against the four fixed heuristic profiles, which
measures "beats these four bots" rather than general strength. V17 showed the
ceiling that implies - 1.5M further steps against those profiles produced
nothing, because there was nothing left to learn from them.

The opponent is drawn from a pool of frozen past snapshots rather than always
being the current policy. Playing only the newest version invites cycling
(A beats B beats C beats A) and catastrophic forgetting of how to punish
older, simpler strategies; sampling from history is the standard guard and
costs nothing but disk.

The opposing policy acts through the same action mapping the agent uses, asked
for its own seat's view via the side-parameterized helpers on the base env.
"""

import random

import numpy as np

from hero_rl_env_v2 import ADVANCE, HeroRealmsMaskedEnv


class SelfPlayEnv(HeroRealmsMaskedEnv):
    """Base env with the heuristic opponent replaced by frozen policies.

    Falls back to the heuristic profile whenever the pool is empty, so the very
    first rollouts before any snapshot exists still produce a real game.
    """

    MAX_OPPONENT_ACTIONS = 300  # a stuck opponent should fail loudly, not hang

    def __init__(self, opponent_pool=None, deterministic_opponent=False,
                 random_seat=False, **kwargs):
        super().__init__(**kwargs)
        self.opponent_pool = opponent_pool if opponent_pool is not None else []
        self.deterministic_opponent = deterministic_opponent
        # The seats are not symmetric and a mirror match is not 50/50: the same
        # policy playing both sides wins 60% from the bot seat (draws 5, moves
        # second) and 40% from the player seat. Training one seat only would
        # bake in that seat's assumptions.
        self.random_seat = random_seat
        self._current_opponent = None

    def reset(self, seed=None, options=None):
        # Pick opponent and seat before reset, since reset may hand the opposing
        # seat its opening turn immediately when the agent sits second.
        self._current_opponent = (random.choice(self.opponent_pool)
                                  if self.opponent_pool else None)
        if self.random_seat:
            self.agent_side = random.choice(("player", "bot"))
        return super().reset(seed=seed, options=options)

    def _opponent_turn(self):
        if self._current_opponent is None:
            return super()._opponent_turn()

        s = self.session
        foe = self._foe_side
        model = self._current_opponent
        for _ in range(self.MAX_OPPONENT_ACTIONS):
            if s.winner is not None or s.active_player != foe:
                return
            obs = self._get_obs(side=foe)
            mask = self.action_masks(side=foe)
            action, _ = model.predict(obs, action_masks=mask,
                                      deterministic=self.deterministic_opponent)
            table = self._action_table(side=foe)
            chosen = table.get(int(action)) or {"type": "advance_phase"}
            from web.bot import apply_action
            apply_action(s, chosen)
        raise RuntimeError(
            f"opposing policy exceeded {self.MAX_OPPONENT_ACTIONS} actions in one turn"
        )


def policy_win_rate(model, n=200, base=100000, profile="random", agent_side="player",
                    opponent_model=None):
    """Win rate against either a heuristic profile or a specific frozen policy.

    Self-play win rates against the current opponent hover near 50% by
    construction and say nothing about absolute strength, so progress has to be
    measured against something fixed.
    """
    env = (SelfPlayEnv(opponent_pool=[opponent_model], deterministic_opponent=True,
                       opponent_profile=profile, agent_side=agent_side)
           if opponent_model is not None
           else HeroRealmsMaskedEnv(opponent_profile=profile, agent_side=agent_side))
    wins = decided = 0
    for ep in range(n):
        obs, _ = env.reset(seed=base + ep)
        done = truncated = False
        reward = 0.0
        while not (done or truncated):
            action, _ = model.predict(obs, action_masks=env.action_masks(),
                                      deterministic=True)
            obs, reward, done, truncated, _ = env.step(action)
        if done:
            decided += 1
            wins += reward > 0
    return wins / max(decided, 1)


def greedy_win_rate(n=200, base=100000, profile="random", agent_side="player"):
    env = HeroRealmsMaskedEnv(opponent_profile=profile, agent_side=agent_side)
    wins = decided = 0
    for ep in range(n):
        env.reset(seed=base + ep)
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
