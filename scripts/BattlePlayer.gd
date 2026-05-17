extends Node
class_name BattlePlayer

signal state_changed
signal choice_requested(choice: Dictionary)
signal choice_cleared

var player_name: String = "Player"
var max_hp: int = 50
var current_hp: int = 50
var max_energy: int = 0
var current_energy: int = 0
var current_block: int = 0
var gold_pool: int = 0
var combat_pool: int = 0
var statuses: Dictionary = {}

var deck: Deck = Deck.new()
var hand: Array[Card] = []
var champions_in_play: Array[Dictionary] = []
var faction_counts_this_turn: Dictionary = {}
var pending_sacrifice_offers: Array[Dictionary] = []
var pending_sacrifice_combat: int = 0
var pending_sacrifice_force_discard: int = 0
var pending_sacrifice_source_card: Card = null
var pending_sacrifice_requires_external_card: bool = false
var pending_sacrifice_target: Node = null
var pending_acquire_to_topdeck_actions: int = 0
var pending_acquire_to_topdeck_any: int = 0
var pending_acquire_to_hand_any: int = 0
var played_cards_this_turn: Array[String] = []
var played_cards_this_turn_refs: Array[Card] = []
var ally_bonus_triggered_this_turn: Dictionary = {}
var pending_ally_activations: Array[Dictionary] = []
var interaction_mode: String = "auto"
var pending_choice: Dictionary = {}


func setup_from_ids(new_name: String, hp: int, energy: int, deck_ids: Array[String]) -> void:
	player_name = new_name
	max_hp = hp
	current_hp = hp
	max_energy = energy
	current_energy = energy
	current_block = 0
	gold_pool = 0
	combat_pool = 0
	statuses.clear()
	hand.clear()
	champions_in_play.clear()
	faction_counts_this_turn.clear()
	pending_sacrifice_offers.clear()
	pending_sacrifice_combat = 0
	pending_sacrifice_force_discard = 0
	pending_sacrifice_source_card = null
	pending_sacrifice_requires_external_card = false
	pending_sacrifice_target = null
	pending_acquire_to_topdeck_actions = 0
	pending_acquire_to_topdeck_any = 0
	pending_acquire_to_hand_any = 0
	played_cards_this_turn.clear()
	played_cards_this_turn_refs.clear()
	ally_bonus_triggered_this_turn.clear()
	pending_ally_activations.clear()
	pending_choice.clear()

	var cards: Array[Card] = GameState.create_cards_from_ids(deck_ids)
	deck.setup(cards)
	state_changed.emit()


func start_turn(cards_to_draw: int) -> void:
	current_block = 0
	gold_pool = 0
	combat_pool = 0
	faction_counts_this_turn.clear()
	pending_sacrifice_offers.clear()
	pending_sacrifice_combat = 0
	pending_sacrifice_force_discard = 0
	pending_sacrifice_source_card = null
	pending_sacrifice_requires_external_card = false
	pending_sacrifice_target = null
	pending_acquire_to_topdeck_actions = 0
	pending_acquire_to_topdeck_any = 0
	pending_acquire_to_hand_any = 0
	played_cards_this_turn.clear()
	played_cards_this_turn_refs.clear()
	ally_bonus_triggered_this_turn.clear()
	pending_ally_activations.clear()
	pending_choice.clear()
	draw_cards(cards_to_draw)
	_prepare_all_champions()
	state_changed.emit()


func end_turn() -> void:
	gold_pool = 0
	combat_pool = 0
	pending_sacrifice_offers.clear()
	pending_sacrifice_combat = 0
	pending_sacrifice_force_discard = 0
	pending_sacrifice_source_card = null
	pending_sacrifice_requires_external_card = false
	pending_sacrifice_target = null
	pending_acquire_to_topdeck_actions = 0
	pending_acquire_to_topdeck_any = 0
	pending_acquire_to_hand_any = 0
	played_cards_this_turn_refs.clear()
	ally_bonus_triggered_this_turn.clear()
	pending_ally_activations.clear()
	pending_choice.clear()
	deck.discard_cards(hand)
	hand.clear()
	state_changed.emit()


func draw_cards(amount: int) -> void:
	for _index in range(amount):
		var drawn_card: Card = deck.draw_card()
		if drawn_card != null:
			hand.append(drawn_card)


func force_discard_weakest(amount: int) -> int:
	if amount <= 0:
		return 0

	var discarded: int = 0
	for _i in range(amount):
		if hand.is_empty():
			break

		var weakest_index: int = _find_weakest_hand_index()
		if weakest_index < 0 or weakest_index >= hand.size():
			weakest_index = 0

		var removed: Card = hand[weakest_index]
		hand.remove_at(weakest_index)
		deck.discard_card(removed)
		discarded += 1

	if discarded > 0:
		state_changed.emit()

	return discarded


func can_play_card(card: Card) -> bool:
	if card == null:
		return false
	if has_pending_choice():
		return false
	return true


func play_card(card: Card, target: Node) -> bool:
	if not can_play_card(card):
		return false

	var faction: String = _get_card_faction(card)
	if not faction.is_empty():
		faction_counts_this_turn[faction] = int(faction_counts_this_turn.get(faction, 0)) + 1

	played_cards_this_turn.append(card.card_name)
	played_cards_this_turn_refs.append(card)

	var is_champion: bool = _is_champion_card(card)
	var hand_index: int = hand.find(card)
	if hand_index != -1:
		hand.remove_at(hand_index)

	if is_champion:
		_add_champion(card)
	else:
		_apply_card_effects(card, target)

	if not faction.is_empty():
		_trigger_ally_bonuses_for_faction(faction, target)

	if not is_champion:
		deck.discard_card(card)
	state_changed.emit()
	return true


func set_interaction_mode(mode: String) -> void:
	interaction_mode = mode


func has_pending_choice() -> bool:
	return not pending_choice.is_empty()


