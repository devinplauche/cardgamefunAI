"""Action space extended with sacrifice and discard targeting.

These are the decisions the project owner identifies as among the most
important in the game, and until now no agent could make them: the engine
resolved them inline via _find_worst_idx the moment the effect fired. Four
training runs (V15 self-taught, V16 warm start, V17 extended, V18 self-play)
converged on the same ~48% band without ever touching them.

Kept as a subclass with its own action layout rather than widening v2, so the
existing baselines and checkpoints stay loadable and comparable. Models are not
transferable between the two: the action space is a different size.

Layout appends to v2's, so v2 indices keep their meaning:

    0..29   v2 actions (play / buy / expend / attack / advance)
    30..39  resolve pending choice, candidate slot 0-9

Candidates are deduplicated by card id. Sacrificing one Gold is the same
decision as sacrificing another Gold, so exposing both as separate actions
would split the policy's probability mass across identical outcomes.
"""

import numpy as np

from hero_engine import apply_choice, choice_candidates
from hero_rl_env_v2 import N_ACTIONS as V2_ACTIONS
from hero_rl_env_v2 import HeroRealmsMaskedEnv

CHOICE_BASE = V2_ACTIONS          # 30
CHOICE_SLOTS = 10
N_ACTIONS = CHOICE_BASE + CHOICE_SLOTS   # 40


def distinct_candidates(player, choice):
    """Unique candidate cards in a stable order.

    Order must not depend on hand/discard shuffling, or the same slot would
    mean different cards from one state to the next and the policy could not
    learn a slot's meaning.
    """
    seen = {}
    for card in choice_candidates(player, choice):
        seen.setdefault(card.id, card)
    return sorted(seen.values(), key=lambda c: (c.cost, c.id))[:CHOICE_SLOTS]


class HeroRealmsChoiceEnv(HeroRealmsMaskedEnv):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        from gymnasium import spaces
        self.action_space = spaces.Discrete(N_ACTIONS)

    def reset(self, seed=None, options=None):
        obs, info = super().reset(seed=seed, options=options)
        # Both seats defer: the opposing policy gets the same decisions the
        # agent does, so self-play and mirror matches stay symmetric.
        self.session.player.defer_choices = True
        self.session.bot.defer_choices = True
        return obs, info

    def _pending(self, side=None):
        me, _ = self._seats(side)
        return me.pending_choices[0] if me.pending_choices else None

    def _action_table(self, side=None):
        """A pending choice blocks everything else.

        The engine is mid-effect while a choice is outstanding, so letting the
        agent play another card first would resolve effects out of order.
        """
        choice = self._pending(side)
        if choice is None:
            return super()._action_table(side)
        me, _ = self._seats(side)
        table = {}
        for i, card in enumerate(distinct_candidates(me, choice)):
            table[CHOICE_BASE + i] = {
                "type": "resolve_choice",
                "kind": choice["kind"],
                "cardId": card.id,
                "label": f"{choice['kind']}: {card.name}",
                # Keeping the engine's own valuation as the priority means the
                # greedy baseline in this env reproduces the old inline
                # behaviour, which is what makes it a fair comparison point.
                "priority": -card.cost,
            }
        return table

    def action_masks(self, side=None):
        mask = np.zeros(N_ACTIONS, dtype=bool)
        if self.session.winner is None:
            for idx in self._action_table(side):
                mask[idx] = True
        if not mask.any():
            from hero_rl_env_v2 import ADVANCE
            mask[ADVANCE] = True
        return mask

    def _apply_choice_action(self, chosen, side=None):
        me, _ = self._seats(side)
        choice = self._pending(side)
        if choice is None:
            return
        candidates = distinct_candidates(me, choice)
        index = next((i for i, c in enumerate(candidates)
                      if c.id == chosen["cardId"]), None)
        if index is None:
            me.pending_choices.remove(choice)
            return
        # distinct_candidates reorders and dedupes, so translate back to the
        # index apply_choice expects in the raw candidate list.
        raw = choice_candidates(me, choice)
        target = candidates[index]
        raw_index = next(i for i, c in enumerate(raw) if c.id == target.id)
        apply_choice(me, choice, raw_index)

    def step(self, action):
        table = self._action_table()
        chosen = table.get(int(action))
        if chosen is not None and chosen["type"] == "resolve_choice":
            self.steps_taken += 1
            self._apply_choice_action(chosen)
            s = self.session
            done = s.winner is not None
            reward = 0.0
            if done:
                reward = 1.0 if s.winner == self.agent_side else -1.0
            truncated = self.steps_taken >= self.max_steps and not done
            return self._get_obs(), reward, done, truncated, {}
        return super().step(action)
