extends RefCounted
class_name CardEvaluator

const AGGRO_HP_THRESHOLD: int = 15
# HP fraction below which the AI treats defense as urgent.
const LOW_HP_FRACTION: float = 0.4
# Weight applied when converting healing to block-equivalent value.
const HEALTH_TO_BLOCK_WEIGHT: float = 0.7
# Sentinel mana value used when scoring market cards for purchase desirability
# (not hand playability), so all market cards pass the playable_now check.
const MARKET_EVAL_MANA: int = 99


func score_card(card: Card, context: Dictionary) -> float:
	if card == null:
		return 0.0

	var ai_mana: int = int(context.get("ai_mana", 0))
	var ai_hp: int = int(context.get("ai_hp", 50))
	var ai_max_hp: int = max(int(context.get("ai_max_hp", 50)), 1)
	var ai_combat: int = int(context.get("ai_combat", 0))
	var ai_champions: int = int(context.get("ai_champions", 0))
	var opponent_hp: int = int(context.get("opponent_hp", 999))
	var opponent_block: int = int(context.get("opponent_block", 0))
	var board_threat: float = float(context.get("board_threat", 0.0))

	# Effective HP to defeat: block absorbs damage before HP is reduced, so the
	# AI must deal opponent_hp + opponent_block total damage to achieve lethal.
	var effective_opponent_hp: int = opponent_hp + opponent_block

	# Cards that cannot be played now should score low, but not always zero,
	# so LOOKAHEAD can still reason about near-future turns.
	var playable_now: bool = card.cost <= ai_mana
	var mana_efficiency: float = 0.1
	if playable_now:
		mana_efficiency = clamp(1.0 - (float(card.cost) / max(float(ai_mana), 1.0)) * 0.5, 0.0, 1.0)

	var estimates: Dictionary = _estimate_card_values(card, ai_champions)
	var card_damage: int = int(estimates.get("damage", 0))
	var damage_score: float = clamp(float(card_damage) / 20.0, 0.0, 1.0)
	var block_score: float = clamp(float(estimates.get("block", 0)) / 15.0, 0.0, 1.0)
	var disruption_score: float = clamp(float(estimates.get("disruption", 0)) / 10.0, 0.0, 1.0)
	var resource_score: float = clamp(float(estimates.get("resource", 0)) / 10.0, 0.0, 1.0)

	# Lethal detection: playing this card may let the AI finish off the opponent.
	var lethal_bonus: float = 0.0
	if effective_opponent_hp > 0:
		var projected_damage: int = ai_combat + card_damage
		if projected_damage >= effective_opponent_hp:
			lethal_bonus = 1.0
		elif projected_damage >= effective_opponent_hp - 3:
			lethal_bonus = 0.5

	# Self-preservation urgency: rises linearly from 0 at the threshold to 1
	# when HP reaches 0 (e.g., urgency = 0.5 at half of LOW_HP_FRACTION).
	var hp_ratio: float = clamp(float(ai_hp) / float(ai_max_hp), 0.0, 1.0)
	var defense_urgency: float = clamp((LOW_HP_FRACTION - hp_ratio) / LOW_HP_FRACTION, 0.0, 1.0)

	var tactical_score: float
	if lethal_bonus >= 1.0:
		# Lethal opportunity: prioritize damage above all else.
		tactical_score = damage_score * 0.75 + disruption_score * 0.10 + block_score * 0.10 + resource_score * 0.05
	elif opponent_hp <= AGGRO_HP_THRESHOLD:
		# Opponent is low: push for the kill.
		tactical_score = damage_score * 0.55 + disruption_score * 0.15 + block_score * 0.15 + resource_score * 0.15
	elif defense_urgency > 0.3:
		# AI is threatened: survival takes priority.
		tactical_score = block_score * 0.45 + damage_score * 0.25 + disruption_score * 0.15 + resource_score * 0.15
	else:
		# Mid-game: disruption and damage lead, defense and resources support.
		tactical_score = disruption_score * 0.40 + damage_score * 0.30 + block_score * 0.20 + resource_score * 0.10

	# High board threat increases the value of defensive cards.
	tactical_score += clamp(board_threat, 0.0, 1.0) * block_score * 0.20

	var final_score: float = mana_efficiency * 0.25 + tactical_score * 0.75

	# Guarantee lethal-enabling cards score near the top.
	if lethal_bonus > 0.0:
		final_score = max(final_score, 0.85 * lethal_bonus)

	return clamp(final_score, 0.0, 1.0)