func begin_sacrifice_choice(sacrifice_pile: Array[Card]) -> bool:
	_ensure_legacy_sacrifice_offer_promoted()
	if not has_pending_sacrifice_offer():
		return false

	if interaction_mode == "manual" and pending_sacrifice_offers.size() > 1:
		var options: Array[Dictionary] = []
		for index: int in range(pending_sacrifice_offers.size()):
			var offer: Dictionary = pending_sacrifice_offers[index]
			options.append({
				"label": _build_sacrifice_offer_label(offer),
				"offer_index": index
			})
		pending_choice = {
			"type": "sacrifice_ability",
			"title": "Choose A Sacrifice Ability",
			"message": "Select which sacrifice ability to use.",
			"options": options,
			"sacrifice_pile": sacrifice_pile
		}
		choice_requested.emit(pending_choice.duplicate(true))
		return true

	if interaction_mode != "manual":
		return use_sacrifice_offer(sacrifice_pile)
	return _begin_specific_sacrifice_offer(0, sacrifice_pile)


func resolve_pending_choice(option_index: int) -> bool:
	if option_index < 0 or pending_choice.is_empty():
		return false

	var options: Array = pending_choice.get("options", [])
	if option_index >= options.size():
		return false

	var option: Dictionary = options[option_index]
	var choice_type: String = String(pending_choice.get("type", ""))
	match choice_type:
		"discard_from_hand":
			return _resolve_discard_choice(option)
		"sacrifice_ability":
			return _resolve_sacrifice_ability_choice(option)
		"ally_activation":
			return _resolve_ally_activation_choice(option)
		"sacrifice_offer":
			return _resolve_sacrifice_choice(option)
		"choice_gain_combat_or_health":
			if String(option.get("id", "")) == "combat":
				gain_combat(int(option.get("value", 0)))
			else:
				gain_health(int(option.get("value", 0)))
			_clear_pending_choice()
			return true
		"choice_gain_gold_or_combat":
			if String(option.get("id", "")) == "gold":
				gain_gold(int(option.get("value", 0)))
			else:
				gain_combat(int(option.get("value", 0)))
			_clear_pending_choice()
			return true
		"choice_gain_gold_or_health_per_champion":
			if String(option.get("id", "")) == "gold":
				gain_gold(int(option.get("value", 0)))
			else:
				gain_health(champions_in_play.size() * int(option.get("value", 0)))
			_clear_pending_choice()
			return true
		"prepare_champion":
			var champion_index: int = int(option.get("index", -1))
			if champion_index >= 0 and champion_index < champions_in_play.size():
				var champion: Dictionary = champions_in_play[champion_index]
				champion["prepared"] = true
				champions_in_play[champion_index] = champion
			_clear_pending_choice()
			state_changed.emit()
			return true
		"stun_target_champion":
			var target_player: BattlePlayer = pending_choice.get("target_player", null)
			var stun_index: int = int(option.get("index", -1))
			if target_player != null:
				target_player.stun_champion_at(stun_index)
			_clear_pending_choice()
			return true
		"recover_discard_to_topdeck":
			var discard_index: int = int(option.get("index", -1))
			if discard_index >= 0 and discard_index < deck.discard_pile.size():
				var card: Card = deck.discard_pile[discard_index]
				deck.discard_pile.remove_at(discard_index)
				deck.draw_pile.append(card)
			_clear_pending_choice()
			state_changed.emit()
			return true
	return false


func get_champion_summaries() -> Array[Dictionary]:
	var summaries: Array[Dictionary] = []
	for index: int in range(champions_in_play.size()):
		var champion: Dictionary = champions_in_play[index]
		var champion_card: Card = champion.get("card", null)
		var image_path: String = ""
		if champion_card != null:
			image_path = champion_card.image_path
		summaries.append({
			"index": index,
			"name": String(champion.get("name", "Champion")),
			"defense": int(champion.get("defense", 0)),
			"is_guard": bool(champion.get("is_guard", false)),
			"prepared": bool(champion.get("prepared", false)),
			"combat": int(champion.get("combat", 0)),
			"gold": int(champion.get("gold", 0)),
			"health": int(champion.get("health", 0)),
			"image_path": image_path
		})
	return summaries


func expend_champion(index: int, target: Node = null) -> bool:
	if index < 0 or index >= champions_in_play.size():
		return false

	var champion: Dictionary = champions_in_play[index]
	if not bool(champion.get("prepared", false)):
		return false

	champion["prepared"] = false
	champions_in_play[index] = champion
	var card: Card = champion.get("card", null)
	var used_card_effects: bool = false
	if card is DataCard:
		var data_card: DataCard = card as DataCard
		for effect: Dictionary in data_card.effects:
			var effect_id: String = String(effect.get("id", ""))
			if effect_id in ["set_faction", "ally_bonus", "champion_data"]:
				continue
			used_card_effects = true
			_apply_effect_entry(effect, null, card)

	if not used_card_effects:
		gain_combat(int(champion.get("combat", 0)))
		gain_gold(int(champion.get("gold", 0)))
		gain_health(int(champion.get("health", 0)))

	var faction: String = _get_card_faction(card)
	if not faction.is_empty():
		_trigger_ally_bonuses_for_faction(faction, target)
	state_changed.emit()
	return true


func auto_expend_all_champions(target: Node = null) -> void:
	for index: int in range(champions_in_play.size()):
		var champion: Dictionary = champions_in_play[index]
		if not bool(champion.get("prepared", false)):
			continue
		expend_champion(index, target)


func has_pending_sacrifice_offer() -> bool:
	_ensure_legacy_sacrifice_offer_promoted()
	return not pending_sacrifice_offers.is_empty()


func get_pending_sacrifice_label() -> String:
	_ensure_legacy_sacrifice_offer_promoted()
	if not has_pending_sacrifice_offer():
		return "Use Sacrifice Ability"
	if pending_sacrifice_offers.size() > 1:
		return "Choose Sacrifice Ability (%d)" % pending_sacrifice_offers.size()
	return _build_sacrifice_offer_label(pending_sacrifice_offers[0])


func use_sacrifice_offer(sacrifice_pile: Array[Card]) -> bool:
	_ensure_legacy_sacrifice_offer_promoted()
	if not has_pending_sacrifice_offer():
		return false
	return _use_specific_sacrifice_offer(0, sacrifice_pile)


