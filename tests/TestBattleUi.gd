extends Node

const BATTLE_SCENE := preload("res://ui/BattleScene.tscn")
const CARD_SCENE := preload("res://ui/Card.tscn")

var _failed: int = 0
var _passed: int = 0


func _ready() -> void:
	GameState.load_databases()
	await run_all()
	print("[UI-TEST] Completed %d tests. Passed=%d Failed=%d" % [_passed + _failed, _passed, _failed])
	get_tree().quit(0 if _failed == 0 else 1)


func run_all() -> void:
	test_project_uses_predictable_window_scaling()
	await test_card_view_uses_compact_layout()
	await test_opponent_champion_buttons_show_portraits_and_state()
	await test_discard_overlay_builds_stable_rows()
	await test_turn_manager_resolves_manual_discard_choice()
	await test_market_acquire_popup_for_pending_ability()
	await test_starting_player_opens_with_three_cards()
	await test_second_player_opens_with_five_cards()


func test_project_uses_predictable_window_scaling() -> void:
	_assert_equal(ProjectSettings.get_setting("display/window/size/mode"), 0, "window sizing: starts windowed")
	_assert_equal(ProjectSettings.get_setting("display/window/stretch/scale"), 1.0, "window sizing: uses native viewport scale")
	_assert_equal(ProjectSettings.get_setting("display/window/stretch/scale_mode"), "fractional", "window sizing: allows fractional responsive scaling")


func test_card_view_uses_compact_layout() -> void:
	var card_view: CardView = CARD_SCENE.instantiate()
	add_child(card_view)
	card_view.set_card_data(_make_action("Word of Power", 6, [{"id": "gain_combat", "value": 5}]))
	await get_tree().process_frame
	var name_label: Label = card_view.get_node("Margin/Content/NameLabel")
	var type_label: Label = card_view.get_node("Margin/Content/Header/TypeLabel")
	var description_label: Label = card_view.get_node("Margin/Content/DescriptionLabel")
	_assert_equal(card_view.size_flags_horizontal, 0, "card layout: card does not horizontally expand")
	_assert_true(not name_label.visible, "card layout: name text hidden")
	_assert_true(not type_label.visible, "card layout: type text hidden")
	_assert_true(not description_label.visible, "card layout: description text hidden")
	card_view.queue_free()
	await get_tree().process_frame


func test_opponent_champion_buttons_show_portraits_and_state() -> void:
	var scene: TurnManager = _instantiate_battle_scene()
	add_child(scene)
	await get_tree().process_frame
	scene.opponent.hand.clear()
	scene.opponent.deck.draw_pile.clear()
	scene.opponent.deck.discard_pile.clear()
	scene.opponent.champions_in_play.clear()
	var champion := _make_champion("Enemy Champion")
	scene.opponent.hand.append(champion)
	_assert_true(scene.opponent.play_card(champion, scene.player), "opponent champion ui: champion plays")
	_assert_true(scene.opponent.expend_champion(0), "opponent champion ui: champion expends")
	scene._refresh_champion_ui()
	await get_tree().process_frame
	var button := scene.opponent_champion_targets.get_child(0) as Button
	_assert_true(button != null, "opponent champion ui: button exists")
	_assert_true(button.icon != null, "opponent champion ui: portrait is shown")
	_assert_true(button.text.contains("Expended"), "opponent champion ui: expended state is shown")
	scene.queue_free()
	await get_tree().process_frame


func test_discard_overlay_builds_stable_rows() -> void:
	var scene: TurnManager = _instantiate_battle_scene()
	add_child(scene)
	await get_tree().process_frame
	scene.player.deck.discard_pile.clear()
	scene.player.deck.discard_pile.append(_make_action("Gold", 0, [{"id": "gain_gold", "value": 1}]))
	scene.player.deck.discard_pile.append(_make_action("Master Weyan", 4, [{"id": "gain_combat", "value": 3}]))
	scene._open_discard_overlay("Your Discard Pile", scene.player.deck.discard_pile)
	await get_tree().process_frame
	_assert_equal(scene.discard_cards.get_child_count(), 2, "discard overlay: one row per card")
	var first_row := scene.discard_cards.get_child(0) as Control
	_assert_true(first_row != null, "discard overlay: row exists")
	_assert_true(first_row.custom_minimum_size.y >= 64.0, "discard overlay: row has stable minimum height")
	_assert_true(first_row.get_child_count() >= 2, "discard overlay: row includes image and text")
	scene.queue_free()
	await get_tree().process_frame


