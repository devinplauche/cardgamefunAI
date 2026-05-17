extends AIController
class_name AIOpponent

enum Difficulty {
	RANDOM,
	GREEDY,
	LOOKAHEAD,
	# Single-axis strategies useful as baselines in benchmarks.
	AGGRO,    # Always prefer highest-damage cards; buy combat-heavy market offers.
	ECON,     # Always prefer highest-resource cards; buy by highest gold cost.
	CONTROL,  # Always prefer highest-disruption cards; buy disruptive market offers.
}

@export var difficulty: Difficulty = Difficulty.GREEDY
@export_range(1, 2, 1) var lookahead_depth: int = 2
@export var fog_of_war: bool = false

var evaluator: CardEvaluator = CardEvaluator.new()


func take_turn(context: Dictionary) -> void:
	turn_started.emit()

	var self_player: Node = context.get("self_player", null)
	var opponent_player: Node = context.get("opponent_player", null)

	if self_player == null or opponent_player == null:
		push_warning("AIOpponent.take_turn missing self_player or opponent_player in context.")
		turn_ended.emit()
		return

	# Play cards until no legal plays remain, with small delays between actions.
	while true:
		var hand: Array[Card] = _get_hand(self_player)
		if hand.is_empty():
			break

		var playable_cards: Array[Card] = _get_playable_cards(hand, _get_mana(self_player))
		if playable_cards.is_empty():
			break

		var chosen_card: Card = _choose_card(playable_cards, self_player, opponent_player)
		if chosen_card == null:
			break

		await wait_human_delay(0.5, 1.5)

		# Keep this call aligned with the existing project contract.
		# Expected signature: play_card(card, target) -> bool
		var played: bool = _play_card(self_player, chosen_card, opponent_player)
		if not played:
			# Prevent infinite loops if the host rejects the chosen card.
			break

	# Tiny post-turn pause to feel less robotic.
	await wait_human_delay(0.35, 0.65)
	turn_ended.emit()


func _choose_card(playable_cards: Array[Card], self_player: Node, opponent_player: Node) -> Card:
	match difficulty:
		Difficulty.RANDOM:
			return _choose_random(playable_cards)
		Difficulty.GREEDY:
			return _choose_greedy(playable_cards, self_player, opponent_player)
		Difficulty.LOOKAHEAD:
			return _choose_lookahead(playable_cards, self_player, opponent_player)
		Difficulty.AGGRO:
			return _choose_aggro(playable_cards, self_player)
		Difficulty.ECON:
			return _choose_econ(playable_cards, self_player)
		Difficulty.CONTROL:
			return _choose_control(playable_cards, self_player)
		_:
			return _choose_random(playable_cards)


func _choose_random(playable_cards: Array[Card]) -> Card:
	if playable_cards.is_empty():
		return null

	var random_index: int = randi_range(0, playable_cards.size() - 1)
	return playable_cards[random_index]


func _choose_greedy(playable_cards: Array[Card], self_player: Node, opponent_player: Node) -> Card:
	var context: Dictionary = _build_eval_context(self_player, opponent_player)
	var best_score: float = -1.0
	var best_card: Card = null

	for card: Card in playable_cards:
		var score: float = evaluator.score_card(card, context)
		if score > best_score:
			best_score = score
			best_card = card

	return best_card


func _choose_lookahead(playable_cards: Array[Card], self_player: Node, opponent_player: Node) -> Card:
	var root_context: Dictionary = _build_eval_context(self_player, opponent_player)
	var depth: int = clamp(lookahead_depth, 1, 2)

	var best_card: Card = null
	var best_score: float = -1.0

	for first_card: Card in playable_cards:
		var context_after_first: Dictionary = root_context.duplicate(true)
		evaluator._apply_card_to_sim_state(first_card, context_after_first)

		var sequence_score: float = evaluator.score_card(first_card, root_context)

		if depth > 1:
			# Simulate a simple next-turn planning step by evaluating the best
			# follow-up from remaining currently known cards.
			var remaining: Array[Card] = _without_card(playable_cards, first_card)
			context_after_first["ai_mana"] = int(root_context.get("ai_max_mana", context_after_first.get("ai_mana", 0)))
			var follow_up: float = _best_future_score(remaining, context_after_first)
			sequence_score = clamp(sequence_score * 0.65 + follow_up * 0.35, 0.0, 1.0)

		if sequence_score > best_score:
			best_score = sequence_score
			best_card = first_card

	return best_card


