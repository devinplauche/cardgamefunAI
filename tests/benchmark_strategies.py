#!/usr/bin/env python3
"""
Strategy benchmark – pure Python, no Godot required.

Mirrors the logic in tests/AIBenchmark.gd so strategy rankings can be
verified locally without a Godot installation.

Usage:
    python3 tests/benchmark_strategies.py
    python3 tests/benchmark_strategies.py --games 20   # faster run
    python3 tests/benchmark_strategies.py --csv results.csv
"""
from __future__ import annotations

import argparse
import csv as csv_module
import json
import math
import os
import random
import re
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# ---------------------------------------------------------------------------
# Card model
# ---------------------------------------------------------------------------

@dataclass
class Card:
    name: str
    cost: int = 0
    faction: str = "neutral"
    card_type: str = "action"
    combat: int = 0
    gold: int = 0
    health: int = 0
    draw_cards: int = 0
    sacrifice_combat: int = 0
    opponent_discard: int = 0
    ally_combat: int = 0
    ally_gold: int = 0
    ally_health: int = 0
    is_champion: bool = False


# ---------------------------------------------------------------------------
# Load and enrich market cards from marketplace.json
# ---------------------------------------------------------------------------

def _parse_int_in_text(text: str, *keywords: str) -> int:
    """Return the first integer that appears before any of the keywords."""
    for kw in keywords:
        m = re.search(r'(\d+)\s+' + re.escape(kw), text, re.IGNORECASE)
        if m:
            return int(m.group(1))
    return 0


def _enrich_card(raw: dict) -> Card:
    effect_text = raw.get("effect", "")
    ally_text = raw.get("ally_effect", "")

    # Detect card draws in effect text
    draw = int(bool(re.search(r'draw a card', effect_text, re.IGNORECASE)))
    m = re.search(r'draw (\d+) cards?', effect_text, re.IGNORECASE)
    if m:
        draw = max(draw, int(m.group(1)))

    # Detect sacrifice / expunge in effect text
    sacrifice = 0
    if re.search(r'expunge|sacrifice', effect_text, re.IGNORECASE):
        sacrifice = max(int(raw.get("combat", 0)), 2)

    # Detect opponent discard in effect text
    discard_match = re.search(r'opponent\s+discards?\s+(\d+)', effect_text, re.IGNORECASE)
    opp_discard = int(discard_match.group(1)) if discard_match else 0

    # Parse ally bonuses from ally_effect text
    ally_combat = _parse_int_in_text(ally_text, "additional combat", "combat")
    ally_gold = _parse_int_in_text(ally_text, "additional gold", "gold")
    ally_health = _parse_int_in_text(ally_text, "additional health", "health")
    # "Draw a card" ally bonus (treat as +1 resource)
    if re.search(r'draw a card', ally_text, re.IGNORECASE):
        draw += 1

    return Card(
        name=raw["name"],
        cost=int(raw.get("cost", 0)),
        faction=raw.get("faction", "neutral"),
        card_type=raw.get("type", "action"),
        combat=int(raw.get("combat", 0)),
        gold=int(raw.get("gold", 0)),
        health=int(raw.get("health", 0)),
        draw_cards=draw,
        sacrifice_combat=sacrifice,
        opponent_discard=opp_discard,
        ally_combat=ally_combat,
        ally_gold=ally_gold,
        ally_health=ally_health,
        is_champion="champion" in raw.get("type", "").lower(),
    )


def load_market_cards(path: str) -> List[Card]:
    with open(path, encoding="utf-8") as f:
        raw_list = json.load(f)
    return [_enrich_card(r) for r in raw_list]


# ---------------------------------------------------------------------------
# Starter deck card definitions (mirrors GameState.gd starting_deck_ids)
# ---------------------------------------------------------------------------

def _make_starter_deck() -> List[Card]:
    return [
        Card("Gold Coin", gold=1),
        Card("Gold Coin", gold=1),
        Card("Gold Coin", gold=1),
        Card("Gold Coin", gold=1),
        Card("Gold Coin", gold=1),
        Card("Gold Coin", gold=1),
        Card("Gold Coin", gold=1),
        Card("Ruby",      gold=2),
        Card("Dagger",    combat=1),
        Card("Sword",     combat=2),
    ]


