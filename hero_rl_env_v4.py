"""v3's action space with an observation that can actually see the game.

Every run from V15 to V20 shared v2's card encoding, and it omits the two
things this game is mostly about. Measured against the 96-card set:

  ally_faction        55 cards   not encoded at all
  ally_* payloads     43 cards   not encoded at all
  faction             80 cards   not encoded at all (per-card)
  sacrifice_*         33 cards   counted via c.get("sacrifice"), an effect key
                                 that does not exist -> constant 0.0 since v15

So the policy could see a card's cost and printed stats but not its faction,
not its ally text, and not whether it enables a sacrifice outlet. Faction
stacking is the core synergy mechanic and `_enabler_value` in web/bot.py is the
only valuation in the repo that rank-correlates positively with real play data
(+0.245, against -0.077 and -0.196 for the two without ally terms). A policy
that cannot observe faction cannot learn any of it, which is a far better
explanation for five methods landing in the same ~48% band than any claim about
PPO's optimizer.

v3 added a second, narrower version of the same mistake: sacrifice and discard
targeting became actions 30-39, but the observation never encoded *what is in
those slots*, so the policy chose targets blind. V20 - the clean rerun -
finished at exactly greedy's 37.5%, which is what choosing uniformly among
unobservable options looks like.

Action space is byte-identical to v3 so the comparison holds. The observation
is not, so v3 checkpoints do not load here - same rule as v2 -> v3.

Public-information discipline: opponent deck features use only the *composition*
of cards the opponent owns, never their location or order. Purchases are public
and the starting deck is fixed, so which cards an opponent owns is public
knowledge; which are in hand and in what order is not, and is never read.
"""

import math

import numpy as np
from gymnasium import spaces

from hero_engine import has_ally
from hero_rl_env_v3 import CHOICE_BASE, CHOICE_SLOTS, N_ACTIONS, distinct_candidates
from hero_rl_env_v3 import HeroRealmsChoiceEnv
from hero_rl_env_v2 import CHAMPION_SLOTS, HAND_SLOTS, MARKET_SLOTS, FACTIONS

# Per-card feature width. 7 of these are v2's; the rest are the repair.
CARD_FEATURES = 22

# Static-per-card features are a pure function of an immutable HRCard and are
# rebuilt ~35 times per observation, on every one of ~10k env steps per second.
# Cached by card.id, which web/session.py already establishes is unique across
# the card set and the five hardcoded starting/Fire Gem cards.
_STATIC_CARD_CACHE: dict[str, tuple[float, ...]] = {}

_THINNING_KEYS = ("sacrifice_card", "sacrifice_for_combat", "sacrifice_up_to")


def _static_card_features(card) -> tuple[float, ...]:
    cached = _STATIC_CARD_CACHE.get(card.id)
    if cached is not None:
        return cached
    effects = card.effects
    faction = (card.faction or "").lower()
    ally_faction = (effects.get("ally_faction", "") or "").lower()
    features = (
        min(card.cost / 10.0, 1.0),
        min(effects.get("gold", 0) / 5.0, 1.0),
        min(effects.get("combat", 0) / 8.0, 1.0),
        min(effects.get("health", 0) / 6.0, 1.0),
        min(effects.get("draw", 0) / 4.0, 1.0),
        1.0 if card.card_type == "champion" else 0.0,
        min(card.guard / 3.0, 1.0),
        # Faction one-hot: 80 of 96 cards have one and v2 encoded none of it.
        *(1.0 if faction == f else 0.0 for f in FACTIONS),
        # Ally payload. What the card pays *if* its ally condition is met.
        min(effects.get("ally_combat", 0) / 6.0, 1.0),
        min(effects.get("ally_gold", 0) / 3.0, 1.0),
        min(effects.get("ally_draw", 0) / 2.0, 1.0),
        min(effects.get("ally_health", 0) / 6.0, 1.0),
        # Sacrifice access, keyed off the effects that actually exist.
        min(effects.get("sacrifice_combat", 0) / 4.0, 1.0),
        1.0 if any(effects.get(key) for key in _THINNING_KEYS) else 0.0,
        min(effects.get("opponent_discard", 0) / 2.0, 1.0),
        1.0 if effects.get("stun", False) else 0.0,
    )
    _STATIC_CARD_CACHE[card.id] = features
    return features


