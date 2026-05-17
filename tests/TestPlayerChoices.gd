extends Node

var _failed: int = 0
var _passed: int = 0
var _last_choice: Dictionary = {}


func _ready() -> void:
	GameState.load_databases()
	run_all()
	print("[CHOICE-TEST] Completed %d tests. Passed=%d Failed=%d" % [_passed + _failed, _passed, _failed])
	get_tree().quit(0 if _failed == 0 else 1)


func run_all() -> void:
	test_manual_discard_choice_request()
	test_manual_sacrifice_choice_request()
	test_manual_choice_branch_request()
	test_self_sacrifice_uses_source_card()
	test_external_sacrifice_excludes_source_card()
	test_multi_discard_choice_resolves_all_steps()
	test_multiple_sacrifice_offers_require_ability_choice()
	test_ally_bonus_queued_not_auto_fired_in_manual_mode()
	test_ally_bonus_activates_on_demand()
	test_ally_bonus_auto_fires_in_ai_mode()
	test_sacrifice_scrap_only_shows_starters()
	test_sacrifice_scrap_resolves_without_combat_bonus()
	test_sacrifice_scrap_removes_card_from_zones()
	test_external_sacrifice_for_combat_uses_starters()
	test_begin_ally_activation_choice_shows_popup()
	test_ally_activation_resolves_sub_choice()
	test_end_turn_not_blocked_after_choice_resolves()
	test_champion_and_action_allies_trigger_with_champion_in_play()
	test_draw_reshuffles_discard_when_draw_empty_mid_turn()


func test_manual_discard_choice_request() -> void:
	var player := _make_player()
	var target := _make_player()
	player.set_interaction_mode("manual")
	player.choice_requested.connect(_capture_choice)
	player.hand.append(_make_action("Weak", 0, []))
	player.hand.append(_make_action("Rampage", 0, [{"id": "draw_up_to_then_discard", "max_draw": 1, "value": 1}]))
	player.deck.draw_pile.append(_make_action("Drawn", 0, []))

	var rampage: Card = player.hand[1]
	_assert_true(player.play_card(rampage, target), "manual discard: card should play")
	_assert_equal(String(_last_choice.get("type", "")), "discard_from_hand", "manual discard: popup requested")
	_assert_true(player.resolve_pending_choice(0), "manual discard: choice resolves")


func test_manual_sacrifice_choice_request() -> void:
	var player := _make_player()
	player.set_interaction_mode("manual")
	player.choice_requested.connect(_capture_choice)
	player.hand.append(_make_action("Filler", 0, []))
	player.pending_sacrifice_combat = 3
	player.pending_sacrifice_requires_external_card = true
	var sacrifice_pile: Array[Card] = []
	_assert_true(player.begin_sacrifice_choice(sacrifice_pile), "manual sacrifice: popup requested")
	_assert_equal(String(_last_choice.get("type", "")), "sacrifice_offer", "manual sacrifice: type matches")
	_assert_true(player.resolve_pending_choice(0), "manual sacrifice: choice resolves")
	_assert_equal(player.combat_pool, 3, "manual sacrifice: combat gained")


func test_manual_choice_branch_request() -> void:
	var player := _make_player()
	var target := _make_player()
	player.set_interaction_mode("manual")
	player.choice_requested.connect(_capture_choice)
	var chooser := _make_action("Darian", 0, [{"id": "choice_gain_combat_or_health", "value": 3, "health": 4}])
	player.hand.append(chooser)
	_assert_true(player.play_card(chooser, target), "manual branch: card should play")
	_assert_equal(String(_last_choice.get("type", "")), "choice_gain_combat_or_health", "manual branch: popup requested")
	_assert_true(player.resolve_pending_choice(1), "manual branch: select health")
	_assert_equal(player.current_hp, player.max_hp, "manual branch: health branch resolves without overflow")


