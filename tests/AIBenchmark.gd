extends Node
## Round-robin AI strategy tournament.
##
## Every ordered pair of strategies plays GAMES_PER_PAIR games (strategy A
## always goes first for those games, and separately B always goes first).
## Results are accumulated per-strategy and printed as a ranked leaderboard
## with 95% confidence intervals. A head-to-head win-rate matrix is also
## printed. Results are exported to user://ai_benchmark_results.csv.
##
## Run from the scene AIBenchmarkRunner.tscn (headless is fine).

# Strategy table: [display_name, AIOpponent.Difficulty]
# Order determines seeding so keep it stable for reproducible results.
const STRATEGIES: Array = [
	["Random",     AIOpponent.Difficulty.RANDOM],
	["Aggro",      AIOpponent.Difficulty.AGGRO],
	["Econ",       AIOpponent.Difficulty.ECON],
	["Control",    AIOpponent.Difficulty.CONTROL],
	["Combo",      AIOpponent.Difficulty.COMBO],
	["Efficiency", AIOpponent.Difficulty.EFFICIENCY],
	["Greedy",     AIOpponent.Difficulty.GREEDY],
	["Lookahead",  AIOpponent.Difficulty.LOOKAHEAD],
	["Adaptive",   AIOpponent.Difficulty.ADAPTIVE],
]

## Games played per ordered pair (A always goes first).
## Each unordered matchup therefore runs 2 * GAMES_PER_PAIR total games.
const GAMES_PER_PAIR: int = 50

const _MAX_TURNS: int = 40
const _MARKET_SIZE: int = 5
const _INITIAL_FIRE_GEMS: int = 16
# Safety cap on cards played per turn to prevent infinite loops when a card
# draws many more cards (e.g. multiple draw-2 effects).
const _MAX_CARDS_PER_TURN: int = 30
# Seed multipliers chosen so that (a, b, game_num) combinations map to
# well-separated integers and avoid collisions across matchups.
const _SEED_STRATEGY_MULT: int = 10000
const _SEED_OPPONENT_MULT: int = 1000
const _SEED_GAME_MULT: int = 7

var _ai_instances: Array = []   # Array[AIOpponent]
var _wins: Array[int] = []
var _losses: Array[int] = []
var _draws: Array[int] = []

# Head-to-head matrix: _h2h[a][b] = wins of strategy a against strategy b.
var _h2h: Array = []   # Array[Array[int]]


func _ready() -> void:
	GameState.load_databases()
	var n: int = STRATEGIES.size()

	# Create one AIOpponent node per strategy.
	for entry: Array in STRATEGIES:
		var ai: AIOpponent = AIOpponent.new()
		ai.difficulty = entry[1]
		add_child(ai)
		_ai_instances.append(ai)
		_wins.append(0)
		_losses.append(0)
		_draws.append(0)
		var row: Array[int] = []
		row.resize(n)
		row.fill(0)
		_h2h.append(row)

	print("[BENCH] Starting benchmark: %d strategies × %d games per ordered pair" % [n, GAMES_PER_PAIR])

	for i: int in range(n):
		for j: int in range(n):
			if i == j:
				continue
			_run_ordered_matchup(i, j)

	_print_ranking()
	_print_h2h_matrix()
	_export_csv()
	get_tree().quit(0)


# Run GAMES_PER_PAIR games where strategy A always goes first.
func _run_ordered_matchup(a_idx: int, b_idx: int) -> void:
	var name_a: String = STRATEGIES[a_idx][0]
	var name_b: String = STRATEGIES[b_idx][0]
	var wins_a: int = 0
	var wins_b: int = 0
	var local_draws: int = 0

	for game_num: int in range(GAMES_PER_PAIR):
		# Derive a deterministic seed from strategy indices and game number.
		seed(a_idx * _SEED_STRATEGY_MULT + b_idx * _SEED_OPPONENT_MULT + game_num * _SEED_GAME_MULT)
		var result: int = _run_game(a_idx, b_idx)
		if result == 1:
			wins_a += 1
			_wins[a_idx] += 1
			_losses[b_idx] += 1
			_h2h[a_idx][b_idx] += 1
		elif result == 2:
			wins_b += 1
			_wins[b_idx] += 1
			_losses[a_idx] += 1
			_h2h[b_idx][a_idx] += 1
		else:
			local_draws += 1
			_draws[a_idx] += 1
			_draws[b_idx] += 1

	print("[BENCH] %s vs %s → A=%d  B=%d  D=%d" % [name_a, name_b, wins_a, wins_b, local_draws])