class HeroRealmsRichObsEnv(HeroRealmsChoiceEnv):
    """v3 actions, repaired observation, optional potential-based shaping."""

    def __init__(self, shaping_weight=0.0, shaping_gamma=0.99, shaping_scale=25.0,
                 **kwargs):
        super().__init__(**kwargs)
        self.action_space = spaces.Discrete(N_ACTIONS)
        # 0.0 reproduces v3's reward exactly, so the shaping term is an A/B and
        # not a silent change to what every arm is optimising.
        self.shaping_weight = shaping_weight
        self.shaping_gamma = shaping_gamma
        self.shaping_scale = shaping_scale
        obs_dim = (
            8                                   # scalar game state
            + (8 + len(FACTIONS))               # own deck composition
            + (8 + len(FACTIONS))               # opponent deck composition (public)
            + MARKET_SLOTS * CARD_FEATURES
            + CHAMPION_SLOTS * 5 * 2
            + HAND_SLOTS * CARD_FEATURES
            + CHOICE_SLOTS * CARD_FEATURES      # what is actually in slots 30-39
            + 3                                 # pending-choice kind
        )
        self.observation_space = spaces.Box(low=-1.0, high=1.0, shape=(obs_dim,),
                                            dtype=np.float32)

    # ---- observation ----

    def _faction_counts(self, player):
        owned = (list(player.deck) + list(player.discard) + list(player.hand)
                 + [bc.card for bc in player.board if bc.alive])
        counts = {f: 0 for f in FACTIONS}
        for card in owned:
            faction = (card.faction or "").lower()
            if faction in counts:
                counts[faction] += 1
        return counts

    def _encode_card(self, card, feats, player=None, faction_counts=None):
        """v2's signature plus the owner context the ally features need.

        `player` is optional so any inherited v2 code path still works; when it
        is supplied the three derived features below are what make ally text
        actionable rather than decorative.
        """
        if card is None:
            feats.extend([0.0] * CARD_FEATURES)
            return
        feats.extend(_static_card_features(card))
        if player is None:
            feats.extend([0.0, 0.0, 0.0])
            return
        # Is this card's ally condition live *right now*? The network would
        # have to rediscover has_ally's rule (board plus everything played this
        # turn, and the card itself does not count) from one-hots alone.
        feats.append(1.0 if has_ally(card, player) else 0.0)
        counts = faction_counts if faction_counts is not None else self._faction_counts(player)
        faction = (card.faction or "").lower()
        ally_faction = (card.effects.get("ally_faction", "") or "").lower()
        # How much of this card's own faction the owner already has: buying the
        # seventh Necros card is a different decision from buying the first.
        feats.append(min(counts.get(faction, 0) / 8.0, 1.0) if faction else 0.0)
        # And how much of the faction this card's ally needs.
        feats.append(min(counts.get(ally_faction, 0) / 8.0, 1.0) if ally_faction else 0.0)

    def _deck_features(self, p):
        """v2's, with the dead sacrifice feature repaired.

        v2 counted `c.get("sacrifice")`; no card carries that key, so the slot
        was a constant zero. The real effects are sacrifice_combat and the three
        thinning variants, split here because they do different things: one
        converts a card into damage, the other permanently thins the deck.
        """
        owned = (list(p.deck) + list(p.discard) + list(p.hand)
                 + [bc.card for bc in p.board if bc.alive])
        n = max(len(owned), 1)
        feats = [
            min(len(owned) / 40.0, 1.0),
            min(sum(c.get("gold", 0) for c in owned) / n / 3.0, 1.0),
            min(sum(c.get("combat", 0) for c in owned) / n / 4.0, 1.0),
            min(sum(c.get("draw", 0) for c in owned) / n / 1.5, 1.0),
            min(sum(c.cost for c in owned) / n / 6.0, 1.0),
            min(sum(1 for c in owned if c.card_type == "champion") / 10.0, 1.0),
            min(sum(1 for c in owned if c.get("sacrifice_combat", 0)) / 5.0, 1.0),
            min(sum(1 for c in owned
                    if any(c.get(k) for k in _THINNING_KEYS)) / 5.0, 1.0),
        ]
        counts = self._faction_counts(p)
        for faction in FACTIONS:
            feats.append(min(counts[faction] / 8.0, 1.0))
        return feats

    def _get_obs(self, side=None):
        s = self.session
        p, o = self._seats(side)
        f = [
            p.hp / 50.0, o.hp / 50.0,
            min(p.gold / 20.0, 1.0), min(p.combat / 20.0, 1.0),
            min(s.turn_number / 60.0, 1.0), min(len(p.hand) / 10.0, 1.0),
            ["play", "champion", "buy", "combat"].index(s.phase) / 3.0,
            min(self.market.fire_gems_remaining / 16.0, 1.0),
        ]
        f.extend(self._deck_features(p))
        # Composition only - see the module docstring on why this is public.
        f.extend(self._deck_features(o))

        own_counts = self._faction_counts(p)
        for i in range(MARKET_SLOTS):
            self._encode_card(self.market.row[i], f, p, own_counts)

        pc = [bc for bc in p.board if bc.alive]
        oc = [bc for bc in o.board if bc.alive]
        for i in range(CHAMPION_SLOTS):
            self._encode_champ(pc[i] if i < len(pc) else None, f)
        for i in range(CHAMPION_SLOTS):
            self._encode_champ(oc[i] if i < len(oc) else None, f)

        for i in range(HAND_SLOTS):
            self._encode_card(p.hand[i] if i < len(p.hand) else None, f, p, own_counts)

        # Actions 30-39 select among these. v3 exposed the actions and not the
        # candidates, so the policy was choosing a slot index with no
        # information about what the slot contained.
        choice = self._pending(side)
        candidates = distinct_candidates(p, choice) if choice else []
        for i in range(CHOICE_SLOTS):
            self._encode_card(candidates[i] if i < len(candidates) else None,
                              f, p, own_counts)
        kind = (choice or {}).get("kind", "")
        f.extend([
            1.0 if choice else 0.0,
            1.0 if kind == "sacrifice" else 0.0,
            1.0 if kind == "discard" else 0.0,
        ])
        return np.array(f, dtype=np.float32)

    # ---- potential-based reward shaping ----

    def _potential(self):
        """Bounded HP-margin potential; zero at any terminal state.

        Potential-based shaping (Ng, Harada & Russell 1999) adds
        F = gamma*Phi(s') - Phi(s), which telescopes over an episode to a
        constant and therefore *provably* leaves the optimal policy unchanged.
        That is the whole reason to use this shape rather than a hand-priced
        per-step bonus: it can only change how fast credit propagates, never
        what the agent is being asked to maximise.

        Phi(terminal) = 0 is required for that guarantee in episodic tasks, so
        the final transition contributes -Phi(s) on top of the win/loss reward.

        HP margin is the right potential here: it already measures 0.89
        correlation with winning in this repo, and the margin-fitness CMA run
        converged cleanly where binary win rate would not - the signal exists,
        it has just never been used as a per-step learning signal.
        """
        if self.session.winner is not None:
            return 0.0
        me, foe = self._seats()
        return self.shaping_weight * math.tanh((me.hp - foe.hp) / self.shaping_scale)

    def step(self, action):
        if not self.shaping_weight:
            return super().step(action)
        before = self._potential()
        obs, reward, done, truncated, info = super().step(action)
        reward += self.shaping_gamma * self._potential() - before
        return obs, reward, done, truncated, info