func force_discard_random(amount: int) -> int:
	if amount <= 0:
		return 0

	var discarded: int = 0
	for _i in range(amount):
		if hand.is_empty():
			break

		var random_index: int = randi_range(0, hand.size() - 1)
		var removed: Card = hand[random_index]
		hand.remove_at(random_index)
		deck.discard_card(removed)
		discarded += 1

	if discarded > 0:
		state_changed.emit()

	return discarded


func receive_damage(amount: int) -> void:
	if amount <= 0:
		return

	var damage_after_block: int = max(amount - current_block, 0)
	current_block = max(current_block - amount, 0)
	current_hp = max(current_hp - damage_after_block, 0)
	state_changed.emit()


func gain_block(amount: int) -> void:
	if amount <= 0:
		return

	current_block += amount
	state_changed.emit()


func gain_health(amount: int) -> void:
	if amount <= 0:
		return

	current_hp = min(current_hp + amount, max_hp)
	state_changed.emit()


func gain_gold(amount: int) -> void:
	if amount <= 0:
		return

	gold_pool += amount
	state_changed.emit()


func gain_combat(amount: int) -> void:
	if amount <= 0:
		return

	combat_pool += amount
	state_changed.emit()


func spend_combat(amount: int) -> bool:
	if amount <= 0:
		return true
	if amount > combat_pool:
		return false

	combat_pool -= amount
	state_changed.emit()
	return true


func spend_gold(amount: int) -> bool:
	if amount <= 0:
		return true
	if amount > gold_pool:
		return false

	gold_pool -= amount
	state_changed.emit()
	return true


func apply_status(status_name: String, stacks: int) -> void:
	if status_name.is_empty() or stacks <= 0:
		return

	statuses[status_name] = int(statuses.get(status_name, 0)) + stacks
	state_changed.emit()


func is_defeated() -> bool:
	return current_hp <= 0


func has_guard_champions() -> bool:
	for champion: Dictionary in champions_in_play:
		if bool(champion.get("is_guard", false)):
			return true
	return false


func resolve_combat_against(opponent: BattlePlayer) -> int:
	if opponent == null:
		combat_pool = 0
		return 0

	var remaining: int = combat_pool

	while remaining > 0 and opponent.has_guard_champions():
		var guard_index: int = opponent._first_guard_index()
		if guard_index == -1:
			break

		var guard_defense: int = int(opponent.champions_in_play[guard_index].get("defense", 1))
		if remaining >= guard_defense:
			remaining -= guard_defense
			opponent.stun_champion_at(guard_index)
		else:
			remaining = 0

	if remaining > 0:
		opponent.receive_damage(remaining)

	var dealt_to_player: int = remaining
	combat_pool = 0
	state_changed.emit()
	return dealt_to_player


func stun_champion_at(index: int) -> void:
	if index < 0 or index >= champions_in_play.size():
		return

	var champion_card: Card = champions_in_play[index].get("card", null)
	if champion_card != null:
		deck.discard_card(champion_card)

	champions_in_play.remove_at(index)
	state_changed.emit()


func get_mana() -> int:
	return current_energy


func get_max_mana() -> int:
	return max_energy


func get_health() -> int:
	return current_hp


func get_block() -> int:
	return current_block


func get_gold_pool() -> int:
	return gold_pool


func get_combat_pool() -> int:
	return combat_pool


func prepare_first_champion() -> bool:
	for index: int in range(champions_in_play.size()):
		var champion: Dictionary = champions_in_play[index]
		if bool(champion.get("prepared", false)):
			continue
		champion["prepared"] = true
		champions_in_play[index] = champion
		state_changed.emit()
		return true
	return false


func set_next_acquire_to_topdeck_actions(count: int) -> void:
	if count <= 0:
		return
	pending_acquire_to_topdeck_actions += count


func set_next_acquire_to_topdeck_any(count: int) -> void:
	if count <= 0:
		return
	pending_acquire_to_topdeck_any += count


func set_next_acquire_to_hand_any(count: int) -> void:
	if count <= 0:
		return
	pending_acquire_to_hand_any += count


func receive_acquired_card(card: Card) -> void:
	if card == null:
		return

	if pending_acquire_to_hand_any > 0:
		hand.append(card)
		pending_acquire_to_hand_any -= 1
		state_changed.emit()
		return

	var is_action: bool = not _is_champion_card(card)
	if pending_acquire_to_topdeck_any > 0:
		deck.draw_pile.append(card)
		pending_acquire_to_topdeck_any -= 1
		state_changed.emit()
		return

	if pending_acquire_to_topdeck_actions > 0 and is_action:
		deck.draw_pile.append(card)
		pending_acquire_to_topdeck_actions -= 1
		state_changed.emit()
		return

	deck.discard_card(card)
	state_changed.emit()


func _apply_card_effects(card: Card, target: Node) -> void:
	if card is DataCard:
		var data_card: DataCard = card as DataCard
		for effect: Dictionary in data_card.effects:
			_apply_effect_entry(effect, target, card)
	else:
		# Fallback for custom card subclasses.
		card.play(target)


