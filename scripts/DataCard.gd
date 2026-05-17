extends Card
class_name DataCard

var effects: Array[Dictionary] = []


func setup_from_dict(data: Dictionary) -> void:
	card_name = String(data.get("name", "Card"))
	cost = int(data.get("cost", 1))
	description = String(data.get("description", ""))
	card_type = String(data.get("type", "Skill"))
	image_path = String(data.get("image_path", ""))
	if image_path.is_empty() and GameState != null:
		image_path = GameState.find_card_image_path(card_name)
	effects.clear()

	for effect: Dictionary in data.get("effects", []):
		effects.append(effect.duplicate(true))


func play(target: Node) -> void:
	for effect: Dictionary in effects:
		var effect_id := String(effect.get("id", ""))
		var value := int(effect.get("value", 0))

		match effect_id:
			"deal_damage":
				CardEffect.deal_damage(target, value)
			"gain_block":
				CardEffect.gain_block(GameState, value)
			"apply_status":
				CardEffect.apply_status(target, String(effect.get("status", "")), value)
			_:
				push_warning("Unknown card effect id: %s" % effect_id)
