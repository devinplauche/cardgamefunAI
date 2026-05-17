extends Control
class_name TurnManager

const CardArtLoader = preload("res://scripts/CardArtLoader.gd")

signal turn_started
signal turn_ended

@export var cards_per_turn: int = 5
@export var ai_difficulty: AIOpponent.Difficulty = AIOpponent.Difficulty.GREEDY
@export var opening_player_override: int = -1

var is_player_turn: bool = false
var player_had_first_turn: bool = false
var opponent_had_first_turn: bool = false
var player_started_match: bool = false
var player: BattlePlayer
var opponent: BattlePlayer
var ai_opponent: AIOpponent

var market_draw_pile: Array[Dictionary] = []
var market_offers: Array[Dictionary] = []
var fire_gem_count: int = 16
var sacrifice_pile: Array[Card] = []
var selected_market_index: int = -1
var selected_market_offer: Dictionary = {}
var custom_choice: Dictionary = {}

@onready var hand: Hand = %Hand
@onready var end_turn_button: Button = %EndTurnButton
@onready var end_turn_floating_button: Button = %EndTurnFloatingButton
@onready var root_margin: MarginContainer = $Margin
@onready var player_stats_panel: VBoxContainer = %PlayerStats
@onready var bottom_panel: PanelContainer = %BottomPanel
@onready var opponent_panel: PanelContainer = $Margin/MainScroll/Layout/MidRow/LeftColumn/OpponentPanel
@onready var combat_panel: PanelContainer = $Margin/MainScroll/Layout/MidRow/LeftColumn/CombatPanel
@onready var store_panel: PanelContainer = $Margin/MainScroll/Layout/MidRow/StorePanel

@onready var player_hp_label: Label = %PlayerHpLabel
@onready var top_hud_player_hp_label: Label = %TopHudPlayerHpLabel
@onready var player_block_label: Label = %PlayerBlockLabel
@onready var player_energy_label: Label = %PlayerEnergyLabel
@onready var player_gold_label: Label = %PlayerGoldLabel
@onready var player_combat_label: Label = %PlayerCombatLabel

@onready var opponent_hp_label: Label = %OpponentHpLabel
@onready var top_hud_opponent_hp_label: Label = %TopHudOpponentHpLabel
@onready var opponent_block_label: Label = %OpponentBlockLabel
@onready var opponent_energy_label: Label = %OpponentEnergyLabel
@onready var opponent_gold_label: Label = %OpponentGoldLabel
@onready var opponent_combat_label: Label = %OpponentCombatLabel
@onready var opponent_played_cards_label: Label = %OpponentPlayedCardsLabel

@onready var battle_log_label: Label = %BattleLogLabel
@onready var view_player_discard_button: Button = %ViewPlayerDiscardButton
@onready var view_opponent_discard_button: Button = %ViewOpponentDiscardButton
@onready var attack_player_button: Button = %AttackPlayerButton
@onready var sacrifice_button: Button = %SacrificeButton
@onready var card_ability_button: Button = %CardAbilityButton
@onready var player_champion_actions: HBoxContainer = %PlayerChampionActions
@onready var opponent_champion_targets: HBoxContainer = %OpponentChampionTargets

@onready var shop_button_1: Button = %ShopCardButton1
@onready var shop_button_2: Button = %ShopCardButton2
@onready var shop_button_3: Button = %ShopCardButton3
@onready var shop_button_4: Button = %ShopCardButton4
@onready var shop_button_5: Button = %ShopCardButton5
@onready var fire_gem_button: Button = %FireGemButton

@onready var market_detail_image: TextureRect = %MarketDetailImage
@onready var market_detail_name: Label = %MarketDetailName
@onready var market_detail_faction: Label = %MarketDetailFaction
@onready var market_detail_type: Label = %MarketDetailType
@onready var market_detail_cost: Label = %MarketDetailCost
@onready var market_detail_effect: Label = %MarketDetailEffect
@onready var open_gallery_button: Button = %OpenGalleryButton
@onready var choice_overlay: Control = %ChoiceOverlay
@onready var choice_title: Label = %ChoiceTitle
@onready var choice_message: Label = %ChoiceMessage
@onready var choice_options: VBoxContainer = %ChoiceOptions
@onready var discard_overlay: Control = %DiscardOverlay
@onready var discard_title: Label = %DiscardTitle
@onready var discard_cards: VBoxContainer = %DiscardCards
@onready var close_discard_button: Button = %CloseDiscardButton

var shop_buttons: Array[Button] = []