func test_self_sacrifice_uses_source_card() -> void:
	var player := _make_player()
	var target := _make_player()
	player.set_interaction_mode("manual")
	var source := _make_action("Influence", 2, [
		{"id": "gain_gold", "value": 3},
		{"id": "sacrifice_combat_offer", "value": 3}
	])
	player.hand.append(source)
	_assert_true(player.play_card(source, target), "self sacrifice: source card should play")
	_assert_true(player.has_pending_sacrifice_offer(), "self sacrifice: offer should be pending")
	var sacrifice_pile: Array[Card] = []
	_assert_true(player.begin_sacrifice_choice(sacrifice_pile), "self sacrifice: should resolve without target choice")
	_assert_equal(sacrifice_pile.size(), 1, "self sacrifice: one card sacrificed")
	_assert_equal(sacrifice_pile[0], source, "self sacrifice: sacrificed card is the source card")
	_assert_equal(player.combat_pool, 3, "self sacrifice: combat gained")


func test_external_sacrifice_excludes_source_card() -> void:
	var player := _make_player()
	var target := _make_player()
	player.set_interaction_mode("manual")
	player.choice_requested.connect(_capture_choice)
	var source := _make_action("The Rot", 3, [
		{"id": "gain_combat", "value": 4},
		{"id": "sacrifice_for_additional_combat", "value": 3}
	])
	var fodder := _make_action("Weak Fodder", 0, [])
	player.hand.append(source)
	player.hand.append(fodder)
	_assert_true(player.play_card(source, target), "external sacrifice: source card should play")
	var sacrifice_pile: Array[Card] = []
	_assert_true(player.begin_sacrifice_choice(sacrifice_pile), "external sacrifice: should open choice")
	_assert_equal(String(_last_choice.get("type", "")), "sacrifice_offer", "external sacrifice: choice type matches")
	for option: Dictionary in _last_choice.get("options", []):
		var label: String = String(option.get("label", "")).to_lower()
		_assert_true(not label.contains("the rot"), "external sacrifice: source card is excluded")


func test_multi_discard_choice_resolves_all_steps() -> void:
	var player := _make_player()
	var target := _make_player()
	player.set_interaction_mode("manual")
	player.choice_requested.connect(_capture_choice)
	player.hand.append(_make_action("Weak One", 0, []))
	player.hand.append(_make_action("Weak Two", 0, []))
	player.hand.append(_make_action("Rampage", 0, [{"id": "draw_up_to_then_discard", "max_draw": 2, "value": 2}]))
	player.deck.draw_pile.append(_make_action("Drawn A", 0, []))
	player.deck.draw_pile.append(_make_action("Drawn B", 0, []))

	var rampage: Card = player.hand[2]
	_assert_true(player.play_card(rampage, target), "multi discard: card should play")
	_assert_equal(String(_last_choice.get("type", "")), "discard_from_hand", "multi discard: popup requested")
	_assert_true(player.resolve_pending_choice(0), "multi discard: first choice resolves")
	_assert_equal(String(player.pending_choice.get("type", "")), "discard_from_hand", "multi discard: second prompt remains active")
	_assert_true(player.resolve_pending_choice(0), "multi discard: second choice resolves")
	_assert_true(not player.has_pending_choice(), "multi discard: choice chain completes")


func test_multiple_sacrifice_offers_require_ability_choice() -> void:
	var player := _make_player()
	var target := _make_player()
	player.set_interaction_mode("manual")
	player.choice_requested.connect(_capture_choice)
	var first_offer := _make_action("Influence", 2, [{"id": "sacrifice_combat_offer", "value": 3}])
	var second_offer := _make_action("Fire Bomb", 8, [{"id": "sacrifice_combat_offer", "value": 5}])
	player.hand.append(first_offer)
	player.hand.append(second_offer)

	_assert_true(player.play_card(first_offer, target), "multi sacrifice: first source plays")
	_assert_true(player.play_card(second_offer, target), "multi sacrifice: second source plays")
	var sacrifice_pile: Array[Card] = []
	_assert_true(player.begin_sacrifice_choice(sacrifice_pile), "multi sacrifice: button should open a choice")
	_assert_equal(String(_last_choice.get("type", "")), "sacrifice_ability", "multi sacrifice: ability selection requested")
	_assert_equal((_last_choice.get("options", []) as Array).size(), 2, "multi sacrifice: both sacrifice abilities are listed")