func _best_future_score(cards: Array[Card], context: Dictionary) -> float:
	if cards.is_empty():
		return 0.0

	var best: float = 0.0
	var mana: int = int(context.get("ai_mana", 0))
	for card: Card in cards:
		if card.cost > mana:
			continue
		best = max(best, evaluator.score_card(card, context))

	return best


func _choose_aggro(playable_cards: Array[Card], self_player: Node) -> Card:
	var ai_champions: int = _get_champion_count(self_player)
	var best_card: Card = null
	var best_value: int = -1
	for card: Card in playable_cards:
		var vals: Dictionary = evaluator.estimate_card_values(card, ai_champions)
		var value: int = int(vals.get("damage", 0))
		if value > best_value:
			best_value = value
			best_card = card
	return best_card if best_card != null else _choose_random(playable_cards)


func _choose_econ(playable_cards: Array[Card], self_player: Node) -> Card:
	var ai_champions: int = _get_champion_count(self_player)
	var best_card: Card = null
	var best_value: int = -1
	for card: Card in playable_cards:
		var vals: Dictionary = evaluator.estimate_card_values(card, ai_champions)
		var value: int = int(vals.get("resource", 0))
		if value > best_value:
			best_value = value
			best_card = card
	return best_card if best_card != null else _choose_random(playable_cards)


func _choose_control(playable_cards: Array[Card], self_player: Node) -> Card:
	var ai_champions: int = _get_champion_count(self_player)
	var best_card: Card = null
	var best_value: int = -1
	for card: Card in playable_cards:
		var vals: Dictionary = evaluator.estimate_card_values(card, ai_champions)
		var value: int = int(vals.get("disruption", 0))
		if value > best_value:
			best_value = value
			best_card = card
	return best_card if best_card != null else _choose_random(playable_cards)


# Public synchronous card picker for use in headless simulations.
# Filters the hand by mana (all Hero Realms cards have cost=0 so this is a no-op
# in practice) and delegates to the configured strategy.
func choose_card(hand: Array[Card], self_player: Node, opponent_player: Node) -> Card:
	var playable: Array[Card] = _get_playable_cards(hand, _get_mana(self_player))
	if playable.is_empty():
		return null
	return _choose_card(playable, self_player, opponent_player)


# Public market-offer selector for headless simulations.
# Returns the index of the best offer to buy, or -1 if nothing is affordable.
func choose_market_offer(offers: Array[Dictionary], gold_pool: int, context: Dictionary) -> int:
	match difficulty:
		Difficulty.RANDOM:
			return _choose_market_random(offers, gold_pool)
		Difficulty.GREEDY, Difficulty.LOOKAHEAD:
			return _choose_market_scored(offers, gold_pool, context)
		Difficulty.AGGRO:
			return _choose_market_by_offer_field(offers, gold_pool, "combat")
		Difficulty.ECON:
			return _choose_market_greedy_cost(offers, gold_pool)
		Difficulty.CONTROL:
			return _choose_market_by_offer_field(offers, gold_pool, "opponent_discard")
		_:
			return _choose_market_random(offers, gold_pool)


func _choose_market_random(offers: Array[Dictionary], gold_pool: int) -> int:
	var affordable: Array[int] = []
	for i: int in range(offers.size()):
		if offers[i].is_empty():
			continue
		if int(offers[i].get("cost", 99)) <= gold_pool:
			affordable.append(i)
	if affordable.is_empty():
		return -1
	return affordable[randi_range(0, affordable.size() - 1)]


func _choose_market_scored(offers: Array[Dictionary], gold_pool: int, context: Dictionary) -> int:
	var best_idx: int = -1
	var best_score: float = -1.0
	for i: int in range(offers.size()):
		if offers[i].is_empty():
			continue
		if int(offers[i].get("cost", 99)) > gold_pool:
			continue
		var s: float = score_market_offer(offers[i], context)
		if s > best_score:
			best_score = s
			best_idx = i
	return best_idx