func _ready() -> void:
	shop_buttons = [shop_button_1, shop_button_2, shop_button_3, shop_button_4, shop_button_5]
	hand.card_selected.connect(_on_card_selected)
	end_turn_button.pressed.connect(_on_end_turn_pressed)
	end_turn_floating_button.pressed.connect(_on_end_turn_pressed)
	view_player_discard_button.pressed.connect(_on_view_player_discard_pressed)
	view_opponent_discard_button.pressed.connect(_on_view_opponent_discard_pressed)
	attack_player_button.pressed.connect(_on_attack_player_pressed)
	sacrifice_button.pressed.connect(_on_sacrifice_button_pressed)
	card_ability_button.pressed.connect(_on_card_ability_button_pressed)
	fire_gem_button.pressed.connect(_on_buy_fire_gem_pressed)
	open_gallery_button.pressed.connect(_on_open_gallery_button_pressed)
	close_discard_button.pressed.connect(_on_close_discard_pressed)

	for index: int in range(shop_buttons.size()):
		var button: Button = shop_buttons[index]
		button.pressed.connect(_on_shop_button_pressed.bind(index))
		button.mouse_entered.connect(_on_shop_button_hovered.bind(index))

	randomize()
	_apply_visual_skin()
	get_viewport().size_changed.connect(_apply_responsive_layout)
	_apply_responsive_layout()

	_start_battle()


func _start_battle() -> void:
	GameState.load_databases()

	player = BattlePlayer.new()
	opponent = BattlePlayer.new()
	ai_opponent = AIOpponent.new()
	ai_opponent.difficulty = ai_difficulty

	add_child(player)
	add_child(opponent)
	add_child(ai_opponent)

	player.setup_from_ids("Player", 50, 0, GameState.starting_deck_ids)
	opponent.setup_from_ids("AI Duelist", 50, 0, GameState.starting_deck_ids)
	player.set_interaction_mode("manual")
	opponent.set_interaction_mode("auto")
	player.choice_requested.connect(_on_player_choice_requested)
	player.choice_cleared.connect(_on_player_choice_cleared)

	fire_gem_count = 16
	sacrifice_pile.clear()
	player_had_first_turn = false
	opponent_had_first_turn = false
	_build_marketplace()
	_refresh_store_ui()
	_refresh_ui()
	_refresh_hand_ui()
	end_turn_button.disabled = false

	var player_goes_first: bool = randf() < 0.5
	if opening_player_override == 0:
		player_goes_first = true
	elif opening_player_override == 1:
		player_goes_first = false
	player_started_match = player_goes_first
	if player_goes_first:
		_log("A rival deck-builder challenges you. You go first.")
		_start_player_turn()
	else:
		_log("A rival deck-builder challenges you. Opponent goes first.")
		call_deferred("_start_opponent_opening_turn")


func _start_opponent_opening_turn() -> void:
	if _is_battle_over():
		return

	await _run_ai_turn()

	if player.is_defeated():
		_on_player_defeated()
		return

	if not _is_battle_over():
		_start_player_turn()


func _start_player_turn() -> void:
	if _is_battle_over():
		return

	is_player_turn = true
	turn_started.emit()

	var draw_count: int = cards_per_turn
	if not player_had_first_turn:
		draw_count = 3 if player_started_match else cards_per_turn
		player_had_first_turn = true

	player.start_turn(draw_count)
	_refresh_hand_ui()
	_refresh_ui()
	_log("Player Main Phase: play cards, expend champions, buy cards, and attack.")


func _on_card_selected(card: Card) -> void:
	if not is_player_turn or card == null:
		return
	if player.has_pending_choice() or _has_custom_choice():
		return

	if not player.play_card(card, opponent):
		return

	_refresh_hand_ui()
	_refresh_ui()
	_log("Played %s." % card.card_name)
	_maybe_open_pending_acquire_popup()

	if opponent.is_defeated():
		_on_opponent_defeated()


func _on_end_turn_pressed() -> void:
	if not is_player_turn:
		return
	if player.has_pending_choice() or _has_custom_choice():
		_log("Resolve the current choice first.")
		return

	is_player_turn = false
	_resolve_player_combat()
	player.end_turn()
	_refresh_hand_ui()
	turn_ended.emit()
	_log("Opponent turn.")

	await _run_ai_turn()

	if player.is_defeated():
		_on_player_defeated()
		return

	if opponent.is_defeated():
		_on_opponent_defeated()
		return

	_start_player_turn()


func _run_ai_turn() -> void:
	if _is_battle_over():
		return

	turn_started.emit()
	var draw_count: int = cards_per_turn
	if not opponent_had_first_turn:
		draw_count = 3 if not player_started_match else cards_per_turn
		opponent_had_first_turn = true
	opponent.start_turn(draw_count)
	opponent.auto_expend_all_champions(player)
	_refresh_ui()

	await ai_opponent.take_turn({
		"self_player": opponent,
		"opponent_player": player,
		"turn_manager": self
	})

	_run_ai_market_phase()
	_resolve_ai_combat()

	opponent.end_turn()
	turn_ended.emit()
	_refresh_ui()

	if player.is_defeated():
		_on_player_defeated()
	else:
		_log("Opponent ends turn.")


