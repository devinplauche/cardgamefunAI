from __future__ import annotations

from typing import Tuple, TypedDict


BASE_GAME_SOURCE_URL = "https://www.herorealms.com/base-game/"


class SimulationShopCardDefinition(TypedDict):
    name: str
    cost: int
    damage: int
    bonus_resources: int


class BaseStarterCardDefinition(TypedDict):
    name: str
    damage: int
    bonus_resources: int
    count: int


BASE_STARTER_DECK_CARDS: Tuple[BaseStarterCardDefinition, ...] = (
    {"name": "Gold", "damage": 0, "bonus_resources": 1, "count": 7},
    {"name": "Dagger", "damage": 1, "bonus_resources": 0, "count": 1},
    {"name": "Short Sword", "damage": 2, "bonus_resources": 0, "count": 1},
    {"name": "Ruby", "damage": 0, "bonus_resources": 2, "count": 1},
)


SIMULATION_SHOP_CARDS: Tuple[SimulationShopCardDefinition, ...] = (
    {"name": "Profit", "cost": 1, "damage": 0, "bonus_resources": 2},
    {"name": "Spark", "cost": 1, "damage": 1, "bonus_resources": 0},
)