# Run one complete game with strategy A going first.
# Returns: 1 if A wins, 2 if B wins, 0 if draw after MAX_TURNS.
func _run_game(a_idx: int, b_idx: int) -> int:
	var player_a: BattlePlayer = BattlePlayer.new()
	var player_b: BattlePlayer = BattlePlayer.new()
	add_child(player_a)
	add_child(player_b)
	player_a.setup_from_ids("A", 50, 0, GameState.starting_deck_ids)
	player_b.setup_from_ids("B", 50, 0, GameState.starting_deck_ids)

	var market_pile: Array[Dictionary] = []
	var market_offers: Array[Dictionary] = []
	var fire_gems: int = _INITIAL_FIRE_GEMS

	for entry: Dictionary in GameState.marketplace_cards:
		market_pile.append(entry.duplicate(true))
	market_pile.shuffle()
	for _i: int in range(_MARKET_SIZE):
		market_offers.append(_draw_market_card(market_pile))

	var winner: int = 0

	for turn: int in range(1, _MAX_TURNS + 1):
		# Player A draws 3 on the very first turn (goes first).
		var draw_a: int = 3 if turn == 1 else 5
		fire_gems = _run_turn(player_a, player_b, a_idx, market_offers, market_pile, fire_gems, draw_a)
		if player_b.current_hp <= 0:
			winner = 1
			break

		fire_gems = _run_turn(player_b, player_a, b_idx, market_offers, market_pile, fire_gems, 5)
		if player_a.current_hp <= 0:
			winner = 2
			break

	# Time-limit tiebreak: higher remaining HP wins.
	if winner == 0:
		if player_a.current_hp > player_b.current_hp:
			winner = 1
		elif player_b.current_hp > player_a.current_hp:
			winner = 2

	player_a.free()
	player_b.free()
	return winner


# Execute one player's full turn. Returns the updated fire_gem count.
func _run_turn(
		active: BattlePlayer,
		other: BattlePlayer,
		strategy_idx: int,
		market_offers: Array[Dictionary],
		market_pile: Array[Dictionary],
		fire_gems: int,
		draw_count: int) -> int:

	active.start_turn(draw_count)
	active.auto_expend_all_champions()

	# Play all cards using the strategy's card-selection logic. We loop on
	# active.hand directly so draw-card effects are included automatically.
	var ai: AIOpponent = _ai_instances[strategy_idx]
	var safety: int = 0
	while not active.hand.is_empty() and safety < _MAX_CARDS_PER_TURN:
		safety += 1
		var chosen: Card = ai.choose_card(active.hand.duplicate(), active, other)
		if chosen == null:
			break
		if not active.play_card(chosen, other):
			# play_card rejected the card (e.g. pending choice in manual mode).
			break

	# Buy from market using strategy's purchasing logic.
	var context: Dictionary = _make_context(active, other)
	while true:
		var buy_idx: int = ai.choose_market_offer(market_offers, active.gold_pool, context)
		if buy_idx == -1:
			break
		var offer: Dictionary = market_offers[buy_idx]
		var cost: int = int(offer.get("cost", 99))
		if not active.spend_gold(cost):
			break
		var purchased: Card = GameState.create_market_card_from_entry(offer)
		if purchased == null:
			active.gain_gold(cost)
			break
		active.receive_acquired_card(purchased)
		market_offers[buy_idx] = _draw_market_card(market_pile)
		context["ai_gold"] = active.gold_pool

	# Spend leftover gold on fire gems.
	while fire_gems > 0 and active.gold_pool >= 2:
		if not active.spend_gold(2):
			break
		var gem: Card = GameState.create_card_from_id("fire_gem")
		if gem == null:
			active.gain_gold(2)
			break
		active.deck.discard_card(gem)
		fire_gems -= 1

	active.resolve_combat_against(other)
	active.end_turn()
	return fire_gems


func _make_context(active: BattlePlayer, other: BattlePlayer) -> Dictionary:
	# Determine the dominant faction played this turn for COMBO / ADAPTIVE buying.
	var dominant_faction: String = ""
	var max_count: int = 0
	for faction: String in active.faction_counts_this_turn.keys():
		var count: int = int(active.faction_counts_this_turn[faction])
		if count > max_count:
			max_count = count
			dominant_faction = faction

	return {
		"ai_mana": active.current_energy,
		"ai_max_mana": active.max_energy,
		"ai_block": active.current_block,
		"ai_hp": active.current_hp,
		"ai_max_hp": active.max_hp,
		"ai_combat": active.combat_pool,
		"ai_gold": active.gold_pool,
		"ai_champions": active.champions_in_play.size(),
		"opponent_hp": other.current_hp,
		"opponent_block": other.current_block,
		"opponent_champions": other.champions_in_play.size(),
		"board_threat": 0.2,
		"ai_dominant_faction": dominant_faction,
	}


func _draw_market_card(pile: Array[Dictionary]) -> Dictionary:
	if pile.is_empty():
		return {}
	return pile.pop_front()