func test_ally_bonus_queued_not_auto_fired_in_manual_mode() -> void:
	var player := _make_player()
	var target := _make_player()
	player.set_interaction_mode("manual")
	var card_a := _make_action("Orc A", 3, [
		{"id": "set_faction", "faction": "wild"},
		{"id": "gain_combat", "value": 2},
		{"id": "ally_bonus", "faction": "wild", "combat": 3}
	])
	var card_b := _make_action("Orc B", 3, [
		{"id": "set_faction", "faction": "wild"},
		{"id": "gain_combat", "value": 2},
		{"id": "ally_bonus", "faction": "wild", "combat": 3}
	])
	player.hand.append(card_a)
	player.hand.append(card_b)
	player.play_card(card_a, target)
	player.play_card(card_b, target)
	_assert_equal(player.combat_pool, 4, "ally manual: base combat only, no auto ally bonus (2+2=4)")
	var pending: Array[Dictionary] = player.get_pending_ally_activations()
	_assert_true(pending.size() >= 1, "ally manual: at least one activation queued")


func test_ally_bonus_activates_on_demand() -> void:
	var player := _make_player()
	var target := _make_player()
	player.set_interaction_mode("manual")
	var card_a := _make_action("Orc A", 3, [
		{"id": "set_faction", "faction": "wild"},
		{"id": "gain_combat", "value": 2},
		{"id": "ally_bonus", "faction": "wild", "combat": 5}
	])
	var card_b := _make_action("Orc B", 3, [
		{"id": "set_faction", "faction": "wild"},
		{"id": "gain_combat", "value": 1}
	])
	player.hand.append(card_a)
	player.hand.append(card_b)
	player.play_card(card_a, target)
	player.play_card(card_b, target)
	var pending: Array[Dictionary] = player.get_pending_ally_activations()
	_assert_true(pending.size() == 1, "ally activate: one activation pending (only card_a has ally_bonus)")
	var trigger_key: String = String(pending[0].get("trigger_key", ""))
	_assert_true(player.combat_pool == 3, "ally activate: combat before activation = 2+1=3")
	_assert_true(player.activate_ally_bonus(trigger_key), "ally activate: activate_ally_bonus returns true")
	_assert_equal(player.combat_pool, 8, "ally activate: combat after activation = 3+5=8")
	_assert_equal(player.get_pending_ally_activations().size(), 0, "ally activate: no more pending after activation")


func test_ally_bonus_auto_fires_in_ai_mode() -> void:
	var player := _make_player()
	var target := _make_player()
	player.set_interaction_mode("auto")
	var card_a := _make_action("Orc A", 3, [
		{"id": "set_faction", "faction": "wild"},
		{"id": "gain_combat", "value": 2},
		{"id": "ally_bonus", "faction": "wild", "combat": 3}
	])
	var card_b := _make_action("Orc B", 3, [
		{"id": "set_faction", "faction": "wild"},
		{"id": "gain_combat", "value": 2}
	])
	player.hand.append(card_a)
	player.hand.append(card_b)
	player.play_card(card_a, target)
	player.play_card(card_b, target)
	_assert_equal(player.combat_pool, 7, "ally auto: 2+2+3=7 (auto-fired)")
	_assert_equal(player.get_pending_ally_activations().size(), 0, "ally auto: nothing pending in ai mode")