func estimate_sequence_score(cards: Array[Card], context: Dictionary) -> float:
	var running_context: Dictionary = context.duplicate(true)
	var total_score: float = 0.0

	for card: Card in cards:
		total_score += score_card(card, running_context)
		_apply_card_to_sim_state(card, running_context)

	# Normalize by sequence length so longer lines are not always favored.
	if cards.is_empty():
		return 0.0

	return clamp(total_score / float(cards.size()), 0.0, 1.0)


# ai_champions is the number of AI champions currently in play, used to scale
# "for each champion" effects accurately.
func _estimate_card_values(card: Card, ai_champions: int = 0) -> Dictionary:
	var damage_total: int = 0
	var block_total: int = 0
	var disruption_total: int = 0
	var resource_total: int = 0

	# DataCard in this project stores effect payloads in card.effects.
	if card is DataCard:
		var data_card: DataCard = card as DataCard
		for effect: Dictionary in data_card.effects:
			var effect_id: String = String(effect.get("id", ""))
			var value: int = int(effect.get("value", 0))
			match effect_id:
				"gain_combat":
					damage_total += value
				"deal_damage":
					damage_total += value
				"gain_block":
					block_total += value
				"gain_health":
					block_total += int(round(float(value) * HEALTH_TO_BLOCK_WEIGHT))
				"force_discard":
					disruption_total += value
				"apply_status":
					disruption_total += value
				"stun_target_champion":
					# Removing a champion is significant disruption.
					disruption_total += 3
				"gain_energy", "draw_cards", "gain_gold":
					resource_total += value
				"for_each_champion_gain_combat":
					damage_total += value * ai_champions
				"for_each_champion_gain_health":
					block_total += int(round(float(value * ai_champions) * HEALTH_TO_BLOCK_WEIGHT))
				"for_each_other_champion_gain_combat", "for_each_other_guard_gain_combat", "for_each_other_wild_gain_combat":
					damage_total += value * max(ai_champions - 1, 0)
				"champion_data":
					# Champions provide value on every subsequent turn; weight
					# their stats double to reflect their persistent presence.
					damage_total += int(effect.get("combat", 0)) * 2
					resource_total += int(effect.get("gold", 0)) * 2
					block_total += int(round(int(effect.get("health", 0)) * HEALTH_TO_BLOCK_WEIGHT)) * 2
				_:
					pass

	# Compatibility fallback for card classes with direct attack/defense/effects fields.
	if card.get("attack") != null:
		damage_total += int(card.get("attack"))
	if card.get("defense") != null:
		block_total += int(card.get("defense"))

	if card.get("effects") != null and card.get("effects") is Array:
		for raw_effect: Variant in card.get("effects"):
			if raw_effect is Dictionary:
				var effect_map: Dictionary = raw_effect
				var effect_kind: String = String(effect_map.get("type", effect_map.get("id", "")))
				var amount: int = int(effect_map.get("value", 1))
				if effect_kind in ["stun", "silence", "discard", "weaken", "vulnerable", "remove"]:
					disruption_total += amount
				if effect_kind in ["draw", "energy", "mana"]:
					resource_total += amount

	return {
		"damage": damage_total,
		"block": block_total,
		"disruption": disruption_total,
		"resource": resource_total
	}


func _apply_card_to_sim_state(card: Card, context: Dictionary) -> void:
	var ai_mana: int = int(context.get("ai_mana", 0))
	context["ai_mana"] = max(ai_mana - card.cost, 0)

	var ai_champions: int = int(context.get("ai_champions", 0))
	var values: Dictionary = _estimate_card_values(card, ai_champions)

	var own_block: int = int(context.get("ai_block", 0))
	context["ai_block"] = own_block + int(values.get("block", 0))

	# In Hero Realms, combat is resolved at end of turn rather than applied
	# card by card. Track accumulated combat so the lethal check in score_card
	# can correctly compare total projected damage against opponent_hp + block.
	# opponent_hp is intentionally left unchanged here so the check is not
	# corrupted by double-subtracting damage in subsequent score_card calls.
	var own_combat: int = int(context.get("ai_combat", 0))
	context["ai_combat"] = own_combat + int(values.get("damage", 0))

	var own_gold: int = int(context.get("ai_gold", 0))
	context["ai_gold"] = own_gold + int(values.get("resource", 0))
