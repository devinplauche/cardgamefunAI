extends Node
class_name GameStateController

signal state_changed

var player_max_hp: int = 50
var player_hp: int = 50
var player_block: int = 0
var player_max_energy: int = 3
var player_energy: int = 3
var player_statuses: Dictionary = {}

# To add a new card, create a new entry in data/cards.json and then place that
# card's id into starting_deck_ids, rewards, shops, or any future deck source.
var starting_deck_ids: Array[String] = [
	"gold_coin",
	"gold_coin",
	"gold_coin",
	"gold_coin",
	"gold_coin",
	"gold_coin",
	"gold_coin",
	"ruby",
	"dagger",
	"sword"
]

const MARKET_SIZE: int = 5

var card_database: Dictionary = {}
var enemy_database: Dictionary = {}
var marketplace_cards: Array[Dictionary] = []
var card_image_lookup: Dictionary = {}
var deck: Deck


func _ready() -> void:
	load_databases()
	reset_for_battle()


func load_databases() -> void:
	card_database = _load_json_file("res://data/cards.json")
	enemy_database = _load_json_file("res://data/enemies.json")
	_index_card_images("res://cards/images")
	marketplace_cards = _load_hero_realms_market_file("res://cards/hero-realms-base.txt")


func reset_for_battle() -> void:
	player_hp = player_max_hp
	player_block = 0
	player_energy = player_max_energy
	player_statuses.clear()
	build_starting_deck()
	emit_changed()


func build_starting_deck() -> void:
	deck = Deck.new()
	var cards: Array[Card] = create_cards_from_ids(starting_deck_ids)
	deck.setup(cards)


func create_cards_from_ids(card_ids: Array[String]) -> Array[Card]:
	var cards: Array[Card] = []
	for card_id: String in card_ids:
		var created_card: Card = create_card_from_id(card_id)
		if created_card != null:
			cards.append(created_card)
	return cards


func create_card_from_id(card_id: String) -> Card:
	var data: Dictionary = card_database.get(card_id, {})
	if data.is_empty():
		push_warning("Missing card id: %s" % card_id)
		return null

	var card: DataCard = DataCard.new()
	card.setup_from_dict(data)
	return card


func create_market_card_from_entry(entry: Dictionary) -> Card:
	if entry.is_empty():
		return null

	var entry_effects: Array[Dictionary] = []
	if entry.has("effects") and entry["effects"] is Array:
		for raw_effect: Variant in entry["effects"]:
			if raw_effect is Dictionary:
				entry_effects.append((raw_effect as Dictionary).duplicate(true))

	var generated_data: Dictionary = {
		"name": String(entry.get("name", "Market Card")),
		"cost": 0,
		"type": String(entry.get("type", "action")),
		"image_path": String(entry.get("image_path", "")),
		"description": String(entry.get("effect", "")),
		"effects": entry_effects
	}

	if entry_effects.is_empty():
		generated_data["effects"] = _build_basic_effects_from_entry(entry)

	var card: DataCard = DataCard.new()
	card.setup_from_dict(generated_data)
	return card


func _build_basic_effects_from_entry(entry: Dictionary) -> Array[Dictionary]:
	var effects: Array[Dictionary] = []
	var combat: int = int(entry.get("combat", 0))
	var gold: int = int(entry.get("gold", 0))
	var health: int = int(entry.get("health", 0))
	var faction: String = String(entry.get("faction", "neutral"))
	var ally_combat: int = int(entry.get("ally_combat", 0))
	var ally_gold: int = int(entry.get("ally_gold", 0))
	var ally_health: int = int(entry.get("ally_health", 0))
	var draw_cards_count: int = int(entry.get("draw_cards", 0))
	var sacrifice_combat: int = int(entry.get("sacrifice_combat", 0))
	var opponent_discard: int = int(entry.get("opponent_discard", 0))

	effects.append({"id": "set_faction", "faction": faction})
	if combat > 0:
		effects.append({"id": "gain_combat", "value": combat})
	if gold > 0:
		effects.append({"id": "gain_gold", "value": gold})
	if health > 0:
		effects.append({"id": "gain_health", "value": health})
	if draw_cards_count > 0:
		effects.append({"id": "draw_cards", "value": draw_cards_count})
	if sacrifice_combat > 0:
		effects.append({"id": "sacrifice_combat_offer", "value": sacrifice_combat})
	if opponent_discard > 0:
		effects.append({"id": "force_discard", "value": opponent_discard})
	if ally_combat > 0 or ally_gold > 0 or ally_health > 0:
		effects.append({
			"id": "ally_bonus",
			"faction": faction,
			"combat": ally_combat,
			"gold": ally_gold,
			"health": ally_health
		})

	if String(entry.get("type", "")).to_lower().contains("champion"):
		effects.append({
			"id": "champion_data",
			"defense": int(entry.get("defense", 3)),
			"guard": bool(entry.get("guard", false)),
			"combat": combat,
			"gold": gold,
			"health": health
		})

	return effects