# Picks the affordable offer whose raw `field` value (from the parsed market
# entry dict) is highest. Falls back to greedy-by-cost when all offers score 0.
func _choose_market_by_offer_field(offers: Array[Dictionary], gold_pool: int, field: String) -> int:
	var best_idx: int = -1
	var best_value: int = -1
	for i: int in range(offers.size()):
		if offers[i].is_empty():
			continue
		if int(offers[i].get("cost", 99)) > gold_pool:
			continue
		var value: int = int(offers[i].get(field, 0))
		if value > best_value:
			best_value = value
			best_idx = i
	if best_idx == -1:
		return _choose_market_greedy_cost(offers, gold_pool)
	return best_idx


func _choose_market_greedy_cost(offers: Array[Dictionary], gold_pool: int) -> int:
	var best_idx: int = -1
	var best_cost: int = -1
	for i: int in range(offers.size()):
		if offers[i].is_empty():
			continue
		var cost: int = int(offers[i].get("cost", 99))
		if cost > gold_pool:
			continue
		if cost > best_cost:
			best_cost = cost
			best_idx = i
	return best_idx


func _build_eval_context(self_player: Node, opponent_player: Node) -> Dictionary:
	var opponent_hp_value: int = _get_health(opponent_player)
	if fog_of_war:
		# Optional hidden-information mode keeps AI from exact lethal math.
		opponent_hp_value = int(ceil(float(opponent_hp_value) * 0.9))

	var ai_max_hp: int = _get_max_health(self_player)
	if ai_max_hp <= 0:
		ai_max_hp = 50

	return {
		"ai_mana": _get_mana(self_player),
		"ai_max_mana": _get_max_mana(self_player),
		"ai_block": _get_block(self_player),
		"ai_hp": _get_health(self_player),
		"ai_max_hp": ai_max_hp,
		"ai_combat": _get_combat(self_player),
		"ai_gold": _get_gold(self_player),
		"ai_champions": _get_champion_count(self_player),
		"opponent_hp": opponent_hp_value,
		"opponent_block": _get_block(opponent_player),
		"opponent_champions": _get_champion_count(opponent_player),
		"board_threat": _estimate_opponent_threat(opponent_player)
	}


func _estimate_opponent_threat(opponent_player: Node) -> float:
	var threat: float = 0.2

	# Combat pool is an immediate damage threat.
	var combat: int = _get_combat(opponent_player)
	threat += clamp(float(combat) / 20.0, 0.0, 0.4)

	# Gold pool signals purchasing power and future deck strength.
	var gold: int = _get_gold(opponent_player)
	threat += clamp(float(gold) / 10.0, 0.0, 0.2)

	# Champion count signals persistent board presence.
	var champion_count: int = _get_champion_count(opponent_player)
	threat += clamp(float(champion_count) * 0.1, 0.0, 0.2)

	return clamp(threat, 0.0, 1.0)


func _get_hand(player: Node) -> Array[Card]:
	if player == null:
		return []

	# Supports either a direct hand array on player or a Hand node under player.
	if player.get("hand") != null and player.get("hand") is Array:
		var direct_hand: Array[Card] = []
		for item: Variant in player.get("hand"):
			if item is Card:
				direct_hand.append(item)
		return direct_hand

	var hand_node: Node = player.get_node_or_null("Hand")
	if hand_node != null and hand_node.get("cards") != null and hand_node.get("cards") is Array:
		var node_hand: Array[Card] = []
		for item: Variant in hand_node.get("cards"):
			if item is Card:
				node_hand.append(item)
		return node_hand

	return []


func _get_playable_cards(hand: Array[Card], mana: int) -> Array[Card]:
	var playable: Array[Card] = []
	for card: Card in hand:
		if card != null and card.cost <= mana:
			playable.append(card)
	return playable


func _play_card(player: Node, card: Card, target: Node) -> bool:
	if player.has_method("play_card"):
		var result: Variant = player.call("play_card", card, target)
		if result is bool:
			return result
		return true

	# Fallback for the current starter project architecture where card.play()
	# and state changes are managed directly by turn logic.
	if card.cost > _get_mana(player):
		return false

	if player.has_method("spend_energy"):
		var spent: Variant = player.call("spend_energy", card.cost)
		if spent is bool and not spent:
			return false

	card.play(target)
	_remove_card_from_owner(player, card)
	return true