def _make_fire_gem() -> Card:
    # Default play: 2 gold (sacrifice option simplified away).
    return Card("Fire Gem", gold=2)


# ---------------------------------------------------------------------------
# Player state
# ---------------------------------------------------------------------------

class Player:
    MAX_HP: int = 50

    def __init__(self, name: str) -> None:
        self.name = name
        self.max_hp = self.MAX_HP
        self.current_hp = self.MAX_HP
        self.current_block = 0
        self.combat_pool = 0
        self.gold_pool = 0
        self.hand: List[Card] = []
        self.discard: List[Card] = []
        self.deck: List[Card] = _make_starter_deck()
        random.shuffle(self.deck)
        self.champions_in_play: List[Card] = []
        self.faction_counts: Dict[str, int] = {}

    def _reshuffle(self) -> None:
        self.deck = list(self.discard)
        self.discard = []
        random.shuffle(self.deck)

    def draw(self, n: int = 1) -> None:
        for _ in range(n):
            if not self.deck:
                if not self.discard:
                    return
                self._reshuffle()
            if self.deck:
                self.hand.append(self.deck.pop(0))

    def start_turn(self, draw_count: int = 5) -> None:
        self.current_block = 0
        self.combat_pool = 0
        self.gold_pool = 0
        self.faction_counts = {}
        self.draw(draw_count)
        # Champions expend: apply their primary stats each turn.
        for champ in self.champions_in_play:
            self.combat_pool += champ.combat
            self.gold_pool += champ.gold

    def play_card(self, card: Card, opponent: "Player") -> bool:
        if card not in self.hand:
            return False
        self.hand.remove(card)

        # Track faction for ally trigger counting (used by COMBO strategy).
        if card.faction and card.faction != "neutral":
            self.faction_counts[card.faction] = (
                self.faction_counts.get(card.faction, 0) + 1
            )

        self.combat_pool += card.combat
        self.gold_pool += card.gold
        if card.health > 0:
            self.current_hp = min(self.max_hp, self.current_hp + card.health)
        if card.sacrifice_combat > 0:
            # Sacrifice: always take the combat gain (simplified).
            self.combat_pool += card.sacrifice_combat
        if card.draw_cards > 0:
            self.draw(card.draw_cards)

        if card.is_champion:
            # Champions enter play; they expend each turn.
            self.champions_in_play.append(card)
        else:
            self.discard.append(card)
        return True

    @property
    def dominant_faction(self) -> str:
        if not self.faction_counts:
            return ""
        return max(self.faction_counts, key=lambda k: self.faction_counts[k])

    def buy_card(self, card: Card) -> None:
        self.discard.append(card)

    def resolve_combat(self, opponent: "Player") -> None:
        net = max(self.combat_pool - opponent.current_block, 0)
        opponent.current_block = max(opponent.current_block - self.combat_pool, 0)
        opponent.current_hp = max(opponent.current_hp - net, 0)

    def end_turn(self) -> None:
        for c in self.hand:
            self.discard.append(c)
        self.hand = []
        self.combat_pool = 0
        self.gold_pool = 0
        self.current_block = 0


# ---------------------------------------------------------------------------
# CardEvaluator (mirrors CardEvaluator.gd)
# ---------------------------------------------------------------------------

_LOW_HP_FRACTION = 0.4
_HEALTH_TO_BLOCK = 0.7
_AGGRO_HP_THRESHOLD = 15


def _estimate_values(card: Card, ai_champions: int) -> Dict[str, int]:
    """Port of CardEvaluator._estimate_card_values."""
    dmg = card.combat
    blk = round(card.health * _HEALTH_TO_BLOCK)
    dis = card.opponent_discard
    res = card.gold + card.draw_cards

    if card.is_champion:
        # Champions persist; double-weight their stats.
        dmg *= 2
        res += card.gold
    return {"damage": dmg, "block": blk, "disruption": dis, "resource": res}