func get_enemy_data(enemy_id: String) -> Dictionary:
	# To add a new enemy, create a new entry in data/enemies.json and then ask
	# the scene or encounter generator to request that enemy id.
	return enemy_database.get(enemy_id, {})


func spend_energy(amount: int) -> bool:
	if amount > player_energy:
		return false

	player_energy -= amount
	emit_changed()
	return true


func gain_block(amount: int) -> void:
	if amount <= 0:
		return

	player_block += amount
	emit_changed()


func clear_block() -> void:
	player_block = 0
	emit_changed()


func receive_damage(amount: int) -> void:
	if amount <= 0:
		return

	var damage_after_block: int = max(amount - player_block, 0)
	player_block = max(player_block - amount, 0)
	player_hp = max(player_hp - damage_after_block, 0)
	emit_changed()


func apply_status(status_name: String, stacks: int) -> void:
	if status_name.is_empty() or stacks <= 0:
		return

	player_statuses[status_name] = int(player_statuses.get(status_name, 0)) + stacks
	emit_changed()


func emit_changed() -> void:
	state_changed.emit()


func _load_json_file(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		push_error("Missing data file: %s" % path)
		return {}

	var file := FileAccess.open(path, FileAccess.READ)
	var json_text := file.get_as_text()
	var json := JSON.new()
	var parse_result := json.parse(json_text)

	if parse_result != OK:
		push_error("Failed to parse %s: %s" % [path, json.get_error_message()])
		return {}

	if json.data is Dictionary:
		return json.data

	push_error("JSON root must be a dictionary: %s" % path)
	return {}


func _load_json_array_file(path: String) -> Array[Dictionary]:
	if not FileAccess.file_exists(path):
		push_error("Missing data file: %s" % path)
		return []

	var file := FileAccess.open(path, FileAccess.READ)
	var json_text := file.get_as_text()
	var json := JSON.new()
	var parse_result := json.parse(json_text)

	if parse_result != OK:
		push_error("Failed to parse %s: %s" % [path, json.get_error_message()])
		return []

	if json.data is Array:
		var output: Array[Dictionary] = []
		for row: Variant in json.data:
			if row is Dictionary:
				output.append(row.duplicate(true))
		return output

	push_error("JSON root must be an array: %s" % path)
	return []


func _load_hero_realms_market_file(path: String) -> Array[Dictionary]:
	if not FileAccess.file_exists(path):
		push_error("Missing market file: %s" % path)
		return []

	var file := FileAccess.open(path, FileAccess.READ)
	var text: String = file.get_as_text()
	var lines: PackedStringArray = text.split("\n")

	var rows: Array[String] = []
	var current_row: String = ""

	for raw_line: String in lines:
		var line: String = raw_line.strip_edges()
		if line.begins_with("Base Set"):
			if not current_row.is_empty():
				rows.append(current_row)
			current_row = line
		else:
			if current_row.is_empty():
				continue
			if not line.is_empty():
				current_row += " " + line

	if not current_row.is_empty():
		rows.append(current_row)

	var market: Array[Dictionary] = []
	for row: String in rows:
		var fields: PackedStringArray = row.split("\t")
		if fields.size() < 10:
			continue

		var source: String = String(fields[9]).strip_edges()
		if source != "Market Deck":
			continue

		var name: String = String(fields[2]).strip_edges()
		var card_type: String = String(fields[4]).strip_edges()
		var faction: String = String(fields[5]).strip_edges().to_lower()
		var cost: int = int(String(fields[6]).strip_edges())
		var defense_field: String = ""
		if fields.size() > 7:
			defense_field = String(fields[7]).strip_edges()

		var effect_text: String = String(fields[3])
		var ally_text: String = _extract_section_after_keyword(effect_text, "ally")
		var sacrifice_text: String = _extract_section_after_keyword(effect_text, "sacrifice")
		var combat: int = _extract_first_number(effect_text, "combat")
		var gold: int = _extract_first_number(effect_text, "gold")
		var health: int = _extract_first_number(effect_text, "health")
		var ally_combat: int = _extract_first_number(ally_text, "combat")
		var ally_gold: int = _extract_first_number(ally_text, "gold")
		var ally_health: int = _extract_first_number(ally_text, "health")
		var draw_cards_count: int = _extract_draw_count(effect_text)
		var sacrifice_combat: int = _extract_first_number(sacrifice_text, "combat")
		var opponent_discard: int = _extract_opponent_discard_count(effect_text)
		var parsed_effects: Array[Dictionary] = _parse_effects_for_market_card(effect_text, card_type, faction, defense_field)

		var defense: int = 0
		var guard: bool = false
		if not defense_field.is_empty():
			defense = _extract_first_number(defense_field, "")
			guard = defense_field.to_lower().contains("guard")

		market.append({
			"name": name,
			"faction": faction,
			"type": card_type,
			"image_path": find_card_image_path(name),
			"gallery_url": _build_card_gallery_url(name),
			"image_url": "",
			"cost": cost,
			"combat": combat,
			"gold": gold,
			"health": health,
			"draw_cards": draw_cards_count,
			"sacrifice_combat": sacrifice_combat,
			"opponent_discard": opponent_discard,
			"ally_combat": ally_combat,
			"ally_gold": ally_gold,
			"ally_health": ally_health,
			"effect": effect_text,
			"effects": parsed_effects,
			"defense": defense,
			"guard": guard
		})

	return market


func _extract_first_number(text: String, keyword: String) -> int:
	var pattern: String
	if keyword.is_empty():
		pattern = "(\\d+)"
	else:
		pattern = "(\\d+)\\s+" + keyword

	var regex := RegEx.new()
	var ok: int = regex.compile(pattern)
	if ok != OK:
		return 0

	var match: RegExMatch = regex.search(text.to_lower())
	if match == null:
		return 0

	return int(match.get_string(1))


func _extract_section_after_keyword(text: String, keyword: String) -> String:
	var lower_text: String = text.to_lower()
	var idx: int = lower_text.find(keyword.to_lower())
	if idx == -1:
		return ""

	var section: String = text.substr(idx)
	var hr_idx: int = section.find("<hr>")
	if hr_idx != -1:
		section = section.substr(0, hr_idx)
	return section


func _extract_draw_count(text: String) -> int:
	var lower: String = text.to_lower()
	if lower.contains("draw two cards"):
		return 2
	if lower.contains("draw a card"):
		return 1

	var regex := RegEx.new()
	if regex.compile("draw\\s+(\\d+)\\s+cards") != OK:
		return 0
	var match: RegExMatch = regex.search(lower)
	if match == null:
		return 0
	return int(match.get_string(1))


func _build_card_gallery_url(card_name: String) -> String:
	# We provide a stable source page link. Image files are intentionally not bundled.
	return "https://www.herorealms.com/card-gallery/"


func find_card_image_path(card_name: String) -> String:
	if card_name.is_empty():
		return ""

	var key: String = _normalize_card_key(card_name)
	var compact_key: String = key.replace("-", "")
	if card_image_lookup.has(key):
		return String(card_image_lookup[key])

	# Support filenames like BAS-EN-001-arkus-imperial-dragon.jpg by matching tail.
	for indexed_key: String in card_image_lookup.keys():
		var indexed_compact: String = indexed_key.replace("-", "")
		if indexed_key.contains(key) or key.contains(indexed_key):
			return String(card_image_lookup[indexed_key])
		if indexed_compact.contains(compact_key) or compact_key.contains(indexed_compact):
			return String(card_image_lookup[indexed_key])

	return ""


func _index_card_images(images_dir: String) -> void:
	card_image_lookup.clear()
	var dir: DirAccess = DirAccess.open(images_dir)
	if dir == null:
		return

	dir.list_dir_begin()
	while true:
		var file_name: String = dir.get_next()
		if file_name.is_empty():
			break
		if dir.current_is_dir():
			continue

		var lower: String = file_name.to_lower()
		var valid_extension: bool = lower.ends_with(".png") or lower.ends_with(".jpg") or lower.ends_with(".jpeg") or lower.ends_with(".webp") or lower.ends_with(".svg")
		if not valid_extension:
			continue

		var stem: String = file_name.get_basename()
		var normalized: String = _normalize_card_key(stem)
		if normalized.is_empty():
			continue

		card_image_lookup[normalized] = "%s/%s" % [images_dir, file_name]

	dir.list_dir_end()


func _normalize_card_key(value: String) -> String:
	var lower: String = value.to_lower()
	lower = lower.replace("'", "")
	lower = lower.replace(",", "")
	lower = lower.replace("_", "-")
	lower = lower.replace(" ", "-")

	var cleaned: String = ""
	for i: int in range(lower.length()):
		var c: String = lower.substr(i, 1)
		if (c >= "a" and c <= "z") or (c >= "0" and c <= "9") or c == "-":
			cleaned += c

	while cleaned.contains("--"):
		cleaned = cleaned.replace("--", "-")

	if cleaned.begins_with("-"):
		cleaned = cleaned.substr(1)
	if cleaned.ends_with("-"):
		cleaned = cleaned.substr(0, cleaned.length() - 1)

	return cleaned


func _extract_opponent_discard_count(text: String) -> int:
	var lower: String = text.to_lower()
	if not lower.contains("opponent") or not lower.contains("discard"):
		return 0

	if lower.contains("opponent discards a card"):
		return 1

	var regex := RegEx.new()
	if regex.compile("opponent\\s+discards\\s+(\\d+)\\s+card") != OK:
		return 0

	var match: RegExMatch = regex.search(lower)
	if match == null:
		return 1

	return int(match.get_string(1))


func _parse_effects_for_market_card(effect_text: String, card_type: String, faction: String, defense_field: String) -> Array[Dictionary]:
	var effects: Array[Dictionary] = []
	var lower: String = effect_text.to_lower()

	effects.append({"id": "set_faction", "faction": faction})

	var ally_text: String = _extract_section_after_keyword(effect_text, "ally")
	var sacrifice_text: String = _extract_section_after_keyword(effect_text, "sacrifice")
	var base_no_ally_sac: String = effect_text
	var lower_base: String = lower
	var ally_marker: int = lower_base.find("ally")
	if ally_marker != -1:
		base_no_ally_sac = effect_text.substr(0, ally_marker)
		lower_base = base_no_ally_sac.to_lower()
	var sacrifice_marker: int = lower_base.find("sacrifice")
	if sacrifice_marker != -1:
		base_no_ally_sac = base_no_ally_sac.substr(0, sacrifice_marker)
		lower_base = base_no_ally_sac.to_lower()

	# Draw patterns.
	var base_draw_then_discard: bool = lower_base.contains("draw a card, then discard a card") or lower_base.contains("draw a card then discard a card") or (lower_base.contains("you may draw a card") and lower_base.contains("if you do") and lower_base.contains("discard a card"))
	if lower_base.contains("draw two cards"):
		effects.append({"id": "draw_cards", "value": 2})
	elif lower_base.contains("draw a card") and not base_draw_then_discard:
		effects.append({"id": "draw_cards", "value": 1})

	if lower_base.contains("draw a card, then discard a card") or lower_base.contains("draw a card then discard a card"):
		effects.append({"id": "draw_then_discard", "draw": 1, "discard": 1, "value": 1})
	elif lower_base.contains("you may draw a card") and lower_base.contains("if you do") and lower_base.contains("discard a card"):
		effects.append({"id": "draw_then_discard", "draw": 1, "discard": 1, "value": 1})
	elif lower_base.contains("draw up to two cards") and lower_base.contains("discard that many"):
		effects.append({"id": "draw_up_to_then_discard", "max_draw": 2, "value": 2})

	# Selection patterns — only one branch fires; numeric gains are mutually exclusive with choices.
	if lower_base.contains("<i>or</i>"):
		if lower_base.contains("gain 3 combat") and lower_base.contains("gain 4 health"):
			effects.append({"id": "choice_gain_combat_or_health", "value": 3, "health": 4})
		elif lower_base.contains("gain 1 gold") and lower_base.contains("gain 2 combat"):
			effects.append({"id": "choice_gain_gold_or_combat", "gold": 1, "combat": 2})
		elif lower_base.contains("gain 1 gold") and lower_base.contains("gain 1 combat"):
			effects.append({"id": "choice_gain_gold_or_combat", "gold": 1, "combat": 1})
		elif lower_base.contains("gain 1 gold") and lower_base.contains("for each champion") and lower_base.contains("health"):
			effects.append({"id": "choice_gain_gold_or_health_per_champion", "gold": 1, "health_per_champion": 1})
	else:
		_append_numeric_gain_effects(effects, base_no_ally_sac)

	# Scaling by board state.
	if lower_base.contains("for each other guard"):
		effects.append({"id": "for_each_other_guard_gain_combat", "value": 1})
	if lower_base.contains("for each other champion"):
		effects.append({"id": "for_each_other_champion_gain_combat", "value": 1})
	if lower_base.contains("for each champion you have in play") and lower_base.contains("combat"):
		effects.append({"id": "for_each_champion_gain_combat", "value": 2})
	if lower_base.contains("for each champion you have in play") and lower_base.contains("health"):
		effects.append({"id": "for_each_champion_gain_health", "value": 1})
	if lower_base.contains("for each other {wild} card"):
		effects.append({"id": "for_each_other_wild_gain_combat", "value": 1})

	# Direct manipulation effects.
	if lower_base.contains("prepare a champion"):
		effects.append({"id": "prepare_champion", "value": 1})
	if lower_base.contains("stun target champion"):
		effects.append({"id": "stun_target_champion", "value": 1})
	if lower_base.contains("put a card from your discard pile on top of your deck"):
		effects.append({"id": "recover_discard_to_topdeck", "champion_only": false, "value": 1})
	if lower_base.contains("take a champion from your discard pile and put it on top of your deck"):
		effects.append({"id": "recover_discard_to_topdeck", "champion_only": true, "value": 1})

	# Opponent discard / sacrifice mechanics.
	var force_discard: int = _extract_opponent_discard_count(base_no_ally_sac)
	if force_discard > 0:
		effects.append({"id": "force_discard", "value": force_discard})

	if lower_base.contains("you may sacrifice"):
		if lower_base.contains("up to two cards"):
			effects.append({"id": "sacrifice_combat_offer", "value": 3, "max_cards": 2})
		elif lower_base.contains("additional {3 combat}"):
			effects.append({"id": "sacrifice_for_additional_combat", "value": 3})
		elif lower_base.contains("additional {2 combat}"):
			effects.append({"id": "sacrifice_for_additional_combat", "value": 2})
		else:
			effects.append({"id": "sacrifice_combat_offer", "value": 2})

	# Ally text.
	if not ally_text.is_empty():
		var ally_lower: String = ally_text.to_lower()
		var ally_combat: int = _extract_first_number(ally_text, "combat")
		var ally_gold: int = _extract_first_number(ally_text, "gold")
		var ally_health: int = _extract_first_number(ally_text, "health")
		if ally_combat > 0 or ally_gold > 0 or ally_health > 0:
			effects.append({
				"id": "ally_bonus",
				"faction": faction,
				"combat": ally_combat,
				"gold": ally_gold,
				"health": ally_health
			})

		var ally_draw_then_discard: bool = ally_lower.contains("draw a card, then discard a card") or (ally_lower.contains("you may draw a card") and ally_lower.contains("if you do") and ally_lower.contains("discard a card"))
		if ally_lower.contains("draw a card") and not ally_draw_then_discard:
			effects.append({"id": "ally_bonus", "faction": faction, "draw_cards": 1})
		if ally_lower.contains("draw a card, then discard a card"):
			effects.append({"id": "ally_bonus", "faction": faction, "draw_then_discard": 1})
		if ally_lower.contains("you may draw a card") and ally_lower.contains("if you do") and ally_lower.contains("discard a card"):
			effects.append({"id": "ally_bonus", "faction": faction, "draw_then_discard": 1})
		if ally_lower.contains("prepare a champion"):
			effects.append({"id": "ally_bonus", "faction": faction, "prepare_champion": 1})
		if ally_lower.contains("stun target champion"):
			effects.append({"id": "ally_bonus", "faction": faction, "stun_target_champion": 1})
		if ally_lower.contains("target opponent discards a card"):
			effects.append({"id": "ally_bonus", "faction": faction, "force_discard": 1})
		if ally_lower.contains("next action you acquire") and ally_lower.contains("top of your deck"):
			effects.append({"id": "ally_bonus", "faction": faction, "next_acquire_to_topdeck_action": 1})
		if ally_lower.contains("next card you acquire") and ally_lower.contains("into your hand"):
			effects.append({"id": "ally_bonus", "faction": faction, "next_acquire_to_hand_any": 1})
		if ally_lower.contains("next card you acquire") and ally_lower.contains("top of your deck"):
			effects.append({"id": "ally_bonus", "faction": faction, "next_acquire_to_topdeck_any": 1})

	# Sacrifice section standalone effects.
	if not sacrifice_text.is_empty():
		var s_lower: String = sacrifice_text.to_lower()
		var is_external: bool = s_lower.contains("hand or discard pile") or s_lower.contains("hand and/or discard pile")
		if is_external:
			# External sacrifice: targets a card in hand or discard pile (not the source card itself)
			# Check whether a combat bonus is granted for sacrificing
			var bonus_combat: int = 0
			if s_lower.contains("additional"):
				bonus_combat = _extract_first_number(sacrifice_text, "combat")
			if bonus_combat > 0:
				# e.g. Krythos: "sacrifice a card in hand/discard. If you do, gain additional 3 combat."
				effects.append({"id": "sacrifice_for_additional_combat", "value": bonus_combat, "starters_only": true})
			else:
				# e.g. Death Touch, The Rot, Tyrannor: pure deck-thinning scrap
				var max_cards: int = 2 if s_lower.contains("up to two") else 1
				effects.append({"id": "sacrifice_scrap", "starters_only": true, "max_cards": max_cards})
		else:
			# Self-sacrifice: the source card itself is sacrificed for a bonus
			var sacrifice_combat: int = _extract_first_number(sacrifice_text, "combat")
			if sacrifice_combat > 0:
				effects.append({"id": "sacrifice_combat_offer", "value": sacrifice_combat})
			if s_lower.contains("target opponent discards a card"):
				effects.append({"id": "sacrifice_force_discard", "value": 1})

	# Champion metadata.
	if card_type.to_lower().contains("champion"):
		var defense: int = 3
		var guard: bool = false
		if not defense_field.is_empty():
			defense = _extract_first_number(defense_field, "")
			guard = defense_field.to_lower().contains("guard")
		effects.append({
			"id": "champion_data",
			"defense": defense,
			"guard": guard,
			"combat": _extract_first_number(base_no_ally_sac, "combat"),
			"gold": _extract_first_number(base_no_ally_sac, "gold"),
			"health": _extract_first_number(base_no_ally_sac, "health")
		})

	return _dedupe_effects(effects)


func _append_numeric_gain_effects(effects: Array[Dictionary], text: String) -> void:
	var combat: int = _extract_first_number(text, "combat")
	var gold: int = _extract_first_number(text, "gold")
	var health: int = _extract_first_number(text, "health")
	if combat > 0:
		effects.append({"id": "gain_combat", "value": combat})
	if gold > 0:
		effects.append({"id": "gain_gold", "value": gold})
	if health > 0:
		effects.append({"id": "gain_health", "value": health})


func _dedupe_effects(effects: Array[Dictionary]) -> Array[Dictionary]:
	var unique: Array[Dictionary] = []
	var seen: Dictionary = {}
	for effect: Dictionary in effects:
		var key: String = JSON.stringify(effect)
		if seen.has(key):
			continue
		seen[key] = true
		unique.append(effect)
	return unique
