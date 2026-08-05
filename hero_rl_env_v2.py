"""Unified, action-masked Gymnasium environment for Hero Realms.

The v1 env (hero_rl_env.py) exposes only buy decisions: play, expend, combat
routing and targeting are all auto-resolved by heuristics, so the policy
structurally cannot learn them no matter how long it trains. v14 plateaued
around 20% against random profiles, which is that ceiling rather than a
tuning problem.

This env drives the real GameSession used by the web app and the MCTS bot, so
every phase the game actually has is a decision the agent makes: which card to
play (and in what order, which matters for ally triggers), which champion to
expend, what to buy, and how to route combat between guards, non-guard
champions and the opponent's face.

Illegal actions are masked rather than penalized - the standard approach for
card games, where the nominal action space is large but only a handful of
actions are legal in any given state (see MaskablePPO / the MTG RL benchmark).
Requires sb3-contrib for MaskablePPO; the mask is exposed via action_masks().

Still heuristic, and the natural phase 2: which card to sacrifice and which to
discard. Those live inside play_card's effect resolution rather than as
session-level actions, so exposing them needs a pending-choice state machine in
the engine, not just a wider action space here.
"""

import random

import gymnasium as gym
import numpy as np
from gymnasium import spaces

from hero_engine import load_hero_cards
from hero_rl_env import OPPONENT_PROFILES
from web.session import create_session

# Flat action layout. Slot counts are generous rather than tight: draw effects
# can push a hand past 5 cards and a board past 6 champions, and an unreachable
# slot is just a permanently-masked action, while a too-small space would make
# legal actions silently unavailable.
HAND_SLOTS = 10
MARKET_SLOTS = 5
CHAMPION_SLOTS = 6
TARGET_SLOTS = 6

PLAY_BASE = 0
BUY_BASE = PLAY_BASE + HAND_SLOTS            # 10
FIRE_GEM = BUY_BASE + MARKET_SLOTS           # 15
EXPEND_BASE = FIRE_GEM + 1                   # 16
ATTACK_BASE = EXPEND_BASE + CHAMPION_SLOTS   # 22
ATTACK_FACE = ATTACK_BASE + TARGET_SLOTS     # 28
ADVANCE = ATTACK_FACE + 1                    # 29
N_ACTIONS = ADVANCE + 1                      # 30

FACTIONS = ("guild", "imperial", "necros", "wild")


from web.bot import _decision_category

#: Legacy phase ordering, retained purely as the observation encoding.
_PHASE_INDEX = {"play": 0, "champion": 1, "buy": 2, "combat": 3}


