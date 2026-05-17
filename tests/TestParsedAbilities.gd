extends Node

var _failed: int = 0
var _passed: int = 0


func _ready() -> void:
	randomize()
	GameState.load_databases()
	run_all()
	var total: int = _passed + _failed
	print("[PARSE-TEST] Completed %d tests. Passed=%d Failed=%d" % [total, _passed, _failed])
	get_tree().quit(0 if _failed == 0 else 1)


func run_all() -> void:
	test_man_at_arms_scaling_combat()
	test_rampage_draw_then_discard_from_hand()
	test_prepare_champion_effect()
	test_stun_target_champion_effect()
	test_next_acquire_to_hand_effect()
	test_next_acquire_to_topdeck_action_effect()
	test_recover_discard_to_topdeck_effect()
	test_elven_gift_parses_draw_then_discard()
	test_close_ranks_scales_with_champions()
	test_all_market_cards_have_effects()


func test_man_at_arms_scaling_combat() -> void:
	var player := _make_player()
	var target := _make_player()

	var guard_a := _make_champion("Guard A", 3, true, [
		{"id": "set_faction", "faction": "imperial"},
		{"id": "champion_data", "defense": 3, "guard": true, "combat": 0, "gold": 0, "health": 0}
	])
	var guard_b := _make_champion("Guard B", 4, true, [
		{"id": "set_faction", "faction": "imperial"},
		{"id": "champion_data", "defense": 4, "guard": true, "combat": 0, "gold": 0, "health": 0}
	])
	var man_at_arms := _make_champion("Man-at-Arms", 4, true, [
		{"id": "set_faction", "faction": "imperial"},
		{"id": "gain_combat", "value": 2},
		{"id": "for_each_other_guard_gain_combat", "value": 1},
		{"id": "champion_data", "defense": 4, "guard": true, "combat": 0, "gold": 0, "health": 0}
	])

	player.hand.append(guard_a)
	player.hand.append(guard_b)
	player.hand.append(man_at_arms)
	_assert_true(player.play_card(guard_a, target), "man-at-arms: guard A played")
	_assert_true(player.play_card(guard_b, target), "man-at-arms: guard B played")
	_assert_true(player.play_card(man_at_arms, target), "man-at-arms: self played")

	_assert_equal(player.champions_in_play.size(), 3, "man-at-arms: champions in play")
	_assert_true(player.expend_champion(2), "man-at-arms: expend champion")
	_assert_equal(player.combat_pool, 4, "man-at-arms: gets 2 + 1 per other guard")


func test_rampage_draw_then_discard_from_hand() -> void:
	var player := _make_player()
	var target := _make_player()

	var weak_1 := _make_action("Weak 1", 1, [{"id": "gain_gold", "value": 1}])
	var weak_2 := _make_action("Weak 2", 1, [{"id": "gain_gold", "value": 1}])
	var strong_1 := _make_action("Strong 1", 4, [{"id": "gain_combat", "value": 6}])
	var strong_2 := _make_action("Strong 2", 4, [{"id": "gain_combat", "value": 5}])
	var rampage := _make_action("Rampage", 6, [
		{"id": "gain_combat", "value": 6},
		{"id": "draw_up_to_then_discard", "max_draw": 2, "value": 2}
	])

	player.hand.append(weak_1)
	player.hand.append(weak_2)
	player.hand.append(rampage)
	player.deck.draw_pile.append(strong_1)
	player.deck.draw_pile.append(strong_2)

	var before_hand: int = player.hand.size()
	_assert_true(player.play_card(rampage, target), "rampage: card played")
	_assert_equal(player.hand.size(), before_hand - 1, "rampage: net hand reduced by played card only")
	_assert_equal(player.combat_pool, 6, "rampage: gains base combat")
	# Discard now contains played Rampage plus two weakest discarded cards.
	_assert_equal(player.deck.discard_count(), 3, "rampage: weakest cards were discarded after drawing")


func test_prepare_champion_effect() -> void:
	var player := _make_player()
	var target := _make_player()
	var champion := _make_champion("Spent Champ", 4, false, [
		{"id": "set_faction", "faction": "imperial"},
		{"id": "champion_data", "defense": 4, "guard": false, "combat": 2, "gold": 0, "health": 0}
	])
	player.hand.append(champion)
	_assert_true(player.play_card(champion, target), "prepare: champion played")
	_assert_true(player.expend_champion(0), "prepare: first expend")
	_assert_equal(player.combat_pool, 2, "prepare: first expend grants combat")

	var prepare_card := _make_action("Prepare", 4, [
		{"id": "prepare_champion", "value": 1}
	])
	player.hand.append(prepare_card)
	_assert_true(player.play_card(prepare_card, target), "prepare: action played")
	_assert_true(player.expend_champion(0), "prepare: champion re-prepared")
	_assert_equal(player.combat_pool, 4, "prepare: second expend grants combat again")


func test_stun_target_champion_effect() -> void:
	var player := _make_player()
	var target := _make_player()
	var enemy_champion := _make_champion("Enemy Champ", 4, true, [
		{"id": "set_faction", "faction": "guild"},
		{"id": "champion_data", "defense": 4, "guard": true, "combat": 0, "gold": 0, "health": 0}
	])
	target.hand.append(enemy_champion)
	_assert_true(target.play_card(enemy_champion, player), "stun: enemy champion played")

	var stun_card := _make_action("Stun", 4, [
		{"id": "stun_target_champion", "value": 1}
	])
	player.hand.append(stun_card)
	_assert_true(player.play_card(stun_card, target), "stun: action played")
	_assert_equal(target.champions_in_play.size(), 0, "stun: target champion removed")