def _score_card(card: Card, context: Dict, ai_champions: int = 0) -> float:
    """Port of CardEvaluator.score_card."""
    ai_gold = context.get("ai_gold", 99)
    ai_hp = context.get("ai_hp", 50)
    ai_max_hp = max(context.get("ai_max_hp", 50), 1)
    ai_combat = context.get("ai_combat", 0)
    opponent_hp = context.get("opponent_hp", 999)
    opponent_block = context.get("opponent_block", 0)
    effective_opp_hp = opponent_hp + opponent_block

    playable_now = card.cost <= ai_gold
    mana_efficiency = 0.1
    if playable_now:
        mana_efficiency = max(0.0, min(1.0, 1.0 - (card.cost / max(ai_gold, 1)) * 0.5))

    vals = _estimate_values(card, ai_champions)
    damage_score = min(vals["damage"] / 20.0, 1.0)
    block_score = min(vals["block"] / 15.0, 1.0)
    disruption_score = min(vals["disruption"] / 10.0, 1.0)
    resource_score = min(vals["resource"] / 10.0, 1.0)

    lethal_bonus = 0.0
    if effective_opp_hp > 0:
        proj = ai_combat + vals["damage"]
        if proj >= effective_opp_hp:
            lethal_bonus = 1.0
        elif proj >= effective_opp_hp - 3:
            lethal_bonus = 0.5

    hp_ratio = max(0.0, min(1.0, ai_hp / ai_max_hp))
    defense_urgency = max(
        0.0, min(1.0, (_LOW_HP_FRACTION - hp_ratio) / _LOW_HP_FRACTION)
    )

    if lethal_bonus >= 1.0:
        tactical = (
            damage_score * 0.75
            + disruption_score * 0.10
            + block_score * 0.10
            + resource_score * 0.05
        )
    elif opponent_hp <= _AGGRO_HP_THRESHOLD:
        tactical = (
            damage_score * 0.55
            + disruption_score * 0.15
            + block_score * 0.15
            + resource_score * 0.15
        )
    elif defense_urgency > 0.3:
        tactical = (
            block_score * 0.45
            + damage_score * 0.25
            + disruption_score * 0.15
            + resource_score * 0.15
        )
    else:
        tactical = (
            damage_score * 0.45
            + disruption_score * 0.25
            + block_score * 0.20
            + resource_score * 0.10
        )

    board_threat = context.get("board_threat", 0.2)
    tactical += min(board_threat, 1.0) * block_score * 0.20

    final = mana_efficiency * 0.25 + tactical * 0.75
    if lethal_bonus > 0.0:
        final = max(final, 0.85 * lethal_bonus)
    return max(0.0, min(1.0, final))


# ---------------------------------------------------------------------------
# Context builder (mirrors AIBenchmark._make_context)
# ---------------------------------------------------------------------------

def _build_context(active: Player, opponent: Player) -> Dict:
    return {
        "ai_gold": active.gold_pool,
        "ai_combat": active.combat_pool,
        "ai_hp": active.current_hp,
        "ai_max_hp": active.max_hp,
        "ai_block": active.current_block,
        "ai_champions": len(active.champions_in_play),
        "opponent_hp": opponent.current_hp,
        "opponent_block": opponent.current_block,
        "opponent_champions": len(opponent.champions_in_play),
        "board_threat": 0.2,
        "ai_dominant_faction": active.dominant_faction,
    }


# ---------------------------------------------------------------------------
# Card-play strategy functions
# ---------------------------------------------------------------------------

def _choose_random(hand: List[Card], active: Player, opponent: Player) -> Optional[Card]:
    return random.choice(hand) if hand else None


def _choose_aggro(hand: List[Card], active: Player, opponent: Player) -> Optional[Card]:
    champs = len(active.champions_in_play)
    best, best_val = None, -1
    for c in hand:
        v = _estimate_values(c, champs)["damage"]
        if v > best_val:
            best_val, best = v, c
    return best or _choose_random(hand, active, opponent)


def _choose_econ(hand: List[Card], active: Player, opponent: Player) -> Optional[Card]:
    champs = len(active.champions_in_play)
    best, best_val = None, -1
    for c in hand:
        v = _estimate_values(c, champs)["resource"]
        if v > best_val:
            best_val, best = v, c
    return best or _choose_random(hand, active, opponent)


def _choose_control(hand: List[Card], active: Player, opponent: Player) -> Optional[Card]:
    champs = len(active.champions_in_play)
    best, best_val = None, -1
    for c in hand:
        v = _estimate_values(c, champs)["disruption"]
        if v > best_val:
            best_val, best = v, c
    return best or _choose_random(hand, active, opponent)


