extends RefCounted
class_name CardEvaluator

const AGGRO_HP_THRESHOLD: int = 15


func score_card(card: Card, context: Dictionary) -> float:
	if card == null:
		return 0.0

	var ai_mana: int = int(context.get("ai_mana", 0))
	var opponent_hp: int = int(context.get("opponent_hp", 999))
	var board_threat: float = float(context.get("board_threat", 0.0))

	# Cards that cannot be played now should score low, but not always zero,
	# so LOOKAHEAD can still reason about near-future turns.
	var playable_now: bool = card.cost <= ai_mana
	var mana_efficiency: float = 0.1
	if playable_now:
		mana_efficiency = clamp(1.0 - (float(card.cost) / max(float(ai_mana), 1.0)) * 0.5, 0.0, 1.0)

	var estimates: Dictionary = _estimate_card_values(card)
	var damage_score: float = float(estimates.get("damage", 0.0)) / 20.0
	var block_score: float = float(estimates.get("block", 0.0)) / 15.0
	var disruption_score: float = float(estimates.get("disruption", 0.0)) / 10.0
	var resource_score: float = float(estimates.get("resource", 0.0)) / 10.0

	damage_score = clamp(damage_score, 0.0, 1.0)
	block_score = clamp(block_score, 0.0, 1.0)
	disruption_score = clamp(disruption_score, 0.0, 1.0)
	resource_score = clamp(resource_score, 0.0, 1.0)

	# Priority rule requested by design:
	# 1) If opponent HP is high, value disruption/removal over pure damage.
	# 2) If opponent HP is low, value direct damage over resource generation.
	var tactical_score: float
	if opponent_hp > AGGRO_HP_THRESHOLD:
		tactical_score = disruption_score * 0.45 + damage_score * 0.25 + block_score * 0.2 + resource_score * 0.1
	else:
		tactical_score = damage_score * 0.5 + disruption_score * 0.2 + block_score * 0.2 + resource_score * 0.1

	# If current board threat is high, defensive options become more valuable.
	tactical_score += clamp(board_threat, 0.0, 1.0) * block_score * 0.3

	var final_score: float = (mana_efficiency * 0.3) + (tactical_score * 0.7)
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


func _estimate_card_values(card: Card) -> Dictionary:
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
					block_total += int(round(float(value) * 0.7))
				"force_discard":
					disruption_total += value
				"apply_status":
					disruption_total += value
				"gain_energy", "draw_cards", "gain_gold":
					resource_total += value
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

	var values: Dictionary = _estimate_card_values(card)
	var opponent_hp: int = int(context.get("opponent_hp", 0))
	context["opponent_hp"] = max(opponent_hp - int(values.get("damage", 0)), 0)

	var own_block: int = int(context.get("ai_block", 0))
	context["ai_block"] = own_block + int(values.get("block", 0))