func _apply_effect_entry(effect: Dictionary, target: Node, source_card: Card = null) -> void:
	var effect_id: String = String(effect.get("id", ""))
	var value: int = int(effect.get("value", 0))
	match effect_id:
		"gain_combat":
			gain_combat(value)
		"deal_damage":
			gain_combat(value)
		"gain_block":
			CardEffect.gain_block(self, value)
		"apply_status":
			CardEffect.apply_status(target, String(effect.get("status", "")), value)
		"gain_gold":
			gain_gold(value)
		"gain_health":
			gain_health(value)
		"draw_cards":
			draw_cards(value)
		"draw_then_discard":
			var draw_count: int = int(effect.get("draw", value))
			var discard_count: int = int(effect.get("discard", draw_count))
			draw_cards(draw_count)
			_request_or_auto_discard_from_hand(discard_count, "Choose a card to discard.")
		"draw_up_to_then_discard":
			var max_draw: int = int(effect.get("max_draw", value))
			draw_cards(max_draw)
			_request_or_auto_discard_from_hand(max_draw, "Choose cards to discard after drawing.")
		"sacrifice_combat_offer":
			_queue_sacrifice_offer(source_card, false, target, value, 0)
		"sacrifice_for_additional_combat":
			_queue_sacrifice_offer(source_card, true, target, value, 0, bool(effect.get("starters_only", false)))
		"sacrifice_force_discard":
			_queue_sacrifice_offer(source_card, false, target, 0, value)
		"sacrifice_scrap":
			_queue_sacrifice_offer(source_card, true, target, 0, 0, bool(effect.get("starters_only", false)))
		"force_discard":
			if target != null and target.has_method("force_discard_random"):
				target.call("force_discard_random", value)
		"stun_target_champion":
			_request_or_auto_stun_target(target)
		"prepare_champion":
			_request_or_auto_prepare_champion()
		"next_acquire_to_topdeck_action":
			set_next_acquire_to_topdeck_actions(max(value, 1))
		"next_acquire_to_topdeck_any":
			set_next_acquire_to_topdeck_any(max(value, 1))
		"next_acquire_to_hand_any":
			set_next_acquire_to_hand_any(max(value, 1))
		"recover_discard_to_topdeck":
			_request_or_auto_recover_discard_to_topdeck(bool(effect.get("champion_only", false)))
		"for_each_other_guard_gain_combat":
			gain_combat(_count_other_guards(source_card) * value)
		"for_each_other_champion_gain_combat":
			gain_combat(_count_other_champions(source_card) * value)
		"for_each_other_wild_gain_combat":
			gain_combat(_count_other_faction_cards_in_play(source_card, "wild") * value)
		"for_each_champion_gain_combat":
			gain_combat(champions_in_play.size() * value)
		"for_each_champion_gain_health":
			gain_health(champions_in_play.size() * value)
		"choice_gain_combat_or_health":
			_request_or_auto_choice_gain_combat_or_health(value, int(effect.get("health", 0)))
		"choice_gain_gold_or_combat":
			_request_or_auto_choice_gain_gold_or_combat(int(effect.get("gold", 0)), int(effect.get("combat", 0)))
		"choice_gain_gold_or_health_per_champion":
			_request_or_auto_choice_gain_gold_or_health_per_champion(int(effect.get("gold", 0)), int(effect.get("health_per_champion", 0)))
		"set_faction", "ally_bonus", "champion_data":
			pass
		_:
			push_warning("Unknown card effect id: %s" % effect_id)


func _is_champion_card(card: Card) -> bool:
	if card == null:
		return false

	if card.card_type.to_lower().contains("champion"):
		return true

	if card is DataCard:
		var data_card: DataCard = card as DataCard
		for effect: Dictionary in data_card.effects:
			if String(effect.get("id", "")) == "champion_data":
				return true

	return false


func _add_champion(card: Card) -> void:
	var champion_data: Dictionary = {
		"card": card,
		"name": card.card_name,
		"defense": 3,
		"is_guard": false,
		"prepared": true,
		"combat": 0,
		"gold": 0,
		"health": 0
	}

	if card is DataCard:
		var data_card: DataCard = card as DataCard
		for effect: Dictionary in data_card.effects:
			var effect_id: String = String(effect.get("id", ""))
			if effect_id == "champion_data":
				champion_data["defense"] = int(effect.get("defense", 3))
				champion_data["is_guard"] = bool(effect.get("guard", false))
				champion_data["combat"] = int(effect.get("combat", 0))
				champion_data["gold"] = int(effect.get("gold", 0))
				champion_data["health"] = int(effect.get("health", 0))

	champions_in_play.append(champion_data)


func _prepare_all_champions() -> void:
	for index: int in range(champions_in_play.size()):
		var champion: Dictionary = champions_in_play[index]
		champion["prepared"] = true
		champions_in_play[index] = champion


func _first_guard_index() -> int:
	for index: int in range(champions_in_play.size()):
		if bool(champions_in_play[index].get("is_guard", false)):
			return index
	return -1


func _get_card_faction(card: Card) -> String:
	if card == null:
		return ""
	if not (card is DataCard):
		return ""

	var data_card: DataCard = card as DataCard
	for effect: Dictionary in data_card.effects:
		if String(effect.get("id", "")) == "set_faction":
			return String(effect.get("faction", "")).to_lower()

	return ""


func _trigger_ally_bonuses_for_faction(faction: String, target: Node = null) -> void:
	if faction.is_empty():
		return

	var faction_card_count: int = 0
	var seen_faction_cards: Dictionary = {}
	for candidate: Card in played_cards_this_turn_refs:
		if candidate == null:
			continue
		if _get_card_faction(candidate) != faction:
			continue
		var key: String = str(candidate.get_instance_id())
		if seen_faction_cards.has(key):
			continue
		seen_faction_cards[key] = true
		faction_card_count += 1
	for champion_entry: Dictionary in champions_in_play:
		var champion_card: Card = champion_entry.get("card", null)
		if champion_card == null:
			continue
		if _get_card_faction(champion_card) != faction:
			continue
		var champion_key: String = str(champion_card.get_instance_id())
		if seen_faction_cards.has(champion_key):
			continue
		seen_faction_cards[champion_key] = true
		faction_card_count += 1

	if faction_card_count < 2:
		return

	var ally_candidates: Array[Card] = []
	for candidate: Card in played_cards_this_turn_refs:
		if candidate == null:
			continue
		var candidate_key: String = str(candidate.get_instance_id())
		if seen_faction_cards.has(candidate_key):
			ally_candidates.append(candidate)
	for champion_entry: Dictionary in champions_in_play:
		var champion_card: Card = champion_entry.get("card", null)
		if champion_card == null:
			continue
		var champion_key: String = str(champion_card.get_instance_id())
		if seen_faction_cards.has(champion_key) and not ally_candidates.has(champion_card):
			ally_candidates.append(champion_card)

	for candidate: Card in ally_candidates:
		if candidate == null:
			continue
		if not _card_has_ally_bonus(candidate):
			continue

		var trigger_key: String = str(candidate.get_instance_id())
		if ally_bonus_triggered_this_turn.has(trigger_key):
			continue

		if interaction_mode == "manual":
			var already_pending: bool = false
			for entry: Dictionary in pending_ally_activations:
				if String(entry.get("trigger_key", "")) == trigger_key:
					already_pending = true
					break
			if not already_pending:
				pending_ally_activations.append({
					"trigger_key": trigger_key,
					"card_name": candidate.card_name,
					"faction": faction,
					"description": _build_ally_activation_description(candidate),
					"card": candidate,
					"target": target
				})
		else:
			_apply_ally_bonus_from_card(candidate, target)
			ally_bonus_triggered_this_turn[trigger_key] = true


