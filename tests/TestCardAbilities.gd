extends Node

var _failed: int = 0
var _passed: int = 0


func _ready() -> void:
	randomize()
	GameState.load_databases()
	run_all()
	var total: int = _passed + _failed
	print("[TEST] Completed %d tests. Passed=%d Failed=%d" % [total, _passed, _failed])
	get_tree().quit(0 if _failed == 0 else 1)


func run_all() -> void:
	test_draw_cards_effect()
	test_sacrifice_offer_grants_combat()
	test_force_discard_effect()
	test_gain_gold_effect()
	test_gain_health_effect()
	test_ally_triggers_for_both_cards_once()
	test_market_entry_draw_parsing_and_effect()
	test_market_entry_opponent_discard_parsing_and_effect()


func test_draw_cards_effect() -> void:
	var player := _make_player()
	player.deck.draw_pile.append(_make_data_card("Seed 1", []))
	player.deck.draw_pile.append(_make_data_card("Seed 2", []))
	player.draw_cards(2)
	var hand_before: int = player.hand.size()
	var draw_card := _make_data_card("Draw Spell", [
		{"id": "draw_cards", "value": 2}
	])
	player.deck.draw_pile.append(_make_data_card("Seed 3", []))
	player.deck.draw_pile.append(_make_data_card("Seed 4", []))
	player.hand.append(draw_card)

	var ok: bool = player.play_card(draw_card, null)
	_assert_true(ok, "draw_cards: card should play")
	_assert_equal(player.hand.size(), hand_before + 2, "draw_cards: net hand should increase by 2")


func test_sacrifice_offer_grants_combat() -> void:
	var player := _make_player()
	var sacrifice_pile: Array[Card] = []

	var gem := _make_data_card("Fire Gem", [
		{"id": "gain_gold", "value": 2},
		{"id": "sacrifice_combat_offer", "value": 3}
	])
	player.hand.append(gem)
	var filler := _make_data_card("Filler", [])
	player.hand.append(filler)

	var ok_play: bool = player.play_card(gem, null)
	_assert_true(ok_play, "sacrifice: fire gem should play")
	_assert_true(player.has_pending_sacrifice_offer(), "sacrifice: offer should be pending")

	var ok_use: bool = player.use_sacrifice_offer(sacrifice_pile)
	_assert_true(ok_use, "sacrifice: should resolve when hand has a card")
	_assert_equal(player.combat_pool, 3, "sacrifice: should grant +3 combat")
	_assert_equal(sacrifice_pile.size(), 1, "sacrifice: exactly one card should be sacrificed")


func test_force_discard_effect() -> void:
	var attacker := _make_player()
	var defender := _make_player()

	defender.hand.append(_make_data_card("A", []))
	defender.hand.append(_make_data_card("B", []))
	var defender_hand_before: int = defender.hand.size()
	var defender_discard_before: int = defender.deck.discard_count()

	var discard_card := _make_data_card("Mind Rake", [
		{"id": "force_discard", "value": 1}
	])
	attacker.hand.append(discard_card)

	var ok: bool = attacker.play_card(discard_card, defender)
	_assert_true(ok, "force_discard: card should play")
	_assert_equal(defender.hand.size(), defender_hand_before - 1, "force_discard: defender hand should drop by 1")
	_assert_equal(defender.deck.discard_count(), defender_discard_before + 1, "force_discard: defender discard should increase")


func test_gain_gold_effect() -> void:
	var player := _make_player()
	var gold_card := _make_data_card("Gold", [
		{"id": "gain_gold", "value": 1}
	])
	player.hand.append(gold_card)

	var ok: bool = player.play_card(gold_card, null)
	_assert_true(ok, "gain_gold: card should play")
	_assert_equal(player.gold_pool, 1, "gain_gold: pool should increase")