func test_sacrifice_scrap_only_shows_starters() -> void:
	var player := _make_player()
	var target := _make_player()
	player.set_interaction_mode("manual")
	player.choice_requested.connect(_capture_choice)
	var non_starter := _make_action("Expensive Card", 5, [])
	var starter_a := _make_action("Gold", 0, [])
	var starter_b := _make_action("Dagger", 0, [])
	var source := _make_action("Death Touch", 1, [
		{"id": "gain_combat", "value": 2},
		{"id": "sacrifice_scrap", "starters_only": true}
	])
	player.hand.append(source)
	player.hand.append(non_starter)
	player.hand.append(starter_a)
	player.deck.discard_pile.append(starter_b)
	_assert_true(player.play_card(source, target), "sacrifice scrap: card plays")
	_assert_true(player.has_pending_sacrifice_offer(), "sacrifice scrap: offer pending")
	var sacrifice_pile: Array[Card] = []
	_assert_true(player.begin_sacrifice_choice(sacrifice_pile), "sacrifice scrap: choice opened")
	_assert_equal(String(_last_choice.get("type", "")), "sacrifice_offer", "sacrifice scrap: type is sacrifice_offer")
	var options: Array = _last_choice.get("options", [])
	for option: Dictionary in options:
		var label: String = String(option.get("label", ""))
		_assert_true(not label.contains("Expensive Card"), "sacrifice scrap: non-starter excluded from options")
	_assert_true(options.size() >= 1, "sacrifice scrap: at least one starter option shown")


func test_sacrifice_scrap_resolves_without_combat_bonus() -> void:
	var player := _make_player()
	var target := _make_player()
	player.set_interaction_mode("manual")
	player.choice_requested.connect(_capture_choice)
	var starter := _make_action("Gold", 0, [])
	var source := _make_action("Death Touch", 1, [
		{"id": "gain_combat", "value": 2},
		{"id": "sacrifice_scrap", "starters_only": true}
	])
	player.hand.append(source)
	player.hand.append(starter)
	_assert_true(player.play_card(source, target), "scrap resolve: card plays")
	_assert_equal(player.combat_pool, 2, "scrap resolve: base combat from card effect")
	var sacrifice_pile: Array[Card] = []
	_assert_true(player.begin_sacrifice_choice(sacrifice_pile), "scrap resolve: choice opened")
	_assert_true(player.resolve_pending_choice(0), "scrap resolve: choice resolves")
	_assert_equal(player.combat_pool, 2, "scrap resolve: no extra combat from scrapping")
	_assert_equal(player.hand.size(), 0, "scrap resolve: starter removed from hand")


func test_sacrifice_scrap_removes_card_from_zones() -> void:
	var player := _make_player()
	var target := _make_player()
	player.set_interaction_mode("manual")
	player.choice_requested.connect(_capture_choice)
	var starter_hand := _make_action("Gold", 0, [])
	var starter_discard := _make_action("Dagger", 0, [])
	var source := _make_action("Death Touch", 1, [
		{"id": "gain_combat", "value": 2},
		{"id": "sacrifice_scrap", "starters_only": true}
	])
	player.hand.append(source)
	player.hand.append(starter_hand)
	player.deck.discard_pile.append(starter_discard)
	_assert_true(player.play_card(source, target), "scrap zones: source plays")
	# After play: hand=[starter_hand], discard=[starter_discard, source(played)]
	var hand_before: int = player.hand.size()
	var discard_before: int = player.deck.discard_pile.size()
	var sacrifice_pile: Array[Card] = []
	_assert_true(player.begin_sacrifice_choice(sacrifice_pile), "scrap zones: choice opened")
	_assert_true(player.resolve_pending_choice(0), "scrap zones: resolved")
	var removed_from_hand: bool = player.hand.size() < hand_before
	var removed_from_discard: bool = player.deck.discard_pile.size() < discard_before
	_assert_true(removed_from_hand or removed_from_discard, "scrap zones: a card was removed from hand or discard")
	_assert_equal(sacrifice_pile.size(), 1, "scrap zones: sacrificed card went to sacrifice pile")