func _apply_ally_bonus_from_card(card: Card, target: Node = null) -> void:
	if card == null or not (card is DataCard):
		return

	var data_card: DataCard = card as DataCard
	for effect: Dictionary in data_card.effects:
		if String(effect.get("id", "")) != "ally_bonus":
			continue

		gain_combat(int(effect.get("combat", 0)))
		gain_gold(int(effect.get("gold", 0)))
		gain_health(int(effect.get("health", 0)))
		if int(effect.get("draw_cards", 0)) > 0:
			draw_cards(int(effect.get("draw_cards", 0)))
		if int(effect.get("draw_then_discard", 0)) > 0:
			draw_cards(int(effect.get("draw_then_discard", 0)))
			_request_or_auto_discard_from_hand(int(effect.get("draw_then_discard", 0)), "Choose a card to discard.")
		if int(effect.get("prepare_champion", 0)) > 0:
			_request_or_auto_prepare_champion()
		if int(effect.get("stun_target_champion", 0)) > 0:
			_request_or_auto_stun_target(target)
		if int(effect.get("force_discard", 0)) > 0:
			if target != null and target.has_method("force_discard_random"):
				target.call("force_discard_random", int(effect.get("force_discard", 0)))
		if int(effect.get("next_acquire_to_topdeck_action", 0)) > 0:
			set_next_acquire_to_topdeck_actions(int(effect.get("next_acquire_to_topdeck_action", 0)))
		if int(effect.get("next_acquire_to_topdeck_any", 0)) > 0:
			set_next_acquire_to_topdeck_any(int(effect.get("next_acquire_to_topdeck_any", 0)))
		if int(effect.get("next_acquire_to_hand_any", 0)) > 0:
			set_next_acquire_to_hand_any(int(effect.get("next_acquire_to_hand_any", 0)))


func _card_has_ally_bonus(card: Card) -> bool:
	if card == null or not (card is DataCard):
		return false
	var data_card: DataCard = card as DataCard
	for effect: Dictionary in data_card.effects:
		if String(effect.get("id", "")) == "ally_bonus":
			return true
	return false


func _build_ally_activation_description(card: Card) -> String:
	if card == null or not (card is DataCard):
		return "Ally Bonus"
	var data_card: DataCard = card as DataCard
	var parts: Array[String] = []
	for effect: Dictionary in data_card.effects:
		if String(effect.get("id", "")) != "ally_bonus":
			continue
		var combat: int = int(effect.get("combat", 0))
		var gold: int = int(effect.get("gold", 0))
		var health: int = int(effect.get("health", 0))
		if combat > 0:
			parts.append("+%d Combat" % combat)
		if gold > 0:
			parts.append("+%d Gold" % gold)
		if health > 0:
			parts.append("+%d Health" % health)
		if int(effect.get("draw_cards", 0)) > 0:
			parts.append("Draw a Card")
		if int(effect.get("draw_then_discard", 0)) > 0:
			parts.append("Draw then Discard")
		if int(effect.get("prepare_champion", 0)) > 0:
			parts.append("Prepare Champion")
		if int(effect.get("stun_target_champion", 0)) > 0:
			parts.append("Stun Champion")
		if int(effect.get("force_discard", 0)) > 0:
			parts.append("Opponent Discards")
		if int(effect.get("next_acquire_to_topdeck_action", 0)) > 0:
			parts.append("Acquire Action To Top Deck")
		if int(effect.get("next_acquire_to_topdeck_any", 0)) > 0:
			parts.append("Acquire Card To Top Deck")
		if int(effect.get("next_acquire_to_hand_any", 0)) > 0:
			parts.append("Acquire Card To Hand")
	if parts.is_empty():
		return "Ally Bonus"
	return " / ".join(parts)


func get_pending_ally_activations() -> Array[Dictionary]:
	var result: Array[Dictionary] = []
	for entry: Dictionary in pending_ally_activations:
		result.append(entry.duplicate(false))
	return result


func activate_ally_bonus(trigger_key: String) -> bool:
	for i in range(pending_ally_activations.size()):
		var entry: Dictionary = pending_ally_activations[i]
		if String(entry.get("trigger_key", "")) != trigger_key:
			continue
		var card: Card = entry.get("card", null)
		var target: Node = entry.get("target", null)
		_apply_ally_bonus_from_card(card, target)
		ally_bonus_triggered_this_turn[trigger_key] = true
		pending_ally_activations.remove_at(i)
		state_changed.emit()
		return true
	return false


func begin_ally_activation_choice() -> bool:
	if pending_ally_activations.is_empty():
		return false
	if interaction_mode != "manual":
		var keys: Array[String] = []
		for entry: Dictionary in pending_ally_activations:
			keys.append(String(entry.get("trigger_key", "")))
		for key: String in keys:
			activate_ally_bonus(key)
		return true
	var options: Array[Dictionary] = []
	for entry: Dictionary in pending_ally_activations:
		options.append({
			"label": "%s: %s" % [String(entry.get("card_name", "")), String(entry.get("description", "Ally Bonus"))],
			"trigger_key": String(entry.get("trigger_key", ""))
		})
	pending_choice = {
		"type": "ally_activation",
		"title": "Choose A Card Ability",
		"message": "Select which ally ability to activate.",
		"options": options
	}
	choice_requested.emit(pending_choice.duplicate(true))
	return true


func stun_first_champion() -> bool:
	if champions_in_play.is_empty():
		return false
	stun_champion_at(0)
	return true


func _recover_discard_to_topdeck(champion_only: bool) -> bool:
	if deck.discard_pile.is_empty():
		return false

	for i in range(deck.discard_pile.size() - 1, -1, -1):
		var candidate: Card = deck.discard_pile[i]
		if candidate == null:
			continue
		if champion_only and not _is_champion_card(candidate):
			continue

		deck.discard_pile.remove_at(i)
		deck.draw_pile.append(candidate)
		state_changed.emit()
		return true

	return false