func test_gain_health_effect() -> void:
	var player := _make_player()
	player.current_hp = 40
	var heal_card := _make_data_card("Heal", [
		{"id": "gain_health", "value": 4}
	])
	player.hand.append(heal_card)

	var ok: bool = player.play_card(heal_card, null)
	_assert_true(ok, "gain_health: card should play")
	_assert_equal(player.current_hp, 44, "gain_health: hp should increase")


func test_ally_triggers_for_both_cards_once() -> void:
	var player := _make_player()
	var card_a := _make_data_card("Guild A", [
		{"id": "set_faction", "faction": "guild"},
		{"id": "gain_gold", "value": 1},
		{"id": "ally_bonus", "faction": "guild", "gold": 2}
	])
	var card_b := _make_data_card("Guild B", [
		{"id": "set_faction", "faction": "guild"},
		{"id": "gain_gold", "value": 1},
		{"id": "ally_bonus", "faction": "guild", "gold": 2}
	])

	player.hand.append(card_a)
	player.hand.append(card_b)

	_assert_true(player.play_card(card_a, null), "ally: first faction card should play")
	_assert_true(player.play_card(card_b, null), "ally: second faction card should play")

	# Base gold: 1 + 1, plus ally bonuses from both cards once each: +2 +2
	_assert_equal(player.gold_pool, 6, "ally: both relevant ally abilities should trigger once")


func test_market_entry_draw_parsing_and_effect() -> void:
	var player := _make_player()
	player.draw_cards(1)
	var hand_before: int = player.hand.size()

	var entry: Dictionary = {
		"name": "Command",
		"faction": "imperial",
		"type": "Action",
		"cost": 5,
		"combat": 3,
		"gold": 2,
		"health": 4,
		"draw_cards": 1,
		"sacrifice_combat": 0,
		"opponent_discard": 0,
		"ally_combat": 0,
		"ally_gold": 0,
		"ally_health": 0,
		"effect": "{Gain 2 gold} {Gain 3 combat} {Gain 4 health} Draw a card.",
		"image_path": ""
	}

	var card: Card = GameState.create_market_card_from_entry(entry)
	player.hand.append(card)
	_assert_true(player.play_card(card, null), "market draw: generated market card should play")

	# Played one card and drew one card => hand count unchanged.
	_assert_equal(player.hand.size(), hand_before, "market draw: draw effect should resolve from generated card")


func test_market_entry_opponent_discard_parsing_and_effect() -> void:
	var attacker := _make_player()
	var defender := _make_player()
	defender.hand.append(_make_data_card("Def A", []))
	defender.hand.append(_make_data_card("Def B", []))
	var before_hand: int = defender.hand.size()

	var entry: Dictionary = {
		"name": "Spark",
		"faction": "wild",
		"type": "Action",
		"cost": 1,
		"combat": 3,
		"gold": 0,
		"health": 0,
		"draw_cards": 0,
		"sacrifice_combat": 0,
		"opponent_discard": 1,
		"ally_combat": 2,
		"ally_gold": 0,
		"ally_health": 0,
		"effect": "{Gain 3 combat} Target opponent discards a card.",
		"image_path": ""
	}

	var card: Card = GameState.create_market_card_from_entry(entry)
	attacker.hand.append(card)
	_assert_true(attacker.play_card(card, defender), "market discard: generated discard card should play")
	_assert_equal(defender.hand.size(), before_hand - 1, "market discard: opponent should discard one card")


func _make_player() -> BattlePlayer:
	var player := BattlePlayer.new()
	player.setup_from_ids("Tester", 50, 0, GameState.starting_deck_ids)
	player.hand.clear()
	player.deck.draw_pile.clear()
	player.deck.discard_pile.clear()
	return player


func _make_data_card(card_name: String, effects: Array[Dictionary]) -> DataCard:
	var card := DataCard.new()
	card.setup_from_dict({
		"name": card_name,
		"cost": 0,
		"type": "Action",
		"description": card_name,
		"effects": effects
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
