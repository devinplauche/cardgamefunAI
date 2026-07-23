"""Gymnasium environment for Hero Realms RL training.

The agent controls buy decisions for player 1.
Player 2 uses a fixed heuristic (BalancedAI).
Play phase and combat are auto-resolved by heuristics.
"""

import random
import gymnasium as gym
from gymnasium import spaces
import numpy as np
from hero_engine import (
    HRPlayer, HRMarket, BoardChampion,
    play_card, buy_card, has_ally, load_hero_cards,
    auto_expend_all,
)
from hero_ai import (
    play_all_playable,
    buy_balanced,
    buy_aggressive,
    buy_economic,
    buy_champion,
    attack_weakest,
    attack_strongest,
    expend_all,
)


OPPONENT_PROFILES = {
    "balanced": {
        "name": "BalancedAI",
        "play": play_all_playable,
        "buy": buy_balanced,
        "attack": attack_weakest,
        "expend": expend_all,
    },
    "aggressive": {
        "name": "AggressiveAI",
        "play": play_all_playable,
        "buy": buy_aggressive,
        "attack": attack_weakest,
        "expend": expend_all,
    },
    "economic": {
        "name": "EconomicAI",
        "play": play_all_playable,
        "buy": buy_economic,
        "attack": attack_strongest,
        "expend": expend_all,
    },
    "champion": {
        "name": "ChampionAI",
        "play": play_all_playable,
        "buy": buy_champion,
        "attack": attack_weakest,
        "expend": expend_all,
    },
}