func _on_attack_player_pressed() -> void:
	if not is_player_turn:
		return
	if player.has_pending_choice() or _has_custom_choice():
		_log("Resolve the current choice first.")
		return
	if player.combat_pool <= 0:
		return
	if opponent.has_guard_champions():
		_log("A Guard blocks direct attacks. Stun guards first.")
		return

	var amount: int = player.combat_pool
	if not player.spend_combat(amount):
		return

	opponent.receive_damage(amount)
	_refresh_ui()
	_log("You attacked opponent for %d." % amount)

	if opponent.is_defeated():
		_on_opponent_defeated()


func _on_attack_champion_pressed(index: int) -> void:
	if not is_player_turn:
		return
	if player.has_pending_choice() or _has_custom_choice():
		_log("Resolve the current choice first.")
		return
	if index < 0 or index >= opponent.champions_in_play.size():
		return

	var target: Dictionary = opponent.champions_in_play[index]
	var is_guard: bool = bool(target.get("is_guard", false))
	if opponent.has_guard_champions() and not is_guard:
		_log("A guard protects non-guard champions.")
		return

	var defense: int = int(target.get("defense", 1))
	if player.combat_pool < defense:
		_log("Not enough combat to stun %s." % String(target.get("name", "Champion")))
		return

	if not player.spend_combat(defense):
		return

	opponent.stun_champion_at(index)
	_refresh_ui()
	_log("Stunned enemy champion.")


func _on_player_champion_pressed(index: int) -> void:
	if not is_player_turn:
		return
	if player.has_pending_choice() or _has_custom_choice():
		_log("Resolve the current choice first.")
		return
	if not player.expend_champion(index, opponent):
		return

	_refresh_ui()
	_log("Used champion Expend ability.")
	_maybe_open_pending_acquire_popup()


func _on_sacrifice_button_pressed() -> void:
	if not is_player_turn:
		return
	if _has_custom_choice():
		_log("Resolve the current choice first.")
		return

	if not player.begin_sacrifice_choice(sacrifice_pile):
		_log("No valid sacrifice target in hand or discard.")
		return

	_refresh_hand_ui()
	_refresh_ui()
	if player.has_pending_choice():
		_log("Choose a card to sacrifice.")
	else:
		_log("Sacrifice ability used.")


func _on_ally_bonus_pressed(trigger_key: String) -> void:
	if not is_player_turn:
		return
	if player.activate_ally_bonus(trigger_key):
		_log("Ally bonus activated.")
	else:
		_log("Ally bonus could not be activated.")
	_refresh_ui()


func _on_card_ability_button_pressed() -> void:
	if not is_player_turn:
		return
	if _has_custom_choice():
		_log("Resolve the current choice first.")
		return
	if player.begin_ally_activation_choice():
		_refresh_ui()
	else:
		_log("No card abilities available.")


func _on_shop_button_hovered(index: int) -> void:
	_set_market_detail_by_index(index)


func _on_shop_button_pressed(index: int) -> void:
	if not is_player_turn:
		return
	if player.has_pending_choice() or _has_custom_choice():
		_log("Resolve the current choice first.")
		return
	if index < 0 or index >= market_offers.size():
		return
	if market_offers[index].is_empty():
		return

	_set_market_detail_by_index(index)

	var offer: Dictionary = market_offers[index]
	var cost: int = int(offer.get("cost", 99))
	if not player.spend_gold(cost):
		_log("Not enough Gold.")
		_refresh_store_ui()
		return

	var purchased_card: Card = GameState.create_market_card_from_entry(offer)
	if purchased_card == null:
		player.gain_gold(cost)
		_log("Purchase failed.")
		_refresh_store_ui()
		return

	player.receive_acquired_card(purchased_card)
	_replace_offer(index)
	_refresh_ui()
	_log("Bought %s for %d Gold." % [purchased_card.card_name, cost])
	_maybe_open_pending_acquire_popup()


func _on_buy_fire_gem_pressed() -> void:
	if not is_player_turn:
		return
	if player.has_pending_choice() or _has_custom_choice():
		_log("Resolve the current choice first.")
		return
	if fire_gem_count <= 0:
		return
	if not player.spend_gold(2):
		_log("Need 2 Gold for Fire Gem.")
		return

	var fire_gem: Card = GameState.create_card_from_id("fire_gem")
	if fire_gem == null:
		player.gain_gold(2)
		_log("Fire Gem card is missing from data.")
		return

	player.deck.discard_card(fire_gem)
	fire_gem_count -= 1
	_refresh_ui()
	_log("Bought Fire Gem.")


func _on_open_gallery_button_pressed() -> void:
	if selected_market_offer.is_empty():
		return

	var url: String = String(selected_market_offer.get("gallery_url", "https://www.herorealms.com/card-gallery/"))
	OS.shell_open(url)


func _on_view_player_discard_pressed() -> void:
	if player == null:
		return
	_open_discard_overlay("Your Discard Pile", player.deck.discard_pile)


func _on_view_opponent_discard_pressed() -> void:
	if opponent == null:
		return
	_open_discard_overlay("Opponent Discard Pile", opponent.deck.discard_pile)


func _on_close_discard_pressed() -> void:
	discard_overlay.visible = false