func test_turn_manager_resolves_manual_discard_choice() -> void:
	var scene: TurnManager = _instantiate_battle_scene()
	add_child(scene)
	await get_tree().process_frame
	scene.player.set_interaction_mode("manual")
	scene.player.hand.clear()
	scene.player.deck.draw_pile.clear()
	scene.player.deck.discard_pile.clear()
	scene.player.hand.append(_make_action("Weak", 0, []))
	scene.player.hand.append(_make_action("Rampage", 0, [{"id": "draw_up_to_then_discard", "max_draw": 1, "value": 1}]))
	scene.player.deck.draw_pile.append(_make_action("Drawn", 0, []))
	var rampage: Card = scene.player.hand[1]
	_assert_true(scene.player.play_card(rampage, scene.opponent), "turn manager choice: rampage plays")
	scene._refresh_hand_ui()
	scene._refresh_ui()
	await get_tree().process_frame
	_assert_true(scene.choice_overlay.visible, "turn manager choice: overlay shown")
	scene._on_choice_option_pressed(0)
	await get_tree().process_frame
	_assert_true(not scene.player.has_pending_choice(), "turn manager choice: click resolves pending choice")
	scene.queue_free()
	await get_tree().process_frame


func test_market_acquire_popup_for_pending_ability() -> void:
	var scene: TurnManager = _instantiate_battle_scene()
	add_child(scene)
	await get_tree().process_frame
	scene.is_player_turn = true
	scene.player.gold_pool = 5
	scene.player.pending_acquire_to_topdeck_actions = 1
	scene.market_offers = [
		{"name": "Action Pick", "faction": "guild", "type": "Action", "cost": 3, "effect": "", "image_path": ""},
		{"name": "Champion Skip", "faction": "imperial", "type": "Champion", "cost": 4, "effect": "", "image_path": ""}
	]
	scene._maybe_open_pending_acquire_popup()
	await get_tree().process_frame
	_assert_true(scene.choice_overlay.visible, "acquire popup: overlay visible")
	_assert_true(scene.choice_title.text.contains("Bribe"), "acquire popup: title indicates Bribe flow")
	_assert_true(scene.choice_options.get_child_count() >= 2, "acquire popup: has market option plus skip")
	scene.queue_free()
	await get_tree().process_frame


func test_starting_player_opens_with_three_cards() -> void:
	var scene: TurnManager = _instantiate_battle_scene()
	add_child(scene)
	await get_tree().process_frame
	scene.player.hand.clear()
	scene.player.deck.draw_pile.clear()
	scene.player.deck.discard_pile.clear()
	for i in range(6):
		scene.player.deck.draw_pile.append(_make_action("Seed %d" % i, 0, []))
	scene.player_started_match = true
	scene.player_had_first_turn = false
	scene.is_player_turn = false
	scene._start_player_turn()
	await get_tree().process_frame
	_assert_equal(scene.player.hand.size(), 3, "opening hand: starting player draws 3")
	scene.queue_free()
	await get_tree().process_frame


func test_second_player_opens_with_five_cards() -> void:
	var scene: TurnManager = _instantiate_battle_scene()
	add_child(scene)
	await get_tree().process_frame
	scene.player.hand.clear()
	scene.player.deck.draw_pile.clear()
	scene.player.deck.discard_pile.clear()
	for i in range(6):
		scene.player.deck.draw_pile.append(_make_action("Seed %d" % i, 0, []))
	scene.player_started_match = false
	scene.player_had_first_turn = false
	scene.is_player_turn = false
	scene._start_player_turn()
	await get_tree().process_frame
	_assert_equal(scene.player.hand.size(), 5, "opening hand: second player draws 5")
	scene.queue_free()
	await get_tree().process_frame


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


func _instantiate_battle_scene() -> TurnManager:
	var scene: TurnManager = BATTLE_SCENE.instantiate()
	scene.opening_player_override = 0
	return scene


func _make_champion(card_name: String) -> DataCard:
	var card := DataCard.new()
	card.setup_from_dict({
		"name": card_name,
		"cost": 4,
		"type": "Champion",
		"description": card_name,
		"effects": [
			{"id": "gain_combat", "value": 3},
			{"id": "champion_data", "defense": 4, "guard": false, "combat": 3}
		]
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