func _print_ranking() -> void:
	var n: int = STRATEGIES.size()
	var entries: Array[Dictionary] = []
	for i: int in range(n):
		var total: int = _wins[i] + _losses[i] + _draws[i]
		var win_rate: float = 0.0
		var ci_half: float = 0.0
		if total > 0:
			# Count a draw as half a win.
			win_rate = (float(_wins[i]) + 0.5 * float(_draws[i])) / float(total)
			# 95% confidence interval half-width using normal approximation.
			ci_half = 1.96 * sqrt(win_rate * (1.0 - win_rate) / float(total))
		entries.append({
			"name": String(STRATEGIES[i][0]),
			"wins": _wins[i],
			"losses": _losses[i],
			"draws": _draws[i],
			"total": total,
			"win_rate": win_rate,
			"ci_half": ci_half,
		})

	entries.sort_custom(func(a: Dictionary, b: Dictionary) -> bool:
		return float(a.get("win_rate", 0.0)) > float(b.get("win_rate", 0.0))
	)

	print("\n[BENCH] ══════════════════ STRATEGY RANKINGS ══════════════════════════════")
	print("[BENCH] %-12s  %5s  %5s  %5s  %5s   Win%%   95%% CI" % ["Strategy", "W", "L", "D", "GP"])
	print("[BENCH] ────────────────────────────────────────────────────────────────────")
	for rank: int in range(entries.size()):
		var e: Dictionary = entries[rank]
		var pct: String = "%.1f%%" % (float(e.get("win_rate", 0.0)) * 100.0)
		var ci: String = "±%.1f%%" % (float(e.get("ci_half", 0.0)) * 100.0)
		print("[BENCH] #%d %-10s  %5d  %5d  %5d  %5d   %s  %s" % [
			rank + 1,
			String(e.get("name", "")),
			int(e.get("wins", 0)),
			int(e.get("losses", 0)),
			int(e.get("draws", 0)),
			int(e.get("total", 0)),
			pct,
			ci,
		])
	print("[BENCH] ══════════════════════════════════════════════════════════════════")


func _print_h2h_matrix() -> void:
	var n: int = STRATEGIES.size()
	# Build short column headers (first 6 chars to keep the table narrow).
	var headers: String = "[BENCH] H2H%% (row beats col)  "
	for j: int in range(n):
		headers += "%7s" % String(STRATEGIES[j][0]).left(6)
	print("\n" + headers)
	print("[BENCH] " + "-".repeat(headers.length() - 8))

	for i: int in range(n):
		var row_name: String = "%-12s" % String(STRATEGIES[i][0])
		var row_str: String = "[BENCH] " + row_name + "  "
		for j: int in range(n):
			if i == j:
				row_str += "      -"
			else:
				var total_ij: int = _h2h[i][j] + _h2h[j][i]
				if total_ij == 0:
					row_str += "    n/a"
				else:
					var pct: float = float(_h2h[i][j]) / float(total_ij) * 100.0
					row_str += "  %4.0f%%" % pct
		print(row_str)
	print("")


func _export_csv() -> void:
	var n: int = STRATEGIES.size()
	var lines: Array[String] = []
	lines.append("Rank,Strategy,W,L,D,GP,WinPct,CI95Half")

	var entries: Array[Dictionary] = []
	for i: int in range(n):
		var total: int = _wins[i] + _losses[i] + _draws[i]
		var win_rate: float = 0.0
		var ci_half: float = 0.0
		if total > 0:
			win_rate = (float(_wins[i]) + 0.5 * float(_draws[i])) / float(total)
			ci_half = 1.96 * sqrt(win_rate * (1.0 - win_rate) / float(total))
		entries.append({
			"name": String(STRATEGIES[i][0]),
			"wins": _wins[i],
			"losses": _losses[i],
			"draws": _draws[i],
			"total": total,
			"win_rate": win_rate,
			"ci_half": ci_half,
		})

	entries.sort_custom(func(a: Dictionary, b: Dictionary) -> bool:
		return float(a.get("win_rate", 0.0)) > float(b.get("win_rate", 0.0))
	)

	for rank: int in range(entries.size()):
		var e: Dictionary = entries[rank]
		lines.append("%d,%s,%d,%d,%d,%d,%.4f,%.4f" % [
			rank + 1,
			String(e.get("name", "")),
			int(e.get("wins", 0)),
			int(e.get("losses", 0)),
			int(e.get("draws", 0)),
			int(e.get("total", 0)),
			float(e.get("win_rate", 0.0)),
			float(e.get("ci_half", 0.0)),
		])

	var csv_path: String = "user://ai_benchmark_results.csv"
	var file: FileAccess = FileAccess.open(csv_path, FileAccess.WRITE)
	if file != null:
		for line: String in lines:
			file.store_line(line)
		file.close()
		print("[BENCH] CSV exported → " + csv_path)
	else:
		push_warning("[BENCH] Could not write CSV to " + csv_path)