def _choose_combo(hand: List[Card], active: Player, opponent: Player) -> Optional[Card]:
    played = active.faction_counts
    best, best_val = None, -1
    for c in hand:
        score = 0
        if c.ally_combat or c.ally_gold or c.ally_health:
            score += 3
        if c.is_champion:
            score += 1
        if c.faction != "neutral" and played.get(c.faction, 0) > 0:
            score += 3
        if score > best_val:
            best_val, best = score, c
    return best if best and best_val > 0 else _choose_random(hand, active, opponent)


def _choose_efficiency(hand: List[Card], active: Player, opponent: Player) -> Optional[Card]:
    best, best_val = None, -1
    for c in hand:
        score = c.sacrifice_combat * 6 + c.draw_cards * 4 + c.gold
        if score > best_val:
            best_val, best = score, c
    return best if best and best_val > 0 else _choose_random(hand, active, opponent)


def _choose_greedy(hand: List[Card], active: Player, opponent: Player) -> Optional[Card]:
    ctx = _build_context(active, opponent)
    champs = len(active.champions_in_play)
    best, best_score = None, -1.0
    for c in hand:
        s = _score_card(c, ctx, champs)
        if s > best_score:
            best_score, best = s, c
    return best


def _choose_lookahead(hand: List[Card], active: Player, opponent: Player) -> Optional[Card]:
    ctx = _build_context(active, opponent)
    champs = len(active.champions_in_play)
    best, best_score = None, -1.0
    for first in hand:
        s = _score_card(first, ctx, champs)
        remaining = [c for c in hand if c is not first]
        follow = max((_score_card(c, ctx, champs) for c in remaining), default=0.0)
        seq = min(1.0, s * 0.65 + follow * 0.35)
        if seq > best_score:
            best_score, best = seq, first
    return best


def _choose_adaptive(hand: List[Card], active: Player, opponent: Player) -> Optional[Card]:
    champs = len(active.champions_in_play)
    # Danger mode – survival first.
    if active.max_hp > 0 and active.current_hp / active.max_hp < 0.4:
        best, best_val = None, -1
        for c in hand:
            vals = _estimate_values(c, champs)
            score = vals["block"] * 2 + vals["damage"]
            if score > best_val:
                best_val, best = score, c
        return best or _choose_greedy(hand, active, opponent)
    # Late-game aggro – push for the kill.
    if opponent.current_hp <= 25:
        return _choose_aggro(hand, active, opponent)
    # Mid-game with champions – leverage combo potential.
    if champs >= 1:
        return _choose_combo(hand, active, opponent)
    # Early game – evaluator-driven.
    return _choose_greedy(hand, active, opponent)


_CARD_CHOOSERS = {
    "Random":     _choose_random,
    "Aggro":      _choose_aggro,
    "Econ":       _choose_econ,
    "Control":    _choose_control,
    "Combo":      _choose_combo,
    "Efficiency": _choose_efficiency,
    "Greedy":     _choose_greedy,
    "Lookahead":  _choose_lookahead,
    "Adaptive":   _choose_adaptive,
}

# ---------------------------------------------------------------------------
# Market-buying strategy functions
# ---------------------------------------------------------------------------

_LETHAL_URGENCY_THRESHOLD = 6


def _affordable(offers: List[Optional[Card]], gold: int) -> List[Tuple[int, Card]]:
    return [
        (i, c)
        for i, c in enumerate(offers)
        if c is not None and c.cost <= gold
    ]


def _market_random(offers: List[Optional[Card]], gold: int, ctx: Dict) -> int:
    aff = _affordable(offers, gold)
    return random.choice(aff)[0] if aff else -1


def _market_scored(offers: List[Optional[Card]], gold: int, ctx: Dict) -> int:
    aff = _affordable(offers, gold)
    if not aff:
        return -1
    ai_combat = ctx.get("ai_combat", 0)
    opp_hp = ctx.get("opponent_hp", 999)
    opp_blk = ctx.get("opponent_block", 0)
    effective = opp_hp + opp_blk
    lethal_urgent = effective > 0 and (effective - ai_combat) <= _LETHAL_URGENCY_THRESHOLD

    champs = ctx.get("ai_champions", 0)
    best_idx, best_s = -1, -1.0
    for idx, c in aff:
        if lethal_urgent:
            s = min(c.combat / 10.0, 1.0)
        else:
            s = _score_card(c, ctx, champs)
        if s > best_s:
            best_s, best_idx = s, idx
    return best_idx