func _open_discard_overlay(title: String, cards: Array[Card]) -> void:
	discard_title.text = "%s (%d)" % [title, cards.size()]
	_clear_children(discard_cards)

	if cards.is_empty():
		var empty_label := Label.new()
		empty_label.text = "No cards in discard pile."
		empty_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
		discard_cards.add_child(empty_label)
		discard_overlay.visible = true
		return

	for i in range(cards.size() - 1, -1, -1):
		var card: Card = cards[i]
		if card == null:
			continue
		var row := HBoxContainer.new()
		row.layout_mode = 2
		row.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		row.custom_minimum_size = Vector2(0, 64)
		row.add_theme_constant_override("separation", 8)

		var image := TextureRect.new()
		image.custom_minimum_size = Vector2(42, 58)
		image.size_flags_vertical = Control.SIZE_SHRINK_CENTER
		image.expand_mode = TextureRect.EXPAND_FIT_WIDTH_PROPORTIONAL
		image.stretch_mode = TextureRect.STRETCH_KEEP_ASPECT_CENTERED
		image.texture = CardArtLoader.load_texture_for_card(card.card_name, card.image_path)
		row.add_child(image)

		var label := Label.new()
		label.size_flags_horizontal = Control.SIZE_EXPAND_FILL
		label.size_flags_vertical = Control.SIZE_SHRINK_CENTER
		label.autowrap_mode = TextServer.AUTOWRAP_WORD
		label.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
		label.text = "%d. %s [%s]" % [cards.size() - i, card.card_name, card.card_type]
		row.add_child(label)

		discard_cards.add_child(row)

	discard_overlay.visible = true


func _build_marketplace() -> void:
	market_draw_pile.clear()
	market_offers.clear()

	for entry: Dictionary in GameState.marketplace_cards:
		market_draw_pile.append(entry.duplicate(true))

	market_draw_pile.shuffle()

	for _slot in range(shop_buttons.size()):
		market_offers.append(_draw_market_card())

	_set_market_detail_by_index(0)


func _draw_market_card() -> Dictionary:
	if market_draw_pile.is_empty():
		return {}
	return market_draw_pile.pop_front()


func _replace_offer(index: int) -> void:
	if index < 0 or index >= market_offers.size():
		return

	market_offers[index] = _draw_market_card()
	if selected_market_index == index:
		_set_market_detail_by_index(index)


func _set_market_detail_by_index(index: int) -> void:
	if index < 0 or index >= market_offers.size() or market_offers[index].is_empty():
		selected_market_index = -1
		selected_market_offer = {}
		market_detail_name.text = "No Market Card"
		market_detail_faction.text = "Faction: -"
		market_detail_type.text = "Type: -"
		market_detail_cost.text = "Cost: -"
		market_detail_effect.text = "Hover a market card to see details."
		market_detail_image.texture = null
		return

	selected_market_index = index
	selected_market_offer = market_offers[index].duplicate(true)

	market_detail_name.text = String(selected_market_offer.get("name", "Card"))
	market_detail_faction.text = "Faction: %s" % String(selected_market_offer.get("faction", "neutral")).capitalize()
	market_detail_type.text = "Type: %s" % String(selected_market_offer.get("type", "Action"))
	market_detail_cost.text = "Cost: %d" % int(selected_market_offer.get("cost", 0))
	market_detail_effect.text = "Effect: %s" % String(selected_market_offer.get("effect", ""))
	market_detail_image.texture = _load_market_card_texture(String(selected_market_offer.get("name", "")))


func _load_market_card_texture(card_name: String) -> Texture2D:
	var direct_path: String = String(selected_market_offer.get("image_path", ""))
	return CardArtLoader.load_texture_for_card(card_name, direct_path)


func _refresh_ui() -> void:
	player_hp_label.text = "Player HP: %d / %d" % [player.current_hp, player.max_hp]
	top_hud_player_hp_label.text = player_hp_label.text
	player_block_label.text = "Player Block: %d" % player.current_block
	player_energy_label.text = "Player Deck: %d draw / %d discard" % [player.deck.draw_count(), player.deck.discard_count()]
	player_gold_label.text = "Player Gold Pool: %d" % player.gold_pool
	player_combat_label.text = "Player Combat Pool: %d" % player.combat_pool

	opponent_hp_label.text = "Opponent HP: %d / %d" % [opponent.current_hp, opponent.max_hp]
	top_hud_opponent_hp_label.text = opponent_hp_label.text
	opponent_block_label.text = "Opponent Block: %d" % opponent.current_block
	opponent_energy_label.text = "Opponent Deck: %d draw / %d discard" % [opponent.deck.draw_count(), opponent.deck.discard_count()]
	opponent_gold_label.text = "Opponent Gold Pool: %d" % opponent.gold_pool
	opponent_combat_label.text = "Opponent Combat Pool: %d" % opponent.combat_pool

	var played_text: String = "None"
	if not opponent.played_cards_this_turn.is_empty():
		played_text = ", ".join(opponent.played_cards_this_turn)
	opponent_played_cards_label.text = "Opponent Played: %s" % played_text

	_refresh_store_ui()
	_refresh_champion_ui()
	_refresh_action_buttons()
	_refresh_choice_gate_state()
	end_turn_floating_button.disabled = end_turn_button.disabled