func _request_or_auto_discard_from_hand(amount: int, message: String) -> void:
	if amount <= 0:
		return
	if interaction_mode != "manual":
		force_discard_weakest(amount)
		return
	_request_discard_choice(max(amount, 1), message)


func _request_discard_choice(remaining: int, message: String) -> void:
	if hand.is_empty():
		return
	var options: Array[Dictionary] = []
	for i in range(hand.size()):
		var card: Card = hand[i]
		options.append({"label": card.card_name, "index": i})
	pending_choice = {
		"type": "discard_from_hand",
		"title": "Choose A Card To Discard",
		"message": message,
		"remaining": remaining,
		"options": options
	}
	choice_requested.emit(pending_choice.duplicate(true))


func _resolve_discard_choice(option: Dictionary) -> bool:
	var discard_index: int = int(option.get("index", -1))
	if discard_index < 0 or discard_index >= hand.size():
		return false
	var removed: Card = hand[discard_index]
	hand.remove_at(discard_index)
	deck.discard_card(removed)
	var remaining: int = int(pending_choice.get("remaining", 1)) - 1
	if remaining > 0 and not hand.is_empty():
		_request_discard_choice(remaining, String(pending_choice.get("message", "Choose a card to discard.")))
	else:
		_clear_pending_choice()
	state_changed.emit()
	return true


func _request_or_auto_choice_gain_combat_or_health(combat: int, health: int) -> void:
	if interaction_mode != "manual":
		gain_combat(combat)
		return
	pending_choice = {
		"type": "choice_gain_combat_or_health",
		"title": "Choose An Ability",
		"message": "Pick which effect to use.",
		"options": [
			{"label": "+%d Combat" % combat, "id": "combat", "value": combat},
			{"label": "+%d Health" % health, "id": "health", "value": health}
		]
	}
	choice_requested.emit(pending_choice.duplicate(true))


func _request_or_auto_choice_gain_gold_or_combat(gold: int, combat: int) -> void:
	if interaction_mode != "manual":
		gain_gold(gold)
		return
	pending_choice = {
		"type": "choice_gain_gold_or_combat",
		"title": "Choose An Ability",
		"message": "Pick which effect to use.",
		"options": [
			{"label": "+%d Gold" % gold, "id": "gold", "value": gold},
			{"label": "+%d Combat" % combat, "id": "combat", "value": combat}
		]
	}
	choice_requested.emit(pending_choice.duplicate(true))


func _request_or_auto_choice_gain_gold_or_health_per_champion(gold: int, health_per_champion: int) -> void:
	if interaction_mode != "manual":
		gain_gold(gold)
		return
	pending_choice = {
		"type": "choice_gain_gold_or_health_per_champion",
		"title": "Choose An Ability",
		"message": "Pick which effect to use.",
		"options": [
			{"label": "+%d Gold" % gold, "id": "gold", "value": gold},
			{"label": "+%d Health Per Champion" % health_per_champion, "id": "health", "value": health_per_champion}
		]
	}
	choice_requested.emit(pending_choice.duplicate(true))


func _request_or_auto_prepare_champion() -> void:
	var exhausted: Array[Dictionary] = []
	for i in range(champions_in_play.size()):
		var champion: Dictionary = champions_in_play[i]
		if not bool(champion.get("prepared", false)):
			exhausted.append({"label": String(champion.get("name", "Champion")), "index": i})
	if exhausted.is_empty():
		return
	if interaction_mode != "manual":
		var first_index: int = int(exhausted[0].get("index", -1))
		if first_index >= 0:
			var chosen: Dictionary = champions_in_play[first_index]
			chosen["prepared"] = true
			champions_in_play[first_index] = chosen
			state_changed.emit()
		return
	pending_choice = {
		"type": "prepare_champion",
		"title": "Choose A Champion To Prepare",
		"message": "Select a spent champion to ready.",
		"options": exhausted
	}
	choice_requested.emit(pending_choice.duplicate(true))


func _request_or_auto_stun_target(target: Node) -> void:
	if target == null or not (target is BattlePlayer):
		return
	var target_player: BattlePlayer = target as BattlePlayer
	var options: Array[Dictionary] = []
	for i in range(target_player.champions_in_play.size()):
		var champion: Dictionary = target_player.champions_in_play[i]
		options.append({"label": String(champion.get("name", "Champion")), "index": i})
	if options.is_empty():
		return
	if interaction_mode != "manual" or options.size() == 1:
		target_player.stun_champion_at(int(options[0].get("index", 0)))
		return
	pending_choice = {
		"type": "stun_target_champion",
		"title": "Choose A Champion To Stun",
		"message": "Select an enemy champion.",
		"target_player": target_player,
		"options": options
	}
	choice_requested.emit(pending_choice.duplicate(true))


func _request_or_auto_recover_discard_to_topdeck(champion_only: bool) -> void:
	var options: Array[Dictionary] = []
	for i in range(deck.discard_pile.size()):
		var candidate: Card = deck.discard_pile[i]
		if candidate == null:
			continue
		if champion_only and not _is_champion_card(candidate):
			continue
		options.append({"label": candidate.card_name, "index": i})
	if options.is_empty():
		return
	if interaction_mode != "manual" or options.size() == 1:
		var index: int = int(options[0].get("index", -1))
		if index >= 0 and index < deck.discard_pile.size():
			var card: Card = deck.discard_pile[index]
			deck.discard_pile.remove_at(index)
			deck.draw_pile.append(card)
			state_changed.emit()
		return
	pending_choice = {
		"type": "recover_discard_to_topdeck",
		"title": "Choose A Card To Recover",
		"message": "Pick a discard card to place on top of your deck.",
		"options": options
	}
	choice_requested.emit(pending_choice.duplicate(true))


func _resolve_sacrifice_ability_choice(option: Dictionary) -> bool:
	var offer_index: int = int(option.get("offer_index", -1))
	var sacrifice_pile: Array[Card] = pending_choice.get("sacrifice_pile", [])
	return _begin_specific_sacrifice_offer(offer_index, sacrifice_pile)


func _resolve_ally_activation_choice(option: Dictionary) -> bool:
	var trigger_key: String = String(option.get("trigger_key", ""))
	# Clear the ally_activation choice silently before the bonus potentially creates a sub-choice
	pending_choice.clear()
	activate_ally_bonus(trigger_key)
	if not has_pending_choice():
		choice_cleared.emit()
	# If a sub-choice was created (e.g. discard_from_hand), choice_requested was already emitted
	return true