def _market_aggro(offers: List[Optional[Card]], gold: int, ctx: Dict) -> int:
    aff = _affordable(offers, gold)
    if not aff:
        return -1
    best_idx, best_val = -1, -1
    for idx, c in aff:
        if c.combat > best_val:
            best_val, best_idx = c.combat, idx
    return best_idx if best_idx >= 0 else aff[0][0]


def _market_econ(offers: List[Optional[Card]], gold: int, ctx: Dict) -> int:
    aff = _affordable(offers, gold)
    if not aff:
        return -1
    return max(aff, key=lambda x: x[1].cost)[0]


def _market_control(offers: List[Optional[Card]], gold: int, ctx: Dict) -> int:
    aff = _affordable(offers, gold)
    if not aff:
        return -1
    best_idx, best_val = -1, -1
    for idx, c in aff:
        if c.opponent_discard > best_val:
            best_val, best_idx = c.opponent_discard, idx
    return best_idx if best_val > 0 else _market_econ(offers, gold, ctx)


def _market_combo(offers: List[Optional[Card]], gold: int, ctx: Dict) -> int:
    aff = _affordable(offers, gold)
    if not aff:
        return -1
    dominant = ctx.get("ai_dominant_faction", "")
    best_idx, best_score = -1, -1
    for idx, c in aff:
        score = c.ally_combat + c.ally_gold + c.ally_health
        if c.is_champion:
            score += 2
        if dominant and c.faction.lower() == dominant.lower():
            score += 3
        if score > best_score:
            best_score, best_idx = score, idx
    return best_idx if best_score > 0 else _market_scored(offers, gold, ctx)


def _market_efficiency(offers: List[Optional[Card]], gold: int, ctx: Dict) -> int:
    aff = _affordable(offers, gold)
    if not aff:
        return -1
    best_idx, best_score = -1, -1
    for idx, c in aff:
        score = c.sacrifice_combat * 3 + c.draw_cards * 4
        if score > best_score:
            best_score, best_idx = score, idx
    return best_idx if best_score > 0 else _market_econ(offers, gold, ctx)


def _market_adaptive(offers: List[Optional[Card]], gold: int, ctx: Dict) -> int:
    ai_hp = ctx.get("ai_hp", 50)
    ai_max_hp = ctx.get("ai_max_hp", 50)
    opp_hp = ctx.get("opponent_hp", 50)
    champs = ctx.get("ai_champions", 0)

    if ai_max_hp > 0 and ai_hp / ai_max_hp < 0.4:
        aff = _affordable(offers, gold)
        if aff:
            best_idx, best_val = -1, -1
            for idx, c in aff:
                v = c.health * 2 + c.combat
                if v > best_val:
                    best_val, best_idx = v, idx
            if best_idx >= 0:
                return best_idx
    if opp_hp <= 25:
        return _market_aggro(offers, gold, ctx)
    if champs >= 1:
        return _market_combo(offers, gold, ctx)
    return _market_scored(offers, gold, ctx)


_MARKET_CHOOSERS = {
    "Random":     _market_random,
    "Aggro":      _market_aggro,
    "Econ":       _market_econ,
    "Control":    _market_control,
    "Combo":      _market_combo,
    "Efficiency": _market_efficiency,
    "Greedy":     _market_scored,
    "Lookahead":  _market_scored,
    "Adaptive":   _market_adaptive,
}

# ---------------------------------------------------------------------------
# Game simulation (mirrors AIBenchmark._run_game / _run_turn)
# ---------------------------------------------------------------------------

_MAX_TURNS = 40
_MARKET_SIZE = 5
_INITIAL_FIRE_GEMS = 16
_MAX_CARDS_PER_TURN = 30