func test_external_sacrifice_for_combat_uses_starters() -> void:
	var player := _make_player()
	var target := _make_player()
	player.set_interaction_mode("manual")
	player.choice_requested.connect(_capture_choice)
	var non_starter := _make_action("Elite Card", 5, [])
	var starter := _make_action("Gold", 0, [])
	var krythos_style := _make_action("Krythos", 7, [
		{"id": "gain_combat", "value": 3},
		{"id": "sacrifice_for_additional_combat", "value": 3, "starters_only": true}
	])
	player.hand.append(krythos_style)
	player.hand.append(non_starter)
	player.hand.append(starter)
	_assert_true(player.play_card(krythos_style, target), "krythos scrap: card plays")
	_assert_equal(player.combat_pool, 3, "krythos scrap: base 3 combat")
	var sacrifice_pile: Array[Card] = []
	_assert_true(player.begin_sacrifice_choice(sacrifice_pile), "krythos scrap: choice opened")
	_assert_equal(String(_last_choice.get("type", "")), "sacrifice_offer", "krythos scrap: sacrifice_offer choice type")
	var options: Array = _last_choice.get("options", [])
	for option: Dictionary in options:
		var label: String = String(option.get("label", ""))
		_assert_true(not label.contains("Elite Card"), "krythos scrap: non-starter excluded")
	_assert_true(options.size() >= 1, "krythos scrap: at least one starter available")
	_assert_true(player.resolve_pending_choice(0), "krythos scrap: resolves")
	_assert_equal(player.combat_pool, 6, "krythos scrap: +3 additional combat gained")


func test_begin_ally_activation_choice_shows_popup() -> void:
	var player := _make_player()
	var target := _make_player()
	player.set_interaction_mode("manual")
	player.choice_requested.connect(_capture_choice)
	var card_a := _make_action("Orc A", 3, [
		{"id": "set_faction", "faction": "wild"},
		{"id": "gain_combat", "value": 2},
		{"id": "ally_bonus", "faction": "wild", "combat": 3}
	])
	var card_b := _make_action("Orc B", 3, [
		{"id": "set_faction", "faction": "wild"},
		{"id": "gain_combat", "value": 1}
	])
	player.hand.append(card_a)
	player.hand.append(card_b)
	player.play_card(card_a, target)
	player.play_card(card_b, target)
	_assert_true(player.get_pending_ally_activations().size() > 0, "ally choice: activations pending")
	_assert_true(player.begin_ally_activation_choice(), "ally choice: returns true")
	_assert_equal(String(_last_choice.get("type", "")), "ally_activation", "ally choice: type is ally_activation")
	_assert_true(player.resolve_pending_choice(0), "ally choice: resolves")
	_assert_equal(player.combat_pool, 6, "ally choice: 2+1+3=6 after activation")


func test_ally_activation_resolves_sub_choice() -> void:
	var player := _make_player()
	var target := _make_player()
	player.set_interaction_mode("manual")
	player.choice_requested.connect(_capture_choice)
	player.hand.append(_make_action("Filler", 0, []))
	var card_a := _make_action("Draw Ally", 3, [
		{"id": "set_faction", "faction": "necros"},
		{"id": "gain_combat", "value": 1},
		{"id": "ally_bonus", "faction": "necros", "draw_then_discard": 1}
	])
	var card_b := _make_action("Necros Action", 3, [
		{"id": "set_faction", "faction": "necros"},
		{"id": "gain_combat", "value": 1}
	])
	player.hand.append(card_a)
	player.hand.append(card_b)
	player.deck.draw_pile.append(_make_action("Drawn", 0, []))
	player.play_card(card_a, target)
	player.play_card(card_b, target)
	_assert_true(player.begin_ally_activation_choice(), "sub choice: ally choice begins")
	_assert_equal(String(_last_choice.get("type", "")), "ally_activation", "sub choice: type correct")
	_assert_true(player.resolve_pending_choice(0), "sub choice: ally resolved, triggers draw_then_discard")
	_assert_equal(String(player.pending_choice.get("type", "")), "discard_from_hand", "sub choice: discard_from_hand pending")
	_assert_true(player.resolve_pending_choice(0), "sub choice: discard resolves")
	_assert_true(not player.has_pending_choice(), "sub choice: all choices resolved")


