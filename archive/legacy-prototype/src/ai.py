from __future__ import annotations
from typing import Optional
from src.engine import Player, Card
import random


def _sum_effect(card: Card, key: str) -> int:
    if isinstance(card.data, dict):
        val = card.data.get(key, 0)
        if isinstance(val, (int, float)):
            return int(val)
    return 0


class AggressiveAI:
    """Prioritizes highest-damage cards. Plays the biggest attack it can."""

    @staticmethod
    def choose_card(player: Player, opponent: Player) -> Optional[Card]:
        best: Optional[Card] = None
        best_val = -1
        for c in list(player.hand):
            dmg = _sum_effect(c, 'damage')
            net = dmg - _sum_effect(c, 'self_damage')
            if net > best_val:
                best = c
                best_val = net
        return best

    @staticmethod
    def take_turn(player: Player, opponent: Player) -> Optional[Card]:
        card = AggressiveAI.choose_card(player, opponent)
        if card:
            player.play_card(card, target=opponent)
            return card
        return None


class DefensiveAI:
    """Prioritizes armor gain and healing over damage."""

    @staticmethod
    def choose_card(player: Player, opponent: Player) -> Optional[Card]:
        if player.hp < 12:
            best: Optional[Card] = None
            best_val = -1
            for c in list(player.hand):
                heal = _sum_effect(c, 'heal') * 2 + _sum_effect(c, 'armor_gain')
                if heal > best_val:
                    best = c
                    best_val = heal
            if best:
                return best

        best = None
        best_val = -1
        for c in list(player.hand):
            score = _sum_effect(c, 'armor_gain') * 2 + _sum_effect(c, 'heal') + _sum_effect(c, 'damage')
            if score > best_val:
                best = c
                best_val = score
        return best

    @staticmethod
    def take_turn(player: Player, opponent: Player) -> Optional[Card]:
        card = DefensiveAI.choose_card(player, opponent)
        if card:
            player.play_card(card, target=opponent)
            return card
        return None


class BalancedAI:
    """Balances between damage, armor, and healing. Values card draw."""

    @staticmethod
    def choose_card(player: Player, opponent: Player) -> Optional[Card]:
        best = None
        best_val = -1
        for c in list(player.hand):
            score = (_sum_effect(c, 'damage')
                     + _sum_effect(c, 'armor_gain')
                     + _sum_effect(c, 'heal')
                     + _sum_effect(c, 'draw')
                     - _sum_effect(c, 'self_damage'))
            if score > best_val:
                best = c
                best_val = score
        return best

    @staticmethod
    def take_turn(player: Player, opponent: Player) -> Optional[Card]:
        card = BalancedAI.choose_card(player, opponent)
        if card:
            player.play_card(card, target=opponent)
            return card
        return None


class RandomAI:
    """Plays a random card from hand."""

    @staticmethod
    def choose_card(player: Player, opponent: Player) -> Optional[Card]:
        if not player.hand:
            return None
        return random.choice(list(player.hand))

    @staticmethod
    def take_turn(player: Player, opponent: Player) -> Optional[Card]:
        card = RandomAI.choose_card(player, opponent)
        if card:
            player.play_card(card, target=opponent)
            return card
        return None


# Keep SimpleAI for backward compatibility
class SimpleAI(AggressiveAI):
    pass