def _run_turn(
    active: Player,
    opponent: Player,
    strategy: str,
    market: List[Optional[Card]],
    market_pile: List[Card],
    fire_gems: int,
    draw_count: int,
) -> int:
    active.start_turn(draw_count)

    card_chooser = _CARD_CHOOSERS[strategy]
    market_chooser = _MARKET_CHOOSERS[strategy]

    # Play all cards from hand.
    safety = 0
    while active.hand and safety < _MAX_CARDS_PER_TURN:
        safety += 1
        card = card_chooser(list(active.hand), active, opponent)
        if card is None:
            break
        if not active.play_card(card, opponent):
            break

    # Buy from market.
    while True:
        ctx = _build_context(active, opponent)
        idx = market_chooser(market, active.gold_pool, ctx)
        if idx < 0 or idx >= len(market) or market[idx] is None:
            break
        offer = market[idx]
        if offer.cost > active.gold_pool:  # type: ignore[union-attr]
            break
        active.gold_pool -= offer.cost  # type: ignore[union-attr]
        active.buy_card(offer)  # type: ignore[arg-type]
        # Refill the market slot.
        market[idx] = market_pile.pop(0) if market_pile else None

    # Spend leftover gold on fire gems.
    while fire_gems > 0 and active.gold_pool >= 2:
        active.gold_pool -= 2
        active.buy_card(_make_fire_gem())
        fire_gems -= 1

    active.resolve_combat(opponent)
    active.end_turn()
    return fire_gems


def _run_game(
    strategy_a: str,
    strategy_b: str,
    all_market_cards: List[Card],
) -> int:
    """Return 1 if A wins, 2 if B wins, 0 for a draw."""
    player_a = Player("A")
    player_b = Player("B")

    pile = list(all_market_cards)
    random.shuffle(pile)
    market: List[Optional[Card]] = [
        pile.pop(0) if pile else None for _ in range(_MARKET_SIZE)
    ]

    fire_gems = _INITIAL_FIRE_GEMS
    winner = 0

    for turn in range(1, _MAX_TURNS + 1):
        draw_a = 3 if turn == 1 else 5
        fire_gems = _run_turn(player_a, player_b, strategy_a, market, pile, fire_gems, draw_a)
        if player_b.current_hp <= 0:
            winner = 1
            break

        fire_gems = _run_turn(player_b, player_a, strategy_b, market, pile, fire_gems, 5)
        if player_a.current_hp <= 0:
            winner = 2
            break

    if winner == 0:
        if player_a.current_hp > player_b.current_hp:
            winner = 1
        elif player_b.current_hp > player_a.current_hp:
            winner = 2

    return winner


# ---------------------------------------------------------------------------
# Tournament runner (mirrors AIBenchmark round-robin)
# ---------------------------------------------------------------------------

STRATEGIES = [
    "Random",
    "Aggro",
    "Econ",
    "Control",
    "Combo",
    "Efficiency",
    "Greedy",
    "Lookahead",
    "Adaptive",
]

# Seed multipliers matching AIBenchmark.gd constants for reproducibility.
_SEED_STRATEGY_MULT = 10000
_SEED_OPPONENT_MULT = 1000
_SEED_GAME_MULT = 7


def run_tournament(
    market_cards: List[Card],
    games_per_pair: int = 50,
) -> Dict:
    n = len(STRATEGIES)
    wins = [0] * n
    losses = [0] * n
    draws = [0] * n
    h2h = [[0] * n for _ in range(n)]

    for i, strat_a in enumerate(STRATEGIES):
        for j, strat_b in enumerate(STRATEGIES):
            if i == j:
                continue
            wa, wb, wd = 0, 0, 0
            for g in range(games_per_pair):
                seed_val = i * _SEED_STRATEGY_MULT + j * _SEED_OPPONENT_MULT + g * _SEED_GAME_MULT
                random.seed(seed_val)
                result = _run_game(strat_a, strat_b, market_cards)
                if result == 1:
                    wa += 1
                    wins[i] += 1
                    losses[j] += 1
                    h2h[i][j] += 1
                elif result == 2:
                    wb += 1
                    wins[j] += 1
                    losses[i] += 1
                    h2h[j][i] += 1
                else:
                    wd += 1
                    draws[i] += 1
                    draws[j] += 1
            print(f"[BENCH] {strat_a} vs {strat_b} → A={wa}  B={wb}  D={wd}")

    return {"wins": wins, "losses": losses, "draws": draws, "h2h": h2h}


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def _make_entries(results: Dict) -> List[Dict]:
    wins, losses, draws = results["wins"], results["losses"], results["draws"]
    entries = []
    for i, name in enumerate(STRATEGIES):
        total = wins[i] + losses[i] + draws[i]
        wr = (wins[i] + 0.5 * draws[i]) / total if total else 0.0
        ci = 1.96 * math.sqrt(wr * (1.0 - wr) / total) if total else 0.0
        entries.append({
            "name": name,
            "wins": wins[i],
            "losses": losses[i],
            "draws": draws[i],
            "total": total,
            "win_rate": wr,
            "ci_half": ci,
        })
    entries.sort(key=lambda e: e["win_rate"], reverse=True)
    return entries