func test_end_turn_not_blocked_after_choice_resolves() -> void:
	var player := _make_player()
	var target := _make_player()
	player.set_interaction_mode("manual")
	player.choice_requested.connect(_capture_choice)
	player.hand.append(_make_action("Filler", 0, []))
	var rampage := _make_action("Rampage", 6, [{"id": "draw_up_to_then_discard", "max_draw": 1, "value": 1}])
	player.hand.append(rampage)
	player.deck.draw_pile.append(_make_action("Drawn", 0, []))
	_assert_true(player.play_card(rampage, target), "end turn block: rampage plays")
	_assert_true(player.has_pending_choice(), "end turn block: discard choice pending")
	_assert_true(player.resolve_pending_choice(0), "end turn block: resolve discard choice")
	_assert_true(not player.has_pending_choice(), "end turn block: no pending choice after resolving")


func test_champion_and_action_allies_trigger_with_champion_in_play() -> void:
	var player := _make_player()
	var target := _make_player()
	player.set_interaction_mode("manual")
	player.choice_requested.connect(_capture_choice)

	var wild_champion := _make_champion("Wild Champ", 4, true, [
		{"id": "set_faction", "faction": "wild"},
		{"id": "champion_data", "defense": 4, "guard": true, "combat": 2, "gold": 0, "health": 0},
		{"id": "ally_bonus", "faction": "wild", "draw_cards": 1}
	])
	var wild_action := _make_action("Wild Action", 3, [
		{"id": "set_faction", "faction": "wild"},
		{"id": "gain_combat", "value": 2},
		{"id": "ally_bonus", "faction": "wild", "combat": 3}
	])

	player.hand.append(wild_champion)
	_assert_true(player.play_card(wild_champion, target), "ally champion/action: champion played")
	player.hand.append(wild_action)
	_assert_true(player.play_card(wild_action, target), "ally champion/action: action played")
	_assert_equal(player.get_pending_ally_activations().size(), 2, "ally champion/action: both allies become activatable")


func test_draw_reshuffles_discard_when_draw_empty_mid_turn() -> void:
	var player := _make_player()
	player.hand.clear()
	player.deck.draw_pile.clear()
	player.deck.discard_pile.clear()
	player.deck.discard_pile.append(_make_action("Recovered", 0, []))
	player.draw_cards(1)
	_assert_equal(player.hand.size(), 1, "reshuffle mid-turn: drew card from shuffled discard")
	_assert_equal(player.deck.draw_count(), 0, "reshuffle mid-turn: draw pile consumed")
	_assert_equal(player.deck.discard_count(), 0, "reshuffle mid-turn: discard moved into draw")


func _capture_choice(choice: Dictionary) -> void:
	_last_choice = choice.duplicate(true)


func _make_player() -> BattlePlayer:
	var player := BattlePlayer.new()
	player.setup_from_ids("Tester", 50, 0, GameState.starting_deck_ids)
	player.hand.clear()
	player.deck.draw_pile.clear()
	player.deck.discard_pile.clear()
	_last_choice = {}
	return player


func _make_action(card_name: String, cost: int, effects: Array[Dictionary]) -> DataCard:
	var card := DataCard.new()
	card.setup_from_dict({
		"name": card_name,
		"cost": cost,
		"type": "Action",
		"description": card_name,
		"effects": effects
	})
	return card


func _make_champion(card_name: String, cost: int, is_guard: bool, effects: Array[Dictionary]) -> DataCard:
	var all_effects: Array[Dictionary] = []
	for effect: Dictionary in effects:
		all_effects.append(effect.duplicate(true))
	var has_meta: bool = false
	for effect: Dictionary in all_effects:
		if String(effect.get("id", "")) == "champion_data":
			has_meta = true
			break
	if not has_meta:
		all_effects.append({"id": "champion_data", "defense": 4, "guard": is_guard, "combat": 0, "gold": 0, "health": 0})

	var card := DataCard.new()
	card.setup_from_dict({
		"name": card_name,
		"cost": cost,
		"type": "Champion",
		"description": card_name,
		"effects": all_effects
	})
	return card


func _assert_equal(actual: Variant, expected: Variant, label: String) -> void:
	if actual == expected:
		_passed += 1
		print("[PASS] %s" % label)
	else:
		_failed += 1
		push_error("[FAIL] %s | expected=%s actual=%s" % [label, str(expected), str(actual)])


func _assert_true(value: bool, label: String) -> void:
	_assert_equal(value, true, label)