func _resolve_sacrifice_choice(option: Dictionary) -> bool:
	var offer_index: int = int(pending_choice.get("offer_index", -1))
	if offer_index < 0 or offer_index >= pending_sacrifice_offers.size():
		return false
	var source: String = String(option.get("source", ""))
	var index: int = int(option.get("index", -1))
	var offer: Dictionary = pending_sacrifice_offers[offer_index]
	var source_card: Card = offer.get("source_card", null)
	var sacrificed: Card = null
	if source == "hand":
		if index < 0 or index >= hand.size():
			return false
		sacrificed = hand[index]
		if sacrificed == source_card:
			return false
		hand.remove_at(index)
	elif source == "discard":
		if index < 0 or index >= deck.discard_pile.size():
			return false
		sacrificed = deck.discard_pile[index]
		if sacrificed == source_card:
			return false
		deck.discard_pile.remove_at(index)
	if sacrificed == null:
		return false
	var sacrifice_pile: Array[Card] = pending_choice.get("sacrifice_pile", [])
	sacrifice_pile.append(sacrificed)
	_apply_sacrifice_offer_bonus(offer)
	_clear_pending_sacrifice_offer(offer_index)
	_clear_pending_choice()
	state_changed.emit()
	return true


func _clear_pending_choice() -> void:
	pending_choice.clear()
	choice_cleared.emit()


func _clear_pending_sacrifice_offer(index: int = -1) -> void:
	if index >= 0 and index < pending_sacrifice_offers.size():
		pending_sacrifice_offers.remove_at(index)
	else:
		pending_sacrifice_offers.clear()
	_sync_legacy_sacrifice_state()


func _apply_sacrifice_offer_bonus(offer: Dictionary) -> void:
	var combat: int = int(offer.get("combat", 0))
	var force_discard: int = int(offer.get("force_discard", 0))
	var target: Node = offer.get("target", null)
	if combat > 0:
		gain_combat(combat)
	if force_discard > 0 and target != null and target.has_method("force_discard_random"):
		target.call("force_discard_random", force_discard)


func _find_weakest_sacrificable_hand_index(source_card: Card) -> int:
	var best_index: int = -1
	var best_score: int = 0
	for i in range(hand.size()):
		var candidate: Card = hand[i]
		if candidate == source_card:
			continue
		var score: int = _card_strength_score(candidate)
		if best_index == -1 or score < best_score:
			best_index = i
			best_score = score
	return best_index


func _pop_sacrificable_from_discard(source_card: Card) -> Card:
	for i in range(deck.discard_pile.size() - 1, -1, -1):
		var candidate: Card = deck.discard_pile[i]
		if candidate == source_card:
			continue
		deck.discard_pile.remove_at(i)
		return candidate
	return null


func _card_is_starter(card: Card) -> bool:
	if card == null:
		return false
	return card.cost == 0


func _find_weakest_starter_hand_index(source_card: Card) -> int:
	var best_index: int = -1
	var best_score: int = 0
	for i in range(hand.size()):
		var candidate: Card = hand[i]
		if candidate == source_card:
			continue
		if not _card_is_starter(candidate):
			continue
		var score: int = _card_strength_score(candidate)
		if best_index == -1 or score < best_score:
			best_index = i
			best_score = score
	return best_index


func _pop_starter_from_discard(source_card: Card) -> Card:
	for i in range(deck.discard_pile.size() - 1, -1, -1):
		var candidate: Card = deck.discard_pile[i]
		if candidate == source_card:
			continue
		if not _card_is_starter(candidate):
			continue
		deck.discard_pile.remove_at(i)
		return candidate
	return null


func _build_sacrifice_offer_label(offer: Dictionary) -> String:
	var card: Card = offer.get("source_card", null)
	var source_name: String = card.card_name if card != null else "Sacrifice"
	var parts: Array[String] = []
	var combat: int = int(offer.get("combat", 0))
	var force_discard: int = int(offer.get("force_discard", 0))
	var starters_only: bool = bool(offer.get("starters_only", false))
	if combat > 0:
		parts.append("+%d Combat" % combat)
	if force_discard > 0:
		parts.append("Opponent Discards %d" % force_discard)
	if parts.is_empty():
		if starters_only:
			parts.append("Scrap a Starter")
		else:
			parts.append("Scrap")
	if bool(offer.get("requires_external", false)):
		return "%s: Sacrifice Another Card (%s)" % [source_name, " / ".join(parts)]
	return "%s: Sacrifice This Card (%s)" % [source_name, " / ".join(parts)]


func _queue_sacrifice_offer(source_card: Card, requires_external: bool, target: Node, combat: int, force_discard: int, starters_only: bool = false) -> void:
	for index: int in range(pending_sacrifice_offers.size()):
		var existing: Dictionary = pending_sacrifice_offers[index]
		if existing.get("source_card", null) != source_card:
			continue
		if bool(existing.get("requires_external", false)) != requires_external:
			continue
		existing["combat"] = max(int(existing.get("combat", 0)), combat)
		existing["force_discard"] = max(int(existing.get("force_discard", 0)), force_discard)
		existing["target"] = target
		if starters_only:
			existing["starters_only"] = true
		pending_sacrifice_offers[index] = existing
		_sync_legacy_sacrifice_state()
		return
	pending_sacrifice_offers.append({
		"source_card": source_card,
		"requires_external": requires_external,
		"target": target,
		"combat": combat,
		"force_discard": force_discard,
		"starters_only": starters_only
	})
	_sync_legacy_sacrifice_state()


func _sync_legacy_sacrifice_state() -> void:
	if pending_sacrifice_offers.is_empty():
		pending_sacrifice_combat = 0
		pending_sacrifice_force_discard = 0
		pending_sacrifice_source_card = null
		pending_sacrifice_requires_external_card = false
		pending_sacrifice_target = null
		return
	var first_offer: Dictionary = pending_sacrifice_offers[0]
	pending_sacrifice_combat = int(first_offer.get("combat", 0))
	pending_sacrifice_force_discard = int(first_offer.get("force_discard", 0))
	pending_sacrifice_source_card = first_offer.get("source_card", null)
	pending_sacrifice_requires_external_card = bool(first_offer.get("requires_external", false))
	pending_sacrifice_target = first_offer.get("target", null)