def print_rankings(results: Dict) -> None:
    entries = _make_entries(results)
    print(
        "\n[BENCH] ══════════════════ STRATEGY RANKINGS ══════════════════════════════"
    )
    print(
        f"[BENCH] {'Strategy':<12}  {'W':>5}  {'L':>5}  {'D':>5}  {'GP':>5}   Win%   95% CI"
    )
    print(
        "[BENCH] ────────────────────────────────────────────────────────────────────"
    )
    for rank, e in enumerate(entries):
        pct = f"{e['win_rate'] * 100:.1f}%"
        ci = f"±{e['ci_half'] * 100:.1f}%"
        print(
            f"[BENCH] #{rank + 1} {e['name']:<10}  {e['wins']:>5}  {e['losses']:>5}  "
            f"{e['draws']:>5}  {e['total']:>5}   {pct}  {ci}"
        )
    print(
        "[BENCH] ══════════════════════════════════════════════════════════════════"
    )


def print_h2h(results: Dict) -> None:
    h2h = results["h2h"]
    n = len(STRATEGIES)
    header = "[BENCH] H2H% (row beats col)  " + "".join(
        f"{s[:6]:>7}" for s in STRATEGIES
    )
    print("\n" + header)
    print("[BENCH] " + "-" * (len(header) - 8))
    for i in range(n):
        row = f"[BENCH] {STRATEGIES[i]:<14}"
        for j in range(n):
            if i == j:
                row += "      -"
            else:
                total_ij = h2h[i][j] + h2h[j][i]
                if total_ij == 0:
                    row += "    n/a"
                else:
                    pct = h2h[i][j] / total_ij * 100.0
                    row += f"  {pct:4.0f}%"
        print(row)
    print("")


def export_csv(results: Dict, path: str) -> None:
    entries = _make_entries(results)
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv_module.writer(f)
        writer.writerow(["Rank", "Strategy", "W", "L", "D", "GP", "WinPct", "CI95Half"])
        for rank, e in enumerate(entries):
            writer.writerow([
                rank + 1,
                e["name"],
                e["wins"],
                e["losses"],
                e["draws"],
                e["total"],
                f"{e['win_rate']:.4f}",
                f"{e['ci_half']:.4f}",
            ])
    print(f"[BENCH] CSV exported → {path}")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="AI strategy benchmark (pure Python, no Godot required)"
    )
    parser.add_argument(
        "--games",
        type=int,
        default=50,
        help="Games per ordered strategy pair (default: 50)",
    )
    parser.add_argument(
        "--csv",
        metavar="FILE",
        default="",
        help="Export results to a CSV file",
    )
    args = parser.parse_args()

    here = os.path.dirname(os.path.abspath(__file__))
    market_path = os.path.join(here, "..", "cards", "marketplace.json")
    if not os.path.isfile(market_path):
        print(
            f"ERROR: marketplace.json not found at {market_path}", file=sys.stderr
        )
        sys.exit(1)

    market_cards = load_market_cards(market_path)
    print(f"[BENCH] Loaded {len(market_cards)} market cards")
    print(
        f"[BENCH] Starting benchmark: {len(STRATEGIES)} strategies"
        f" × {args.games} games per ordered pair"
    )

    results = run_tournament(market_cards, games_per_pair=args.games)
    print_rankings(results)
    print_h2h(results)
    if args.csv:
        export_csv(results, args.csv)


if __name__ == "__main__":
    main()