func _refresh_hand_ui() -> void:
	hand.set_cards(player.hand)


func _refresh_store_ui() -> void:
	for index: int in range(shop_buttons.size()):
		var button: Button = shop_buttons[index]
		if index >= market_offers.size() or market_offers[index].is_empty():
			button.text = "Sold Out"
			button.disabled = true
			continue

		var offer: Dictionary = market_offers[index]
		var cost: int = int(offer.get("cost", 99))
		var card_name: String = String(offer.get("name", "Unknown"))
		var faction: String = String(offer.get("faction", "neutral"))
		var short_name: String = card_name
		if short_name.length() > 20:
			short_name = short_name.substr(0, 20) + "..."
		button.text = "%s [%s] (%d)" % [short_name, faction.capitalize(), cost]
		button.tooltip_text = "%s [%s] (%d Gold)" % [card_name, faction.capitalize(), cost]
		button.disabled = (not is_player_turn) or player.gold_pool < cost

	fire_gem_button.text = "Buy Fire Gem (2 Gold) x%d" % fire_gem_count
	fire_gem_button.disabled = (not is_player_turn) or fire_gem_count <= 0 or player.gold_pool < 2


func _refresh_champion_ui() -> void:
	_clear_children(player_champion_actions)
	_clear_children(opponent_champion_targets)

	var player_summaries: Array[Dictionary] = player.get_champion_summaries()
	for summary: Dictionary in player_summaries:
		var idx: int = int(summary.get("index", 0))
		var action_button := Button.new()
		var champion_name: String = String(summary.get("name", "Champion"))
		var is_prepared: bool = bool(summary.get("prepared", false))
		action_button.text = "%s\n%s" % [champion_name, "Ready" if is_prepared else "Expended"]
		action_button.custom_minimum_size = Vector2(108, 98)
		action_button.tooltip_text = champion_name
		var image_path: String = String(summary.get("image_path", ""))
		var portrait: Texture2D = CardArtLoader.load_texture_for_card(champion_name, image_path)
		if portrait != null:
			action_button.icon = portrait
			action_button.expand_icon = true
			action_button.icon_alignment = HORIZONTAL_ALIGNMENT_CENTER
		if not is_prepared:
			action_button.rotation_degrees = 90.0
			action_button.modulate = Color(0.80, 0.80, 0.88, 0.92)
		action_button.disabled = (not is_player_turn) or not bool(summary.get("prepared", false))
		action_button.pressed.connect(_on_player_champion_pressed.bind(idx))
		_apply_button_style(action_button, _make_button_style(Color(0.16, 0.19, 0.29, 0.96), Color(0.50, 0.62, 0.86, 0.42)))
		player_champion_actions.add_child(action_button)

	var opponent_summaries: Array[Dictionary] = opponent.get_champion_summaries()
	for summary: Dictionary in opponent_summaries:
		var idx: int = int(summary.get("index", 0))
		var target_button := Button.new()
		var champion_name: String = String(summary.get("name", "Champion"))
		var is_prepared: bool = bool(summary.get("prepared", false))
		var guard_text: String = " Guard" if bool(summary.get("is_guard", false)) else ""
		target_button.text = "%s\n%d%s | %s" % [champion_name, int(summary.get("defense", 0)), guard_text, "Ready" if is_prepared else "Expended"]
		target_button.custom_minimum_size = Vector2(108, 98)
		target_button.tooltip_text = champion_name
		var image_path: String = String(summary.get("image_path", ""))
		var portrait: Texture2D = CardArtLoader.load_texture_for_card(champion_name, image_path)
		if portrait != null:
			target_button.icon = portrait
			target_button.expand_icon = true
			target_button.icon_alignment = HORIZONTAL_ALIGNMENT_CENTER
		if not is_prepared:
			target_button.modulate = Color(0.84, 0.84, 0.92, 0.92)
		target_button.disabled = (not is_player_turn) or player.combat_pool <= 0
		target_button.pressed.connect(_on_attack_champion_pressed.bind(idx))
		_apply_button_style(target_button, _make_button_style(Color(0.20, 0.16, 0.22, 0.96), Color(0.78, 0.55, 0.55, 0.40)))
		opponent_champion_targets.add_child(target_button)


func _refresh_action_buttons() -> void:
	sacrifice_button.disabled = (not is_player_turn) or not player.has_pending_sacrifice_offer()
	sacrifice_button.text = player.get_pending_sacrifice_label()
	attack_player_button.disabled = (not is_player_turn) or player.combat_pool <= 0 or opponent.has_guard_champions()
	var pending_count: int = player.get_pending_ally_activations().size()
	card_ability_button.disabled = (not is_player_turn) or pending_count == 0
	card_ability_button.text = "Card Abilities (%d)" % pending_count if pending_count > 0 else "Card Abilities"