class HeroRealmsEnv(gym.Env):
    metadata = {"render_modes": ["human"]}

    def __init__(self, cards, render_mode=None, max_steps=500, opponent_profile="balanced", allow_fire_gem=True, fire_gem_penalty=0.0):
        super().__init__()
        self.cards = cards
        self.render_mode = render_mode
        self.max_steps = max_steps
        self._requested_profile = (opponent_profile or "balanced").lower()
        if self._requested_profile not in OPPONENT_PROFILES and self._requested_profile != "random":
            self._requested_profile = "balanced"
        # "random" is re-rolled per episode in reset(); a named profile is fixed here.
        # Defaulting to balanced unconditionally silently ignored the caller's
        # request and made every per-opponent evaluation a BalancedAI match.
        initial = "balanced" if self._requested_profile == "random" else self._requested_profile
        self.opponent_profile_key = initial
        self._opponent_profile = OPPONENT_PROFILES[initial]
        self.allow_fire_gem = allow_fire_gem
        self.fire_gem_penalty = fire_gem_penalty

        # Actions: 0-4 buy market row, 5 buy Fire Gem / pass, 6 pass/end turn
        self.action_space = spaces.Discrete(6 if not allow_fire_gem else 7)

        obs_dim = (6 + (5 * 7) + (5 * 5) + (5 * 5) +
                   (5 * 7))
        self.observation_space = spaces.Box(
            low=-1.0, high=1.0, shape=(obs_dim,), dtype=np.float32
        )

    def _encode_card(self, card, features):
        if card is None:
            features.extend([0.0] * 7)
            return
        features.append(min(card.cost / 10.0, 1.0))
        features.append(min(card.get("gold", 0) / 5.0, 1.0))
        features.append(min(card.get("combat", 0) / 8.0, 1.0))
        features.append(min(card.get("health", 0) / 6.0, 1.0))
        features.append(min(card.get("draw", 0) / 4.0, 1.0))
        features.append(1.0 if card.card_type == "champion" else 0.0)
        features.append(min(card.guard / 3.0, 1.0))

    def _encode_champ(self, bc, features):
        if bc is None:
            features.extend([0.0] * 5)
            return
        features.append(bc.current_health / 6.0)
        features.append(min(bc.guard / 3.0, 1.0))
        features.append(1.0 if bc.card.get("combat", 0) > 0 else 0.0)
        features.append(1.0 if bc.card.get("gold", 0) > 0 else 0.0)
        features.append(1.0 if bc.guard > 0 else 0.0)

    def _get_obs(self):
        p = self.agent
        o = self.opponent
        features = []

        features.append(p.hp / 50.0)
        features.append(o.hp / 50.0)
        features.append(p.gold / 20.0)
        features.append(p.combat / 20.0)
        features.append(self.turn / 100.0)
        features.append(len(p.hand) / 10.0)

        for i in range(5):
            self._encode_card(self.market.row[i], features)

        champs = [bc for bc in p.board if bc.alive]
        for i in range(5):
            self._encode_champ(champs[i] if i < len(champs) else None, features)

        champs = [bc for bc in o.board if bc.alive]
        for i in range(5):
            self._encode_champ(champs[i] if i < len(champs) else None, features)

        hand_cards = p.hand[:5]
        for i in range(5):
            self._encode_card(hand_cards[i] if i < len(hand_cards) else None, features)

        return np.array(features, dtype=np.float32)

    def _opponent_turn(self):
        opp = self.opponent
        ag = self.agent

        opp.gold = 0
        opp.combat = 0
        opp.actions_played = 0
        opp.played_this_turn.clear()
        opp.pending_ally.clear()
        opp.cards_bought = 0
        for bc in opp.board:
            bc.exhausted = False

        self._opponent_profile["play"](opp, ag, self.market)
        self._opponent_profile["expend"](opp, ag)
        self._opponent_profile["buy"](opp, ag, self.market)

        if opp.combat > 0:
            guards = [bc for bc in ag.board if bc.guard and bc.alive]
            if guards:
                self._opponent_profile["attack"](opp, ag, guards)
            ag.hp -= opp.combat
            opp.combat = 0

        if ag.hp <= 0:
            self.winner = opp.name

    def _cleanup(self, player):
        for c in player.hand:
            player.discard.append(c)
        player.hand.clear()
        player.draw(5)

    def _resolve_turn(self):
        p = self.agent
        o = self.opponent

        if p.combat > 0:
            guards = [bc for bc in o.board if bc.guard and bc.alive]
            if guards:
                attack_weakest(p, o, guards)
            o.hp -= p.combat
            p.combat = 0

        if o.hp <= 0:
            self.winner = p.name
            return

        self._cleanup(p)
        self._opponent_turn()

        if self.winner:
            return

        self._cleanup(o)

        self.turn += 1
        p.gold = 0
        p.combat = 0
        p.actions_played = 0
        p.played_this_turn.clear()
        p.pending_ally.clear()
        p.cards_bought = 0
        for bc in p.board:
            bc.exhausted = False

        play_all_playable(p, o, self.market)
        auto_expend_all(p, o)

    def set_opponent_profile(self, profile: str):
        profile_key = profile.lower()
        if profile_key in OPPONENT_PROFILES:
            self.opponent_profile_key = profile_key
            self._opponent_profile = OPPONENT_PROFILES[profile_key]

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)

        if self._requested_profile == "random":
            profile_key = random.choice(list(OPPONENT_PROFILES.keys()))
            self.set_opponent_profile(profile_key)

        self.agent = HRPlayer("Agent")
        self.opponent = HRPlayer(self._opponent_profile["name"])
        self.agent.setup_starting_deck()
        self.opponent.setup_starting_deck()

        self.market = HRMarket(self.cards)
        self.turn = 1
        self.winner = None
        self.steps_taken = 0

        self.agent.draw(3)
        self.opponent.draw(5)

        play_all_playable(self.agent, self.opponent, self.market)
        auto_expend_all(self.agent, self.opponent)

        return self._get_obs(), {}

    def step(self, action):
        self.steps_taken += 1
        reward = 0.0
        p = self.agent

        if action == 6 or (action == 5 and not self.allow_fire_gem):
            self._resolve_turn()
        else:
            bought = buy_card(p, self.market, action)
            if not bought:
                self._resolve_turn()
            else:
                if action == 5 and self.fire_gem_penalty != 0.0:
                    reward += self.fire_gem_penalty
                can_buy = False
                if p.gold > 0:
                    for c in self.market.row_cards():
                        if c and c.cost <= p.gold:
                            can_buy = True
                            break
                    if not can_buy and p.gold >= 2 and self.market.can_buy_fire_gem():
                        can_buy = True
                if not can_buy:
                    self._resolve_turn()

        done = self.winner is not None
        if done:
            reward = 1.0 if self.winner == self.agent.name else -1.0

        truncated = self.steps_taken >= self.max_steps and not done

        return self._get_obs(), reward, done, truncated, {}

    def render(self):
        if self.render_mode == "human":
            p = self.agent
            o = self.opponent
            row = self.market.row_cards()
            print(f"Turn {self.turn}")
            print(f"Agent HP:{p.hp} Gold:{p.gold} Combat:{p.combat} Hand:{len(p.hand)}")
            print(f"Opponent HP:{o.hp} Board:{sum(1 for bc in o.board if bc.alive)}")
            print(f"Market: {[(c.name[:12] if c else '---') for c in row]}")
            print()
