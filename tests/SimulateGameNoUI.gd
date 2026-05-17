extends Node

const MAX_TURNS: int = 30
const CARDS_PER_TURN: int = 5
const MARKET_SIZE: int = 5
const SIM_SEEDS: Array[int] = [101, 202, 303, 404, 505]

var player: BattlePlayer
var opponent: BattlePlayer
var market_draw_pile: Array[Dictionary] = []
var market_offers: Array[Dictionary] = []
var fire_gem_count: int = 16


func _ready() -> void:
	GameState.load_databases()
	var failed: int = 0
	for sim_seed: int in SIM_SEEDS:
		seed(sim_seed)
		_setup_players()
		_setup_market()
		if not _simulate_match(sim_seed):
			failed += 1
		player.free()
		opponent.free()
	print("[SIM] Completed %d deterministic matches. Failed=%d" % [SIM_SEEDS.size(), failed])
	get_tree().quit(0 if failed == 0 else 1)


func _setup_players() -> void:
	player = BattlePlayer.new()
	opponent = BattlePlayer.new()
	add_child(player)
	add_child(opponent)
	player.setup_from_ids("Player", 50, 0, GameState.starting_deck_ids)
	opponent.setup_from_ids("Opponent", 50, 0, GameState.starting_deck_ids)


func _setup_market() -> void:
	market_draw_pile.clear()
	market_offers.clear()
	for entry: Dictionary in GameState.marketplace_cards:
		market_draw_pile.append(entry.duplicate(true))
	market_draw_pile.shuffle()
	for _i in range(MARKET_SIZE):
		market_offers.append(_draw_market_card())


func _simulate_match(sim_seed: int) -> bool:
	var player_first: bool = randf() < 0.5
	print("[SIM:%d] First player: %s" % [sim_seed, "Player" if player_first else "Opponent"])

	for turn in range(1, MAX_TURNS + 1):
		if player.current_hp <= 0 or opponent.current_hp <= 0:
			break

		if player_first:
			_run_turn(player, opponent, turn == 1, "Player", true)
			if _has_invalid_state():
				return false
			if opponent.current_hp <= 0:
				break
			_run_turn(opponent, player, turn == 1, "Opponent", false)
		else:
			_run_turn(opponent, player, turn == 1, "Opponent", true)
			if _has_invalid_state():
				return false
			if player.current_hp <= 0:
				break
			_run_turn(player, opponent, turn == 1, "Player", false)
		if _has_invalid_state():
			return false

		print("[SIM:%d] End turn %d | Player HP=%d Opponent HP=%d" % [sim_seed, turn, player.current_hp, opponent.current_hp])

	var winner: String = "Draw"
	if player.current_hp > opponent.current_hp:
		winner = "Player"
	elif opponent.current_hp > player.current_hp:
		winner = "Opponent"

	var has_winner: bool = player.current_hp <= 0 or opponent.current_hp <= 0
	if not has_winner:
		push_error("[SIM:%d] No winner after %d turns." % [sim_seed, MAX_TURNS])
		return false

	print("[SIM:%d] Match over. Winner: %s | Player HP=%d Opponent HP=%d" % [sim_seed, winner, player.current_hp, opponent.current_hp])
	return true


func _run_turn(active: BattlePlayer, other: BattlePlayer, is_first_turn: bool, label: String, is_starting_player: bool) -> void:
	var draw_count: int = 5
	if is_first_turn:
		draw_count = 3 if is_starting_player else 5

	active.start_turn(draw_count)
	active.auto_expend_all_champions()

	# Play all cards in hand in random order.
	while not active.hand.is_empty():
		var index: int = randi_range(0, active.hand.size() - 1)
		var card: Card = active.hand[index]
		active.play_card(card, other)

	# Buy cards greedily by highest affordable market cost.
	while true:
		var best_idx: int = -1
		var best_cost: int = -1

		for i in range(market_offers.size()):
			var offer: Dictionary = market_offers[i]
			if offer.is_empty():
				continue
			var cost: int = int(offer.get("cost", 99))
			if cost <= active.gold_pool and cost > best_cost:
				best_cost = cost
				best_idx = i

		if best_idx == -1:
			break

		if not active.spend_gold(best_cost):
			break

		var purchased: Card = GameState.create_market_card_from_entry(market_offers[best_idx])
		if purchased != null:
			active.receive_acquired_card(purchased)
		market_offers[best_idx] = _draw_market_card()

	# Buy fire gems with remaining gold.
	while fire_gem_count > 0 and active.gold_pool >= 2:
		if not active.spend_gold(2):
			break
		var gem: Card = GameState.create_card_from_id("fire_gem")
		if gem != null:
			active.deck.discard_card(gem)
		fire_gem_count -= 1

	# Resolve combat.
	active.resolve_combat_against(other)
	active.end_turn()


func _has_invalid_state() -> bool:
	if player.current_hp < 0 or opponent.current_hp < 0:
		push_error("[SIM] HP dropped below zero.")
		return true
	if player.gold_pool < 0 or opponent.gold_pool < 0:
		push_error("[SIM] Gold pool dropped below zero.")
		return true
	if player.combat_pool < 0 or opponent.combat_pool < 0:
		push_error("[SIM] Combat pool dropped below zero.")
		return true
	if player.has_pending_choice() or opponent.has_pending_choice():
		push_error("[SIM] No-UI simulation left a pending manual choice.")
		return true
	return false


func _draw_market_card() -> Dictionary:
	if market_draw_pile.is_empty():
		return {}
	return market_draw_pile.pop_front()
