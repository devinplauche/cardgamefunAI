"""Tunable weights for the card-valuation heuristics.

Both valuation functions were fixed integer formulas:

    _card_score   = cost*10 + combat*4 + gold*3 + health*3 + draw*5 + champ_hp*2
    _buy_priority = cost    + combat*2 + gold*2 + draw*2

Neither has any term for ally effects or sacrifice access, so 55 of 96 cards
carry printed value that both price at exactly zero. Four months of real play
(936 games, baseline 56.84%) put the three largest per-card lifts on cards
whose edge lives entirely in those unpriced terms: Taxation +23.2pp (z=5.7,
Imperial ally grants 6 health), The Rot +11.2pp (z=2.1, sacrifice_card) and
Death Touch +9.2pp (z=2.0, sacrifice_card).

DEFAULTS reproduce the original formulas exactly, so importing this module
changes nothing until weights are replaced. The added terms default to 0.0,
which is what the old code implicitly assumed.

Ally weights are deliberately separate from their non-ally counterparts. An
ally effect is conditional on holding another card of the faction, so it
cannot be worth the same as an unconditional one, and forcing them to share a
weight would bake in that assumption before measuring it.
"""

from __future__ import annotations

DEFAULTS: dict[str, float] = {
    # --- original _card_score terms ---
    "cost": 10.0,
    "combat": 4.0,
    "gold": 3.0,
    "health": 3.0,
    "draw": 5.0,
    "champion_health": 2.0,
    # --- previously unpriced ---
    "ally_combat": 0.0,
    "ally_gold": 0.0,
    "ally_health": 0.0,
    "ally_draw": 0.0,
    "sacrifice_card": 0.0,
    # --- original _buy_priority terms (separate scale, deliberately) ---
    "buy_cost": 1.0,
    "buy_combat": 2.0,
    "buy_gold": 2.0,
    "buy_draw": 2.0,
    "buy_ally": 0.0,
    "buy_sacrifice": 0.0,
}

#: Order used when packing/unpacking a CMA-ES parameter vector. Fixed so a
#: saved vector keeps its meaning across runs.
PARAM_ORDER = tuple(DEFAULTS)

_active: dict[str, float] = dict(DEFAULTS)


def get(name: str) -> float:
    return _active[name]


def snapshot() -> dict[str, float]:
    return dict(_active)


def set_weights(weights: dict[str, float]) -> None:
    """Replace the active weights and invalidate anything derived from them."""
    _active.update(weights)
    _invalidate()


def reset() -> None:
    _active.clear()
    _active.update(DEFAULTS)
    _invalidate()


def to_vector(weights: dict[str, float] | None = None) -> list[float]:
    w = weights if weights is not None else _active
    return [w[k] for k in PARAM_ORDER]


def from_vector(vec) -> dict[str, float]:
    return {k: float(v) for k, v in zip(PARAM_ORDER, vec)}


def _invalidate() -> None:
    """_buy_priority memoizes per card id; a stale cache would silently keep
    scoring with the previous candidate's weights for the rest of a fit."""
    try:
        from web.session import _BUY_PRIORITY_CACHE
        _BUY_PRIORITY_CACHE.clear()
    except Exception:  # pragma: no cover - import cycle during early startup
        pass