func _clear_children(container: Node) -> void:
	for child: Node in container.get_children():
		child.queue_free()


func _resolve_player_combat() -> void:
	if player.combat_pool <= 0:
		return

	var before_hp: int = opponent.current_hp
	var dealt: int = player.resolve_combat_against(opponent)
	var blocked_by_guards: bool = before_hp == opponent.current_hp and dealt == 0

	if blocked_by_guards:
		_log("Player combat was absorbed by guards.")
	elif dealt > 0:
		_log("Player attacks for %d combat." % dealt)


func _resolve_ai_combat() -> void:
	if opponent.combat_pool <= 0:
		return

	var before_hp: int = player.current_hp
	var dealt: int = opponent.resolve_combat_against(player)
	var blocked_by_guards: bool = before_hp == player.current_hp and dealt == 0

	if blocked_by_guards:
		_log("Opponent combat was absorbed by guards.")
	elif dealt > 0:
		_log("Opponent attacks for %d combat." % dealt)


func _run_ai_market_phase() -> void:
	while true:
		var best_index: int = -1
		var best_cost: int = -1

		for index: int in range(market_offers.size()):
			var offer: Dictionary = market_offers[index]
			if offer.is_empty():
				continue
			var cost: int = int(offer.get("cost", 99))
			if cost <= opponent.gold_pool and cost > best_cost:
				best_cost = cost
				best_index = index

		if best_index == -1:
			break

		var offer_to_buy: Dictionary = market_offers[best_index]
		var buy_cost: int = int(offer_to_buy.get("cost", 99))
		if not opponent.spend_gold(buy_cost):
			break

		var purchased_card: Card = GameState.create_market_card_from_entry(offer_to_buy)
		if purchased_card == null:
			opponent.gain_gold(buy_cost)
			break

		opponent.receive_acquired_card(purchased_card)
		_replace_offer(best_index)

	# Fire Gem is always available, so AI may buy those too.
	while fire_gem_count > 0 and opponent.gold_pool >= 2:
		if not opponent.spend_gold(2):
			break
		var fire_gem: Card = GameState.create_card_from_id("fire_gem")
		if fire_gem == null:
			opponent.gain_gold(2)
			break
		opponent.deck.discard_card(fire_gem)
		fire_gem_count -= 1


func _on_opponent_defeated() -> void:
	if not opponent.is_defeated():
		return

	is_player_turn = false
	end_turn_button.disabled = true
	end_turn_floating_button.disabled = true
	_refresh_hand_ui()
	_log("Battle won. You defeated the rival deck-builder.")


func _on_player_defeated() -> void:
	is_player_turn = false
	end_turn_button.disabled = true
	end_turn_floating_button.disabled = true
	_refresh_hand_ui()
	_log("Battle lost. Your rival outplayed you.")


func _is_battle_over() -> bool:
	return player == null or opponent == null or player.is_defeated() or opponent.is_defeated()


func _log(message: String) -> void:
	battle_log_label.text = message


func _apply_visual_skin() -> void:
	opponent_panel.add_theme_stylebox_override("panel", _make_panel_style(Color(0.08, 0.23, 0.24, 0.92), Color(0.38, 0.77, 0.74, 0.35)))
	combat_panel.add_theme_stylebox_override("panel", _make_panel_style(Color(0.17, 0.14, 0.26, 0.92), Color(0.67, 0.52, 0.94, 0.22)))
	store_panel.add_theme_stylebox_override("panel", _make_panel_style(Color(0.28, 0.18, 0.08, 0.92), Color(0.95, 0.67, 0.29, 0.35)))
	bottom_panel.add_theme_stylebox_override("panel", _make_panel_style(Color(0.12, 0.16, 0.24, 0.94), Color(0.33, 0.55, 0.88, 0.20)))

	var primary_button_style: StyleBoxFlat = _make_button_style(Color(0.14, 0.22, 0.34, 0.96), Color(0.35, 0.64, 0.95, 0.45))
	var action_button_style: StyleBoxFlat = _make_button_style(Color(0.18, 0.26, 0.18, 0.96), Color(0.43, 0.85, 0.54, 0.42))
	var store_button_style: StyleBoxFlat = _make_button_style(Color(0.35, 0.24, 0.10, 0.96), Color(0.92, 0.70, 0.29, 0.45))

	_apply_button_style(end_turn_button, primary_button_style)
	_apply_button_style(end_turn_floating_button, primary_button_style)
	_apply_button_style(view_player_discard_button, primary_button_style)
	_apply_button_style(view_opponent_discard_button, primary_button_style)
	_apply_button_style(attack_player_button, action_button_style)
	_apply_button_style(sacrifice_button, action_button_style)
	_apply_button_style(card_ability_button, action_button_style)
	_apply_button_style(fire_gem_button, store_button_style)
	_apply_button_style(open_gallery_button, primary_button_style)
	_apply_button_style(close_discard_button, primary_button_style)
	for button: Button in shop_buttons:
		_apply_button_style(button, store_button_style)

	battle_log_label.modulate = Color(1.0, 0.95, 0.84, 1.0)
	market_detail_name.modulate = Color(1.0, 0.93, 0.70, 1.0)
	market_detail_effect.modulate = Color(0.94, 0.94, 0.98, 1.0)


