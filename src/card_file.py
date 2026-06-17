from __future__ import annotations

from typing import Tuple, TypedDict


class SimulationShopCardDefinition(TypedDict):
    name: str
    cost: int
    damage: int
    bonus_resources: int


SIMULATION_SHOP_CARDS: Tuple[SimulationShopCardDefinition, ...] = (
    {"name": "Profit", "cost": 1, "damage": 0, "bonus_resources": 2},
    {"name": "Spark", "cost": 1, "damage": 1, "bonus_resources": 0},
)