func _remove_card_from_owner(player: Node, card: Card) -> void:
	if player.get("hand") != null and player.get("hand") is Array:
		var direct_hand: Array = player.get("hand")
		var idx: int = direct_hand.find(card)
		if idx != -1:
			direct_hand.remove_at(idx)

	var hand_node: Node = player.get_node_or_null("Hand")
	if hand_node != null and hand_node.has_method("remove_card"):
		# If remove_card(deck) exists in your project, pass null for compatibility.
		hand_node.call("remove_card", card, null)


func _without_card(cards: Array[Card], card_to_remove: Card) -> Array[Card]:
	var copy: Array[Card] = cards.duplicate()
	var index: int = copy.find(card_to_remove)
	if index != -1:
		copy.remove_at(index)
	return copy


func _get_mana(player: Node) -> int:
	if player == null:
		return 0
	if player.has_method("get_mana"):
		return int(player.call("get_mana"))
	if player.get("mana") != null:
		return int(player.get("mana"))
	if player.get("player_energy") != null:
		return int(player.get("player_energy"))
	return 0


func _get_max_mana(player: Node) -> int:
	if player == null:
		return 0
	if player.has_method("get_max_mana"):
		return int(player.call("get_max_mana"))
	if player.get("max_mana") != null:
		return int(player.get("max_mana"))
	if player.get("player_max_energy") != null:
		return int(player.get("player_max_energy"))
	return _get_mana(player)


func _get_health(player: Node) -> int:
	if player == null:
		return 0
	if player.has_method("get_health"):
		return int(player.call("get_health"))
	if player.get("health") != null:
		return int(player.get("health"))
	if player.get("player_hp") != null:
		return int(player.get("player_hp"))
	if player.get("current_hp") != null:
		return int(player.get("current_hp"))
	return 0


func _get_max_health(player: Node) -> int:
	if player == null:
		return 50
	if player.has_method("get_max_health"):
		return int(player.call("get_max_health"))
	if player.get("max_hp") != null:
		return int(player.get("max_hp"))
	if player.get("player_max_hp") != null:
		return int(player.get("player_max_hp"))
	return 50


func _get_block(player: Node) -> int:
	if player == null:
		return 0
	if player.has_method("get_block"):
		return int(player.call("get_block"))
	if player.get("block") != null:
		return int(player.get("block"))
	if player.get("player_block") != null:
		return int(player.get("player_block"))
	if player.get("current_block") != null:
		return int(player.get("current_block"))
	return 0


func _get_combat(player: Node) -> int:
	if player == null:
		return 0
	if player.has_method("get_combat_pool"):
		return int(player.call("get_combat_pool"))
	if player.get("combat_pool") != null:
		return int(player.get("combat_pool"))
	return 0


func _get_gold(player: Node) -> int:
	if player == null:
		return 0
	if player.has_method("get_gold_pool"):
		return int(player.call("get_gold_pool"))
	if player.get("gold_pool") != null:
		return int(player.get("gold_pool"))
	return 0


func _get_champion_count(player: Node) -> int:
	if player == null:
		return 0
	if player.get("champions_in_play") != null:
		return int(player.get("champions_in_play").size())
	return 0


# Public wrapper so external nodes (e.g., TurnManager) can get the same threat
# estimate used internally without reaching into a private method.
func estimate_threat(opponent_player: Node) -> float:
	return _estimate_opponent_threat(opponent_player)


# Score a raw market offer dictionary for the AI's current game state.
# Returns a value in [0, 1]; higher means more desirable to buy.
func score_market_offer(offer: Dictionary, context: Dictionary) -> float:
	if offer.is_empty():
		return 0.0
	var temp_card: Card = GameState.create_market_card_from_entry(offer)
	if temp_card == null:
		return 0.0
	# create_market_card_from_entry returns a DataCard (which extends Card and
	# RefCounted), so temp_card is automatically freed when it goes out of scope.
	# Use MARKET_EVAL_MANA so all market cards pass the playable_now check —
	# we are scoring purchase desirability, not hand playability.
	var buy_context: Dictionary = context.duplicate(true)
	buy_context["ai_mana"] = CardEvaluator.MARKET_EVAL_MANA
	return evaluator.score_card(temp_card, buy_context)