class HeroRealmsMaskedEnv(gym.Env):
    metadata = {"render_modes": ["human"]}

    def __init__(self, cards=None, opponent_profile="random", max_steps=1000,
                 fire_gem_penalty=0.0, seed=None, agent_side="player"):
        super().__init__()
        # The two seats are not symmetric: the player seat moves first and is
        # compensated with a 3-card opening hand against the bot seat's 5.
        # Benchmarks that always seat the tested policy in one of them measure
        # the seat as much as the policy, so the side is parameterized.
        if agent_side not in ("player", "bot"):
            raise ValueError("agent_side must be 'player' or 'bot'")
        self.agent_side = agent_side
        self.cards = cards if cards is not None else load_hero_cards("data/hero_realms_cards.json")
        self.max_steps = max_steps
        self.fire_gem_penalty = fire_gem_penalty
        self._requested_profile = (opponent_profile or "balanced").lower()
        if self._requested_profile not in OPPONENT_PROFILES and self._requested_profile != "random":
            self._requested_profile = "balanced"
        self._seed = seed

        self.action_space = spaces.Discrete(N_ACTIONS)
        obs_dim = (8 + 12 + (MARKET_SLOTS * 7) + (CHAMPION_SLOTS * 5) * 2 + (HAND_SLOTS * 7))
        self.observation_space = spaces.Box(low=-1.0, high=1.0, shape=(obs_dim,), dtype=np.float32)

    @staticmethod
    def _other(side):
        return "bot" if side == "player" else "player"

    @property
    def me(self):
        return getattr(self.session, self.agent_side)

    @property
    def foe(self):
        return getattr(self.session, self._other(self.agent_side))

    @property
    def _foe_side(self):
        return self._other(self.agent_side)

    def _seats(self, side=None):
        """(acting player, their opponent) for whichever seat is asked about.

        Self-play needs the opposing policy's view of the same session, so
        every perspective-dependent method takes a side rather than reading
        self.agent_side directly.
        """
        side = side or self.agent_side
        return getattr(self.session, side), getattr(self.session, self._other(side))

    # ---- observation ----

    def _encode_card(self, card, feats):
        if card is None:
            feats.extend([0.0] * 7)
            return
        feats.append(min(card.cost / 10.0, 1.0))
        feats.append(min(card.get("gold", 0) / 5.0, 1.0))
        feats.append(min(card.get("combat", 0) / 8.0, 1.0))
        feats.append(min(card.get("health", 0) / 6.0, 1.0))
        feats.append(min(card.get("draw", 0) / 4.0, 1.0))
        feats.append(1.0 if card.card_type == "champion" else 0.0)
        feats.append(min(card.guard / 3.0, 1.0))

    def _encode_champ(self, bc, feats):
        if bc is None:
            feats.extend([0.0] * 5)
            return
        feats.append(min(bc.current_health / 6.0, 1.0))
        feats.append(min(bc.guard / 3.0, 1.0))
        feats.append(1.0 if bc.card.get("combat", 0) > 0 else 0.0)
        feats.append(1.0 if bc.card.get("gold", 0) > 0 else 0.0)
        feats.append(0.0 if bc.exhausted else 1.0)

    def _deck_features(self, p):
        """Deck composition the v1 obs never had. A policy that cannot see what
        it has already bought cannot reason about buy timing or thinning - the
        distinction between average hand strength and raw deck total."""
        owned = list(p.deck) + list(p.discard) + list(p.hand) + [bc.card for bc in p.board if bc.alive]
        n = max(len(owned), 1)
        feats = [
            min(len(owned) / 40.0, 1.0),
            min(sum(c.get("gold", 0) for c in owned) / n / 3.0, 1.0),
            min(sum(c.get("combat", 0) for c in owned) / n / 4.0, 1.0),
            min(sum(c.get("draw", 0) for c in owned) / n / 1.5, 1.0),
            min(sum(c.cost for c in owned) / n / 6.0, 1.0),
            min(sum(1 for c in owned if c.card_type == "champion") / 10.0, 1.0),
            min(sum(1 for c in owned if c.get("sacrifice")) / 5.0, 1.0),
            min(len(p.deck) / 20.0, 1.0),
        ]
        for f in FACTIONS:
            feats.append(min(sum(1 for c in owned if c.faction == f) / 8.0, 1.0))
        return feats

    def _get_obs(self, side=None):
        s = self.session
        p, o = self._seats(side)
        f = [
            p.hp / 50.0, o.hp / 50.0,
            min(p.gold / 20.0, 1.0), min(p.combat / 20.0, 1.0),
            min(s.turn_number / 60.0, 1.0), min(len(p.hand) / 10.0, 1.0),
            # Under the faithful main phase every category is legal at once, so
            # the observation carries the *decision category* (what a greedy
            # policy would do next) rather than a phase index. Keeps the
            # feature meaningful and the observation width unchanged.
            _PHASE_INDEX[_decision_category(s)] / 3.0,
            min(self.market.fire_gems_remaining / 16.0, 1.0),
        ]
        f.extend(self._deck_features(p))
        for i in range(MARKET_SLOTS):
            self._encode_card(self.market.row[i], f)
        pc = [bc for bc in p.board if bc.alive]
        oc = [bc for bc in o.board if bc.alive]
        for i in range(CHAMPION_SLOTS):
            self._encode_champ(pc[i] if i < len(pc) else None, f)
        for i in range(CHAMPION_SLOTS):
            self._encode_champ(oc[i] if i < len(oc) else None, f)
        for i in range(HAND_SLOTS):
            self._encode_card(p.hand[i] if i < len(p.hand) else None, f)
        return np.array(f, dtype=np.float32)

    # ---- action mapping ----

    def _action_table(self, side=None):
        """Map each legal session action onto a flat index. Several legal
        actions can share an index (a stun card with multiple targets); the
        highest-priority variant wins, which keeps target choice heuristic for
        stuns while leaving physical combat targeting to the policy."""
        s = self.session
        table = {}
        me, foe = self._seats(side)
        hand_ids = [c.id for c in me.hand]
        board_ids = [str(bc.instance_id) for bc in me.board if bc.alive and not bc.exhausted]
        targets = [str(bc.instance_id) for bc in s._attack_targets(foe)]

        for a in s.legal_actions():
            t = a["type"]
            idx = None
            if t == "play_card":
                # Positional slot, so identical copies stay distinguishable.
                for i, cid in enumerate(hand_ids[:HAND_SLOTS]):
                    if cid == a["cardId"] and (PLAY_BASE + i) not in table:
                        idx = PLAY_BASE + i
                        break
            elif t == "buy_card":
                mi = int(a["marketIndex"])
                idx = FIRE_GEM if mi == 5 else BUY_BASE + mi
            elif t == "expend_champion":
                cid = a["championId"]
                if cid in board_ids and board_ids.index(cid) < CHAMPION_SLOTS:
                    idx = EXPEND_BASE + board_ids.index(cid)
            elif t == "attack_target":
                if a["target"] == "player":
                    idx = ATTACK_FACE
                else:
                    cid = a.get("championId")
                    if cid in targets and targets.index(cid) < TARGET_SLOTS:
                        idx = ATTACK_BASE + targets.index(cid)
            elif t == "advance_phase":
                idx = ADVANCE
            if idx is not None and idx not in table:
                table[idx] = a
        return table

    def action_masks(self, side=None):
        mask = np.zeros(N_ACTIONS, dtype=bool)
        if self.session.winner is None:
            for idx in self._action_table(side):
                mask[idx] = True
        if not mask.any():
            mask[ADVANCE] = True  # never hand MaskablePPO an all-false mask
        return mask

    # ---- opponent ----

    def _opponent_turn(self):
        """Heuristic profile rather than the session's MCTS bot: 2M training
        steps cannot afford thousands of rollouts per opponent move."""
        s = self.session
        ag, opp = self._seats()
        prof = self._profile
        prof["play"](opp, ag, self.market)
        prof["expend"](opp, ag)
        prof["buy"](opp, ag, self.market)
        if opp.combat > 0:
            guards = [bc for bc in ag.board if bc.guard and bc.alive]
            prof["attack"](opp, ag, guards)
            ag.hp -= opp.combat
            opp.combat = 0
        ag.remove_stunned_champions() if hasattr(ag, "remove_stunned_champions") else None
        s._check_winner()
        if s.winner is None:
            s.end_turn()

    # ---- gym API ----

    def reset(self, seed=None, options=None):
        super().reset(seed=seed)
        # Draw the profile from a seed-derived RNG, not the global one. With
        # random.choice, opponent_profile="random" made evaluation
        # irreproducible: the seed fixed the deck shuffle but not which of the
        # four profiles was faced, so the same model on the same seeds could
        # score several points apart between runs.
        self._episode_rng = random.Random(seed) if seed is not None else random
        key = (self._episode_rng.choice(sorted(OPPONENT_PROFILES))
               if self._requested_profile == "random" else self._requested_profile)
        self._profile = OPPONENT_PROFILES[key]
        self.opponent_profile_key = key

        self.session = create_session(seed=seed if seed is not None else self._seed)
        self.session.active_player = "player"
        # create_session already opens in the correct phase (main when
        # FREEFORM_TURN, else "play"); do not override it.
        self.market = self.session.market
        self.steps_taken = 0
        # Seated second: the opposing seat takes its opening turn before the
        # agent ever observes the state.
        if self.agent_side == "bot":
            self._opponent_turn()
        return self._get_obs(), {}

    def step(self, action):
        from web.bot import apply_action

        self.steps_taken += 1
        s = self.session
        reward = 0.0
        table = self._action_table()
        chosen = table.get(int(action))

        if chosen is None:
            # Masking should prevent this; treat as a no-op phase advance
            # rather than corrupting game state on an out-of-mask sample.
            chosen = {"type": "advance_phase"}
        if chosen["type"] == "buy_card" and int(chosen.get("marketIndex", -1)) == 5:
            reward += self.fire_gem_penalty

        was_combat = s.phase == "combat"
        apply_action(s, chosen)

        # end_turn inside advance_phase hands the turn to the opponent.
        if s.winner is None and s.active_player == self._foe_side:
            self._opponent_turn()

        done = s.winner is not None
        if done:
            # GameSession.winner is the side key ("player"/"bot"), not the
            # HRPlayer.name ("Player"/"Bot") the v1 env compares against.
            reward = 1.0 if s.winner == self.agent_side else -1.0
        truncated = self.steps_taken >= self.max_steps and not done
        return self._get_obs(), reward, done, truncated, {}

    def render(self):
        s = self.session
        print(f"T{s.turn_number} {s.phase} | me {self.me.hp}hp g{self.me.gold} "
              f"c{self.me.combat} | foe {self.foe.hp}hp")