func _make_panel_style(fill: Color, border: Color) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = fill
	style.border_color = border
	style.border_width_left = 2
	style.border_width_top = 2
	style.border_width_right = 2
	style.border_width_bottom = 2
	style.corner_radius_top_left = 18
	style.corner_radius_top_right = 18
	style.corner_radius_bottom_left = 18
	style.corner_radius_bottom_right = 18
	style.shadow_color = Color(0, 0, 0, 0.28)
	style.shadow_size = 10
	return style


func _make_button_style(fill: Color, border: Color) -> StyleBoxFlat:
	var style := StyleBoxFlat.new()
	style.bg_color = fill
	style.border_color = border
	style.border_width_left = 1
	style.border_width_top = 1
	style.border_width_right = 1
	style.border_width_bottom = 1
	style.corner_radius_top_left = 10
	style.corner_radius_top_right = 10
	style.corner_radius_bottom_left = 10
	style.corner_radius_bottom_right = 10
	return style


func _apply_button_style(button: Button, base_style: StyleBoxFlat) -> void:
	if button == null:
		return
	button.add_theme_stylebox_override("normal", base_style)
	var hover_style: StyleBoxFlat = base_style.duplicate()
	hover_style.bg_color = base_style.bg_color.lightened(0.08)
	button.add_theme_stylebox_override("hover", hover_style)
	var pressed_style: StyleBoxFlat = base_style.duplicate()
	pressed_style.bg_color = base_style.bg_color.darkened(0.10)
	button.add_theme_stylebox_override("pressed", pressed_style)


func _on_player_choice_requested(choice: Dictionary) -> void:
	choice_overlay.visible = true
	choice_title.text = String(choice.get("title", "Choose"))
	choice_message.text = String(choice.get("message", "Make a selection."))
	_clear_children(choice_options)
	var options: Array = choice.get("options", [])
	for index: int in range(options.size()):
		var option: Dictionary = options[index]
		var button := Button.new()
		button.text = String(option.get("label", "Option"))
		_apply_button_style(button, _make_button_style(Color(0.20, 0.18, 0.34, 0.98), Color(0.73, 0.58, 0.97, 0.40)))
		button.pressed.connect(_on_choice_option_pressed.bind(index))
		choice_options.add_child(button)
	_refresh_choice_gate_state()


func _on_player_choice_cleared() -> void:
	if not _has_custom_choice():
		choice_overlay.visible = false
		_clear_children(choice_options)
	_refresh_hand_ui()
	_refresh_ui()


func _on_choice_option_pressed(index: int) -> void:
	if player == null:
		return
	if not player.resolve_pending_choice(index):
		return
	if player.has_pending_choice():
		_on_player_choice_requested(player.pending_choice)
	else:
		_log("Choice resolved.")
		_maybe_open_pending_acquire_popup()


func _has_custom_choice() -> bool:
	return not custom_choice.is_empty()


func _open_custom_choice(choice: Dictionary) -> void:
	custom_choice = choice.duplicate(true)
	choice_overlay.visible = true
	choice_title.text = String(custom_choice.get("title", "Choose"))
	choice_message.text = String(custom_choice.get("message", "Make a selection."))
	_clear_children(choice_options)
	var options: Array = custom_choice.get("options", [])
	for index: int in range(options.size()):
		var option: Dictionary = options[index]
		var button := Button.new()
		button.text = String(option.get("label", "Option"))
		_apply_button_style(button, _make_button_style(Color(0.29, 0.20, 0.15, 0.98), Color(0.95, 0.72, 0.40, 0.40)))
		button.pressed.connect(_on_custom_choice_option_pressed.bind(index))
		choice_options.add_child(button)
	_refresh_choice_gate_state()


func _clear_custom_choice() -> void:
	custom_choice.clear()
	if not player.has_pending_choice():
		choice_overlay.visible = false
		_clear_children(choice_options)
	_refresh_hand_ui()
	_refresh_ui()


func _on_custom_choice_option_pressed(index: int) -> void:
	if index < 0:
		return
	var options: Array = custom_choice.get("options", [])
	if index >= options.size():
		return
	var option: Dictionary = options[index]
	if bool(option.get("skip", false)):
		_clear_custom_choice()
		_log("Skipped acquire popup.")
		return

	var market_index: int = int(option.get("market_index", -1))
	if market_index < 0 or market_index >= market_offers.size() or market_offers[market_index].is_empty():
		_clear_custom_choice()
		_log("That market card is no longer available.")
		return

	var offer: Dictionary = market_offers[market_index]
	var cost: int = int(offer.get("cost", 99))
	if not player.spend_gold(cost):
		_clear_custom_choice()
		_log("Not enough Gold for that acquire.")
		return

	var purchased_card: Card = GameState.create_market_card_from_entry(offer)
	if purchased_card == null:
		player.gain_gold(cost)
		_clear_custom_choice()
		_log("Acquire failed.")
		return

	player.receive_acquired_card(purchased_card)
	_replace_offer(market_index)
	_clear_custom_choice()
	_log("Acquired %s for %d Gold." % [purchased_card.card_name, cost])
	_maybe_open_pending_acquire_popup()