func _ensure_legacy_sacrifice_offer_promoted() -> void:
	if not pending_sacrifice_offers.is_empty():
		return
	if pending_sacrifice_combat <= 0 and pending_sacrifice_force_discard <= 0:
		return
	pending_sacrifice_offers.append({
		"source_card": pending_sacrifice_source_card,
		"requires_external": pending_sacrifice_requires_external_card,
		"target": pending_sacrifice_target,
		"combat": pending_sacrifice_combat,
		"force_discard": pending_sacrifice_force_discard
	})
	_sync_legacy_sacrifice_state()


func _begin_specific_sacrifice_offer(offer_index: int, sacrifice_pile: Array[Card]) -> bool:
	if offer_index < 0 or offer_index >= pending_sacrifice_offers.size():
		return false
	var offer: Dictionary = pending_sacrifice_offers[offer_index]
	if not bool(offer.get("requires_external", false)):
		return _use_specific_sacrifice_offer(offer_index, sacrifice_pile)
	if interaction_mode != "manual":
		return _use_specific_sacrifice_offer(offer_index, sacrifice_pile)

	var options: Array[Dictionary] = []
	var source_card: Card = offer.get("source_card", null)
	var starters_only: bool = bool(offer.get("starters_only", false))
	for i in range(hand.size()):
		var card: Card = hand[i]
		if card == source_card:
			continue
		if starters_only and not _card_is_starter(card):
			continue
		options.append({"label": "%s [Hand]" % card.card_name, "source": "hand", "index": i})
	for i in range(deck.discard_pile.size()):
		var discard_card: Card = deck.discard_pile[i]
		if discard_card == source_card:
			continue
		if starters_only and not _card_is_starter(discard_card):
			continue
		options.append({"label": "%s [Discard]" % discard_card.card_name, "source": "discard", "index": i})

	if options.is_empty():
		_clear_pending_sacrifice_offer(offer_index)
		return false

	pending_choice = {
		"type": "sacrifice_offer",
		"title": "Choose A Card To Sacrifice",
		"message": _build_sacrifice_offer_label(offer),
		"options": options,
		"offer_index": offer_index,
		"sacrifice_pile": sacrifice_pile
	}
	choice_requested.emit(pending_choice.duplicate(true))
	return true


func _use_specific_sacrifice_offer(offer_index: int, sacrifice_pile: Array[Card]) -> bool:
	if offer_index < 0 or offer_index >= pending_sacrifice_offers.size():
		return false
	var offer: Dictionary = pending_sacrifice_offers[offer_index]
	var source_card: Card = offer.get("source_card", null)
	var starters_only: bool = bool(offer.get("starters_only", false))
	var sacrificed: Card = null
	if bool(offer.get("requires_external", false)):
		if not hand.is_empty():
			var weakest_index: int
			if starters_only:
				weakest_index = _find_weakest_starter_hand_index(source_card)
			else:
				weakest_index = _find_weakest_sacrificable_hand_index(source_card)
			if weakest_index != -1:
				sacrificed = hand[weakest_index]
				hand.remove_at(weakest_index)
		if sacrificed == null:
			if starters_only:
				sacrificed = _pop_starter_from_discard(source_card)
			else:
				sacrificed = _pop_sacrificable_from_discard(source_card)
	else:
		sacrificed = source_card
		_remove_card_from_zones(sacrificed)

	if sacrificed == null:
		_clear_pending_sacrifice_offer(offer_index)
		return false

	sacrifice_pile.append(sacrificed)
	_apply_sacrifice_offer_bonus(offer)
	_clear_pending_sacrifice_offer(offer_index)
	_clear_pending_choice()
	state_changed.emit()
	return true


func _remove_card_from_zones(card: Card) -> void:
	if card == null:
		return
	var hand_index: int = hand.find(card)
	if hand_index != -1:
		hand.remove_at(hand_index)
	var discard_index: int = deck.discard_pile.find(card)
	if discard_index != -1:
		deck.discard_pile.remove_at(discard_index)
	var draw_index: int = deck.draw_pile.find(card)
	if draw_index != -1:
		deck.draw_pile.remove_at(draw_index)


func _find_weakest_hand_index() -> int:
	if hand.is_empty():
		return -1

	var best_index: int = 0
	var best_score: int = _card_strength_score(hand[0])
	for i in range(1, hand.size()):
		var score: int = _card_strength_score(hand[i])
		if score < best_score:
			best_score = score
			best_index = i

	return best_index


func _card_strength_score(card: Card) -> int:
	if card == null:
		return -9999

	var score: int = card.cost * 10
	if card is DataCard:
		var data_card: DataCard = card as DataCard
		for effect: Dictionary in data_card.effects:
			var effect_id: String = String(effect.get("id", ""))
			var value: int = int(effect.get("value", 0))
			match effect_id:
				"gain_combat", "gain_gold", "gain_health", "draw_cards", "draw_then_discard", "draw_up_to_then_discard":
					score += value * 4
				"force_discard", "stun_target_champion", "prepare_champion", "ally_bonus":
					score += 8
				"champion_data":
					score += int(effect.get("defense", 0)) * 3
				_:
					pass

	return score


func _count_other_guards(exclude_card: Card) -> int:
	var count: int = 0
	for champion: Dictionary in champions_in_play:
		if champion.get("card", null) == exclude_card:
			continue
		if bool(champion.get("is_guard", false)):
			count += 1
	return count


func _count_other_champions(exclude_card: Card) -> int:
	var count: int = 0
	for champion: Dictionary in champions_in_play:
		if champion.get("card", null) == exclude_card:
			continue
		count += 1
	return count


func _count_other_faction_cards_in_play(exclude_card: Card, faction: String) -> int:
	var normalized: String = faction.to_lower()
	var count: int = 0
	for played: Card in played_cards_this_turn_refs:
		if played == null or played == exclude_card:
			continue
		if _get_card_faction(played) == normalized:
			count += 1
	return count