func test_next_acquire_to_hand_effect() -> void:
	var player := _make_player()
	var target := _make_player()
	var setup_card := _make_action("Deception Ally", 0, [
		{"id": "next_acquire_to_hand_any", "value": 1}
	])
	player.hand.append(setup_card)
	_assert_true(player.play_card(setup_card, target), "acquire-hand: setup card played")

	var purchased := _make_action("Purchased", 3, [{"id": "gain_combat", "value": 3}])
	var hand_before: int = player.hand.size()
	player.receive_acquired_card(purchased)
	_assert_equal(player.hand.size(), hand_before + 1, "acquire-hand: acquired card enters hand")


func test_next_acquire_to_topdeck_action_effect() -> void:
	var player := _make_player()
	var target := _make_player()
	var setup_card := _make_action("Bribe Ally", 0, [
		{"id": "next_acquire_to_topdeck_action", "value": 1}
	])
	player.hand.append(setup_card)
	_assert_true(player.play_card(setup_card, target), "acquire-topdeck: setup card played")

	var purchased := _make_action("Purchased Action", 3, [{"id": "gain_combat", "value": 3}])
	var draw_before: int = player.deck.draw_count()
	player.receive_acquired_card(purchased)
	_assert_equal(player.deck.draw_count(), draw_before + 1, "acquire-topdeck: action placed on draw pile")


func test_recover_discard_to_topdeck_effect() -> void:
	var player := _make_player()
	var target := _make_player()
	var recovered := _make_champion("Recovered Champ", 4, false, [
		{"id": "set_faction", "faction": "necros"},
		{"id": "champion_data", "defense": 4, "guard": false, "combat": 2, "gold": 0, "health": 0}
	])
	player.deck.discard_card(recovered)

	var recover_card := _make_action("Recover", 5, [
		{"id": "recover_discard_to_topdeck", "champion_only": true, "value": 1}
	])
	player.hand.append(recover_card)
	var draw_before: int = player.deck.draw_count()
	_assert_true(player.play_card(recover_card, target), "recover: action played")
	_assert_equal(player.deck.draw_count(), draw_before + 1, "recover: champion moved to topdeck")


func test_elven_gift_parses_draw_then_discard() -> void:
	var entry: Dictionary = _find_market_entry("Elven Gift")
	var card: Card = GameState.create_market_card_from_entry(entry)
	_assert_true(card is DataCard, "elven gift: parsed as data card")
	var effects: Array[Dictionary] = (card as DataCard).effects
	var has_draw_then_discard: bool = false
	for effect: Dictionary in effects:
		if String(effect.get("id", "")) == "draw_then_discard":
			has_draw_then_discard = true
			break
	_assert_true(has_draw_then_discard, "elven gift: has draw_then_discard effect")


func test_close_ranks_scales_with_champions() -> void:
	var player := _make_player()
	var target := _make_player()
	var champ_a := _make_champion("Champion A", 4, false, [{"id": "set_faction", "faction": "imperial"}])
	var champ_b := _make_champion("Champion B", 4, false, [{"id": "set_faction", "faction": "imperial"}])
	player.hand.append(champ_a)
	player.hand.append(champ_b)
	_assert_true(player.play_card(champ_a, target), "close ranks: first champion played")
	_assert_true(player.play_card(champ_b, target), "close ranks: second champion played")

	var entry: Dictionary = _find_market_entry("Close Ranks")
	var close_ranks: Card = GameState.create_market_card_from_entry(entry)
	player.hand.append(close_ranks)
	_assert_true(player.play_card(close_ranks, target), "close ranks: card played")
	_assert_equal(player.combat_pool, 9, "close ranks: gains 5 base + 2 per champion in play")


func test_all_market_cards_have_effects() -> void:
	for entry: Dictionary in GameState.marketplace_cards:
		var name: String = String(entry.get("name", "Unknown"))
		var card: Card = GameState.create_market_card_from_entry(entry)
		_assert_true(card != null, "parse: generated card exists for %s" % name)
		if card is DataCard:
			var data_card: DataCard = card as DataCard
			_assert_true(not data_card.effects.is_empty(), "parse: generated effects present for %s" % name)
		else:
			_assert_true(false, "parse: generated card type for %s" % name)


func _make_player() -> BattlePlayer:
	var player := BattlePlayer.new()
	player.setup_from_ids("Tester", 50, 0, GameState.starting_deck_ids)
	player.hand.clear()
	player.deck.draw_pile.clear()
	player.deck.discard_pile.clear()
	return player


func _find_market_entry(card_name: String) -> Dictionary:
	for entry: Dictionary in GameState.marketplace_cards:
		if String(entry.get("name", "")) == card_name:
			return entry.duplicate(true)
	return {}


func _make_action(card_name: String, card_cost: int, effects: Array[Dictionary]) -> DataCard:
	var card := DataCard.new()
	card.setup_from_dict({
		"name": card_name,
		"cost": card_cost,
		"type": "Action",
		"description": card_name,
		"effects": effects
	})
	return card


func _make_champion(card_name: String, defense: int, is_guard: bool, effects: Array[Dictionary]) -> DataCard:
	var with_meta: Array[Dictionary] = []
	for effect: Dictionary in effects:
		with_meta.append(effect.duplicate(true))
	var has_meta: bool = false
	for effect: Dictionary in with_meta:
		if String(effect.get("id", "")) == "champion_data":
			has_meta = true
			break
	if not has_meta:
		with_meta.append({"id": "champion_data", "defense": defense, "guard": is_guard, "combat": 0, "gold": 0, "health": 0})

	var card := DataCard.new()
	card.setup_from_dict({
		"name": card_name,
		"cost": 0,
		"type": "Champion",
		"description": card_name,
		"effects": with_meta
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
