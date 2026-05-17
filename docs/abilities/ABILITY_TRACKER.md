# Hero Realms Base Ability Tracker

This tracker lists the unique parsed ability effect IDs currently recognized from the base market file and their implementation status.

## Core Resource Abilities
- set_faction: Implemented, parsed, tested
- gain_combat: Implemented, parsed, tested
- gain_gold: Implemented, parsed, tested
- gain_health: Implemented, parsed, tested
- draw_cards: Implemented, parsed, tested

## Discard and Disruption
- force_discard: Implemented, parsed, tested
- stun_target_champion: Implemented, parsed, tested
- sacrifice_force_discard: Implemented, parsed, tested in simulation path

## Draw/Discard Ordering
- draw_then_discard: Implemented, parsed, tested
- draw_up_to_then_discard: Implemented, parsed, tested

Notes:
- Rampage semantics are modeled as draw two then discard two weakest from hand.
- Discard selection only chooses from current hand, so already played cards are never discarded.

## Board-Scaled Effects
- for_each_other_guard_gain_combat: Implemented, parsed, tested
- for_each_other_champion_gain_combat: Implemented, parsed, tested
- for_each_other_wild_gain_combat: Implemented, parsed, tested in simulation path
- for_each_champion_gain_health: Implemented, parsed, tested in simulation path

Notes:
- Man-at-Arms semantics are modeled as base combat plus per-other-guard scaling when expended.

## Choice Abilities
- choice_gain_combat_or_health: Implemented with deterministic combat-preferred choice
- choice_gain_gold_or_combat: Implemented with deterministic gold-preferred choice
- choice_gain_gold_or_health_per_champion: Implemented with deterministic gold-preferred choice

## Champion Flow
- champion_data: Implemented, parsed, tested
- prepare_champion: Implemented, parsed, tested
- recover_discard_to_topdeck: Implemented, parsed, tested

## Acquisition Modifiers
- next_acquire_to_topdeck_action: Implemented, parsed, tested
- next_acquire_to_topdeck_any: Implemented, parsed, tested in simulation path
- next_acquire_to_hand_any: Implemented, parsed, tested

## Ally Handling
- ally_bonus: Implemented, parsed, tested

Ally bonus currently supports:
- combat, gold, health
- draw_cards
- draw_then_discard
- prepare_champion
- stun_target_champion
- force_discard
- next_acquire_to_topdeck_action
- next_acquire_to_topdeck_any
- next_acquire_to_hand_any

## Sacrifice Handling
- sacrifice_combat_offer: Implemented, parsed, tested
- sacrifice_for_additional_combat: Implemented, parsed, tested in simulation path