func _maybe_open_pending_acquire_popup() -> void:
	if not is_player_turn:
		return
	if player == null:
		return
	if player.has_pending_choice() or _has_custom_choice():
		return

	var mode: String = ""
	if player.pending_acquire_to_hand_any > 0:
		mode = "hand_any"
	elif player.pending_acquire_to_topdeck_any > 0:
		mode = "topdeck_any"
	elif player.pending_acquire_to_topdeck_actions > 0:
		mode = "topdeck_action"

	if mode.is_empty():
		return

	var options: Array[Dictionary] = []
	for i in range(market_offers.size()):
		var offer: Dictionary = market_offers[i]
		if offer.is_empty():
			continue
		var cost: int = int(offer.get("cost", 99))
		if cost > player.gold_pool:
			continue
		if mode == "topdeck_action":
			var type_text: String = String(offer.get("type", "")).to_lower()
			if not type_text.contains("action"):
				continue
		var card_name: String = String(offer.get("name", "Unknown"))
		options.append({
			"label": "%s (%d Gold)" % [card_name, cost],
			"market_index": i
		})

	if options.is_empty():
		return

	options.append({"label": "Skip", "skip": true})
	var title: String = "Choose A Card To Acquire"
	var message: String = "Pick a market card for your pending acquire effect."
	if mode == "hand_any":
		title = "Deception: Acquire Into Hand"
		message = "Choose the next card to acquire into your hand."
	elif mode == "topdeck_action":
		title = "Bribe: Acquire Action To Top Deck"
		message = "Choose an action card to acquire onto your deck."
	elif mode == "topdeck_any":
		title = "Acquire Card To Top Deck"
		message = "Choose the next card to acquire onto your deck."

	_open_custom_choice({
		"type": "market_acquire",
		"mode": mode,
		"title": title,
		"message": message,
		"options": options
	})


func _refresh_choice_gate_state() -> void:
	var choice_open: bool = (player != null and player.has_pending_choice()) or _has_custom_choice()
	hand.mouse_filter = Control.MOUSE_FILTER_IGNORE if choice_open else Control.MOUSE_FILTER_PASS
	if choice_open:
		end_turn_button.disabled = true
		end_turn_floating_button.disabled = true
		view_player_discard_button.disabled = true
		view_opponent_discard_button.disabled = true
		attack_player_button.disabled = true
		sacrifice_button.disabled = true
		card_ability_button.disabled = true
		for button: Button in shop_buttons:
			button.disabled = true
		fire_gem_button.disabled = true
	else:
		end_turn_button.disabled = not is_player_turn
		_refresh_store_ui()
		_refresh_action_buttons()
		view_player_discard_button.disabled = false
		view_opponent_discard_button.disabled = false
		end_turn_floating_button.disabled = end_turn_button.disabled


func _apply_responsive_layout() -> void:
	var viewport_size: Vector2 = get_viewport_rect().size
	var h: float = viewport_size.y
	var w: float = viewport_size.x
	var compact_top_bar: bool = w < 1360.0

	hand.scale = Vector2.ONE
	end_turn_floating_button.visible = false
	player_stats_panel.visible = not compact_top_bar
	top_hud_player_hp_label.visible = compact_top_bar
	top_hud_opponent_hp_label.visible = compact_top_bar
	battle_log_label.visible = not compact_top_bar
	view_player_discard_button.text = "Discard" if compact_top_bar else "Your Discard"
	view_opponent_discard_button.text = "Opp Discard" if compact_top_bar else "Opponent Discard"

	if h < 700.0 or w < 1220.0:
		root_margin.add_theme_constant_override("margin_top", 34)
		root_margin.add_theme_constant_override("margin_bottom", 4)
		bottom_panel.custom_minimum_size = Vector2(0, 110)
		market_detail_image.custom_minimum_size = Vector2(66, 88)
		hand.scale = Vector2(0.76, 0.76)
	elif h < 860.0:
		root_margin.add_theme_constant_override("margin_top", 36)
		root_margin.add_theme_constant_override("margin_bottom", 8)
		bottom_panel.custom_minimum_size = Vector2(0, 138)
		market_detail_image.custom_minimum_size = Vector2(76, 102)
		hand.scale = Vector2(0.84, 0.84)
	else:
		root_margin.add_theme_constant_override("margin_top", 36)
		root_margin.add_theme_constant_override("margin_bottom", 10)
		bottom_panel.custom_minimum_size = Vector2(0, 156)
		market_detail_image.custom_minimum_size = Vector2(84, 112)
		hand.scale = Vector2(0.9, 0.9)
