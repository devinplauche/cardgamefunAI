extends Node

var _failed: int = 0
var _passed: int = 0


func _ready() -> void:
	randomize()
	GameState.load_databases()
	run_all()
	var total: int = _passed + _failed
	print("[HERO-REALMS-TEST] Completed %d tests. Passed=%d Failed=%d" % [total, _passed, _failed])
	get_tree().quit(0 if _failed == 0 else 1)


func run_all() -> void:
	# ── Imperial Champions ─────────────────────────────────────────────────────
	test_arkus_expend_grants_combat_and_draws()
	test_arkus_ally_grants_health()
	test_darian_expend_grants_combat()
	test_cristov_expend_grants_combat_and_health()
	test_cristov_ally_draws_card()
	test_kraka_expend_draws_and_heals()
	test_kraka_ally_grants_flat_health()
	test_man_at_arms_expend_grants_base_combat()
	test_master_weyan_expend_grants_base_combat()
	test_tithe_priest_expend_grants_gold()
	# ── Imperial Actions ───────────────────────────────────────────────────────
	test_close_ranks_grants_combat()
	test_close_ranks_ally_grants_health()
	test_command_grants_gold_combat_health_and_draws()
	test_domination_grants_combat_health_and_draws()
	test_domination_ally_prepares_champion()
	test_rally_the_troops_grants_combat_and_health()
	test_rally_ally_prepares_champion()
	test_recruit_grants_gold_and_health()
	test_recruit_ally_grants_gold()
	test_taxation_grants_gold()
	test_taxation_ally_grants_health()
	test_word_of_power_draws_two_cards()
	test_word_of_power_ally_grants_health()
	test_word_of_power_sacrifice_grants_combat()
	# ── Guild Champions ────────────────────────────────────────────────────────
	test_borg_expend_grants_combat()
	test_myros_expend_grants_gold()
	test_myros_ally_grants_combat()
	test_parov_expend_grants_combat()
	test_parov_ally_draws_card()
	test_rake_expend_grants_combat()
	test_rasmus_expend_grants_gold()
	test_rasmus_ally_sets_topdeck_flag()
	test_street_thug_expend_grants_gold()
	# ── Guild Actions ──────────────────────────────────────────────────────────
	test_bribe_grants_gold()
	test_bribe_ally_sets_topdeck_action_flag()
	test_death_threat_grants_combat_and_draws()
	test_death_threat_ally_stuns_champion()
	test_deception_grants_gold_and_draws()
	test_deception_ally_sets_acquire_to_hand_flag()
	test_fire_bomb_grants_combat_and_draws()
	test_fire_bomb_sacrifice_grants_combat()
	test_hit_job_grants_combat()
	test_hit_job_ally_stuns_champion()
	test_intimidation_grants_combat()
	test_intimidation_ally_grants_gold()
	test_profit_grants_gold()
	test_profit_ally_grants_combat()
	test_smash_and_grab_grants_combat_and_recovers()
	# ── Necros Champions ───────────────────────────────────────────────────────
	test_cult_priest_expend_grants_gold()
	test_cult_priest_ally_grants_combat()
	test_death_cultist_expend_grants_combat()
	test_krythos_expend_grants_combat()
	test_krythos_sacrifice_grants_extra_combat()
	test_lys_expend_grants_combat()
	test_lys_sacrifice_grants_extra_combat()
	test_rayla_expend_grants_combat()
	test_rayla_ally_draws_card()
	test_tyrannor_expend_grants_combat()
	test_tyrannor_ally_draws_card()
	test_varrick_expend_recovers_champion()
	test_varrick_ally_draws_card()
	# ── Necros Actions ─────────────────────────────────────────────────────────
	test_dark_energy_grants_combat()
	test_dark_energy_ally_draws_card()
	test_dark_reward_grants_gold()
	test_death_touch_grants_combat()
	test_death_touch_ally_grants_combat()
	test_influence_grants_gold()
	test_influence_sacrifice_grants_combat()
	test_life_drain_grants_combat()
	test_life_drain_ally_draws_card()
	test_the_rot_grants_combat()
	test_the_rot_ally_grants_combat()
	# ── Wild Champions ─────────────────────────────────────────────────────────
	test_broelyn_expend_grants_gold()
	test_broelyn_ally_forces_discard()
	test_cron_expend_grants_combat()
	test_cron_ally_draws_card()
	test_dire_wolf_expend_grants_combat()
	test_dire_wolf_ally_grants_combat()
	test_grak_expend_grants_combat()
	test_grak_ally_draws_then_discards()
	test_orc_grunt_expend_grants_combat()
	test_orc_grunt_ally_draws_card()
	test_torgen_expend_grants_combat()
	test_wolf_shaman_expend_grants_base_combat()
	# ── Wild Actions ───────────────────────────────────────────────────────────
	test_elven_curse_grants_combat_and_forces_discard()
	test_elven_curse_ally_grants_combat()
	test_elven_gift_grants_gold()
	test_natures_bounty_grants_gold()
	test_natures_bounty_ally_forces_discard_only()
	test_natures_bounty_sacrifice_grants_combat()
	test_rampage_grants_combat()
	test_spark_grants_combat_and_forces_discard()
	test_spark_ally_grants_combat()
	test_wolf_form_grants_combat_and_forces_discard()
	test_wolf_form_sacrifice_forces_opponent_discard()
	# ── Fire Gem ───────────────────────────────────────────────────────────────
	test_fire_gem_grants_gold()
	test_fire_gem_sacrifice_grants_combat()


# ── Imperial Champions ─────────────────────────────────────────────────────────

func test_arkus_expend_grants_combat_and_draws() -> void:
	var player := _make_player()
	var target := _make_player()
	var arkus := _market_card("Arkus, Imperial Dragon")
	if arkus == null:
		return
	_seed_draw(player, 3)
	player.hand.append(arkus)
	_assert_true(player.play_card(arkus, target), "arkus-expend: champion played")
	var hand_before: int = player.hand.size()
	_assert_true(player.expend_champion(0, target), "arkus-expend: champion expended")
	_assert_equal(player.combat_pool, 5, "arkus-expend: gains 5 combat")
	_assert_equal(player.hand.size(), hand_before + 1, "arkus-expend: draws a card")


func test_arkus_ally_grants_health() -> void:
	var player := _make_player()
	var target := _make_player()
	var arkus := _market_card("Arkus, Imperial Dragon")
	if arkus == null:
		return
	var trigger := _faction_trigger("imperial")
	player.hand.append(trigger)
	player.hand.append(arkus)
	_assert_true(player.play_card(trigger, target), "arkus-ally: trigger played")
	var hp_before: int = player.current_hp
	_assert_true(player.play_card(arkus, target), "arkus-ally: arkus played as champion → ally fires")
	_assert_equal(player.current_hp, hp_before + 6, "arkus-ally: gains 6 health from ally")


func test_darian_expend_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var darian := _market_card("Darian, War Mage")
	if darian == null:
		return
	player.hand.append(darian)
	_assert_true(player.play_card(darian, target), "darian-expend: champion played")
	_assert_true(player.expend_champion(0, target), "darian-expend: champion expended")
	_assert_equal(player.combat_pool, 3, "darian-expend: gains 3 combat (auto choice picks combat)")


func test_cristov_expend_grants_combat_and_health() -> void:
	var player := _make_player()
	var target := _make_player()
	var cristov := _market_card("Cristov, the Just")
	if cristov == null:
		return
	player.hand.append(cristov)
	var hp_before: int = player.current_hp
	_assert_true(player.play_card(cristov, target), "cristov-expend: champion played")
	_assert_true(player.expend_champion(0, target), "cristov-expend: champion expended")
	_assert_equal(player.combat_pool, 2, "cristov-expend: gains 2 combat")
	_assert_equal(player.current_hp, hp_before + 3, "cristov-expend: gains 3 health")


func test_cristov_ally_draws_card() -> void:
	var player := _make_player()
	var target := _make_player()
	var cristov := _market_card("Cristov, the Just")
	if cristov == null:
		return
	_seed_draw(player, 3)
	var trigger := _faction_trigger("imperial")
	player.hand.append(trigger)
	player.hand.append(cristov)
	_assert_true(player.play_card(trigger, target), "cristov-ally: trigger played")
	var hand_before: int = player.hand.size()
	_assert_true(player.play_card(cristov, target), "cristov-ally: cristov played → ally fires")
	_assert_equal(player.hand.size(), hand_before + 1, "cristov-ally: draws a card from ally")


func test_kraka_expend_draws_and_heals() -> void:
	var player := _make_player()
	var target := _make_player()
	var kraka := _market_card("Kraka, High Priest")
	if kraka == null:
		return
	_seed_draw(player, 3)
	player.hand.append(kraka)
	var hp_before: int = player.current_hp
	var hand_before: int = player.hand.size()
	_assert_true(player.play_card(kraka, target), "kraka-expend: champion played")
	_assert_true(player.expend_champion(0, target), "kraka-expend: champion expended")
	_assert_equal(player.hand.size(), hand_before + 1, "kraka-expend: draws a card")
	_assert_equal(player.current_hp, hp_before + 2, "kraka-expend: gains 2 health")


func test_kraka_ally_grants_flat_health() -> void:
	var player := _make_player()
	var target := _make_player()
	var kraka := _market_card("Kraka, High Priest")
	if kraka == null:
		return
	var trigger := _faction_trigger("imperial")
	player.hand.append(trigger)
	player.hand.append(kraka)
	_assert_true(player.play_card(trigger, target), "kraka-ally: trigger played")
	var hp_before: int = player.current_hp
	_assert_true(player.play_card(kraka, target), "kraka-ally: kraka played → ally fires")
	_assert_true(player.current_hp > hp_before, "kraka-ally: ally grants health bonus")


func test_man_at_arms_expend_grants_base_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var maa := _market_card("Man-at-Arms")
	if maa == null:
		return
	player.hand.append(maa)
	_assert_true(player.play_card(maa, target), "man-at-arms-expend: champion played")
	_assert_true(player.expend_champion(0, target), "man-at-arms-expend: champion expended")
	_assert_equal(player.combat_pool, 2, "man-at-arms-expend: gains 2 base combat (no other guards)")


func test_master_weyan_expend_grants_base_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var weyan := _market_card("Master Weyan")
	if weyan == null:
		return
	player.hand.append(weyan)
	_assert_true(player.play_card(weyan, target), "master-weyan-expend: champion played")
	_assert_true(player.expend_champion(0, target), "master-weyan-expend: champion expended")
	_assert_equal(player.combat_pool, 3, "master-weyan-expend: gains 3 base combat (no other champions)")


func test_tithe_priest_expend_grants_gold() -> void:
	var player := _make_player()
	var target := _make_player()
	var tithe := _market_card("Tithe Priest")
	if tithe == null:
		return
	player.hand.append(tithe)
	_assert_true(player.play_card(tithe, target), "tithe-priest-expend: champion played")
	_assert_true(player.expend_champion(0, target), "tithe-priest-expend: champion expended")
	_assert_equal(player.gold_pool, 1, "tithe-priest-expend: gains 1 gold (auto choice picks gold)")


# ── Imperial Actions ────────────────────────────────────────────────────────────

func test_close_ranks_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Close Ranks")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "close-ranks: card played")
	_assert_equal(player.combat_pool, 5, "close-ranks: gains 5 base combat (no champions in play)")


func test_close_ranks_ally_grants_health() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Close Ranks")
	if card == null:
		return
	var trigger := _faction_trigger("imperial")
	player.hand.append(trigger)
	player.hand.append(card)
	_assert_true(player.play_card(trigger, target), "close-ranks-ally: trigger played")
	var hp_before: int = player.current_hp
	_assert_true(player.play_card(card, target), "close-ranks-ally: close ranks played → ally fires")
	_assert_equal(player.current_hp, hp_before + 6, "close-ranks-ally: both cards grant +6 health from ally")


func test_command_grants_gold_combat_health_and_draws() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Command")
	if card == null:
		return
	_seed_draw(player, 3)
	player.hand.append(card)
	var hp_before: int = player.current_hp
	_assert_true(player.play_card(card, target), "command: card played")
	_assert_equal(player.gold_pool, 2, "command: gains 2 gold")
	_assert_equal(player.combat_pool, 3, "command: gains 3 combat")
	_assert_equal(player.current_hp, hp_before + 4, "command: gains 4 health")


func test_domination_grants_combat_health_and_draws() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Domination")
	if card == null:
		return
	_seed_draw(player, 3)
	player.hand.append(card)
	var hp_before: int = player.current_hp
	var hand_before: int = player.hand.size()
	_assert_true(player.play_card(card, target), "domination: card played")
	_assert_equal(player.combat_pool, 6, "domination: gains 6 combat")
	_assert_equal(player.current_hp, hp_before + 6, "domination: gains 6 health")
	_assert_equal(player.hand.size(), hand_before + 1, "domination: draws a card")


func test_domination_ally_prepares_champion() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Domination")
	if card == null:
		return
	_seed_draw(player, 3)
	# Play and expend a champion so it becomes spent
	var spent_champ := _make_champion("Spent Champ", 3, false, [{"id": "set_faction", "faction": "imperial"}])
	player.hand.append(spent_champ)
	_assert_true(player.play_card(spent_champ, target), "domination-ally: spent champion played")
	_assert_true(player.expend_champion(0, target), "domination-ally: champion expended")
	_assert_equal(bool(player.champions_in_play[0].get("prepared", true)), false, "domination-ally: champion is now spent")
	# Now play Domination — 2 imperial cards in play (champion in refs + domination), ally fires
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "domination-ally: domination played → ally fires")
	_assert_equal(bool(player.champions_in_play[0].get("prepared", false)), true, "domination-ally: spent champion was prepared")


func test_rally_the_troops_grants_combat_and_health() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Rally the Troops")
	if card == null:
		return
	player.hand.append(card)
	var hp_before: int = player.current_hp
	_assert_true(player.play_card(card, target), "rally: card played")
	_assert_equal(player.combat_pool, 5, "rally: gains 5 combat")
	_assert_equal(player.current_hp, hp_before + 5, "rally: gains 5 health")


func test_rally_ally_prepares_champion() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Rally the Troops")
	if card == null:
		return
	var spent_champ := _make_champion("Spent Champ", 3, false, [{"id": "set_faction", "faction": "imperial"}])
	player.hand.append(spent_champ)
	_assert_true(player.play_card(spent_champ, target), "rally-ally: champion played")
	_assert_true(player.expend_champion(0, target), "rally-ally: champion expended")
	_assert_equal(bool(player.champions_in_play[0].get("prepared", true)), false, "rally-ally: champion is spent")
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "rally-ally: rally played → ally fires")
	_assert_equal(bool(player.champions_in_play[0].get("prepared", false)), true, "rally-ally: champion was prepared")


func test_recruit_grants_gold_and_health() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Recruit")
	if card == null:
		return
	player.hand.append(card)
	var hp_before: int = player.current_hp
	_assert_true(player.play_card(card, target), "recruit: card played")
	_assert_equal(player.gold_pool, 2, "recruit: gains 2 gold")
	_assert_equal(player.current_hp, hp_before + 3, "recruit: gains 3 health (no champion scaling)")


func test_recruit_ally_grants_gold() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Recruit")
	if card == null:
		return
	var trigger := _faction_trigger("imperial")
	player.hand.append(trigger)
	player.hand.append(card)
	_assert_true(player.play_card(trigger, target), "recruit-ally: trigger played")
	_assert_true(player.play_card(card, target), "recruit-ally: recruit played → ally fires")
	_assert_equal(player.gold_pool, 2 + 1, "recruit-ally: gains 2 gold (base) + 1 gold (ally)")


func test_taxation_grants_gold() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Taxation")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "taxation: card played")
	_assert_equal(player.gold_pool, 2, "taxation: gains 2 gold")


func test_taxation_ally_grants_health() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Taxation")
	if card == null:
		return
	var trigger := _faction_trigger("imperial")
	player.hand.append(trigger)
	player.hand.append(card)
	_assert_true(player.play_card(trigger, target), "taxation-ally: trigger played")
	var hp_before: int = player.current_hp
	_assert_true(player.play_card(card, target), "taxation-ally: taxation played → ally fires")
	_assert_equal(player.current_hp, hp_before + 6, "taxation-ally: gains 6 health from ally")


func test_word_of_power_draws_two_cards() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Word of Power")
	if card == null:
		return
	_seed_draw(player, 5)
	player.hand.append(card)
	var hand_before: int = player.hand.size()
	_assert_true(player.play_card(card, target), "word-of-power: card played")
	_assert_equal(player.hand.size(), hand_before + 2, "word-of-power: draws 2 cards (net hand -1 played +2 drawn = +1)")


func test_word_of_power_ally_grants_health() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Word of Power")
	if card == null:
		return
	_seed_draw(player, 5)
	var trigger := _faction_trigger("imperial")
	player.hand.append(trigger)
	player.hand.append(card)
	_assert_true(player.play_card(trigger, target), "word-of-power-ally: trigger played")
	var hp_before: int = player.current_hp
	_assert_true(player.play_card(card, target), "word-of-power-ally: word of power played → ally fires")
	_assert_equal(player.current_hp, hp_before + 5, "word-of-power-ally: gains 5 health from ally")
	_assert_equal(player.combat_pool, 0, "word-of-power-ally: no phantom combat from sacrifice section bleed")


func test_word_of_power_sacrifice_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Word of Power")
	if card == null:
		return
	_seed_draw(player, 5)
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "word-of-power-sacrifice: card played")
	_assert_true(player.has_pending_sacrifice_offer(), "word-of-power-sacrifice: sacrifice offer queued")
	_assert_true(_use_sacrifice(player), "word-of-power-sacrifice: sacrifice used")
	_assert_equal(player.combat_pool, 5, "word-of-power-sacrifice: gains 5 combat after self-sacrifice")


# ── Guild Champions ─────────────────────────────────────────────────────────────

func test_borg_expend_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Borg, Ogre Mercenary")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "borg-expend: champion played")
	_assert_true(player.expend_champion(0, target), "borg-expend: champion expended")
	_assert_equal(player.combat_pool, 4, "borg-expend: gains 4 combat")


func test_myros_expend_grants_gold() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Myros, Guild Mage")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "myros-expend: champion played")
	_assert_true(player.expend_champion(0, target), "myros-expend: champion expended")
	_assert_equal(player.gold_pool, 3, "myros-expend: gains 3 gold")


func test_myros_ally_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Myros, Guild Mage")
	if card == null:
		return
	var trigger := _faction_trigger("guild")
	player.hand.append(trigger)
	player.hand.append(card)
	_assert_true(player.play_card(trigger, target), "myros-ally: trigger played")
	_assert_true(player.play_card(card, target), "myros-ally: myros played → ally fires")
	_assert_equal(player.combat_pool, 4, "myros-ally: gains 4 combat from ally")


func test_parov_expend_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Parov, the Enforcer")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "parov-expend: champion played")
	_assert_true(player.expend_champion(0, target), "parov-expend: champion expended")
	_assert_equal(player.combat_pool, 3, "parov-expend: gains 3 combat")


func test_parov_ally_draws_card() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Parov, the Enforcer")
	if card == null:
		return
	_seed_draw(player, 3)
	var trigger := _faction_trigger("guild")
	player.hand.append(trigger)
	player.hand.append(card)
	_assert_true(player.play_card(trigger, target), "parov-ally: trigger played")
	var hand_before: int = player.hand.size()
	_assert_true(player.play_card(card, target), "parov-ally: parov played → ally fires")
	_assert_equal(player.hand.size(), hand_before + 1, "parov-ally: draws a card from ally")


func test_rake_expend_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Rake, Master Assassin")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "rake-expend: champion played")
	_assert_true(player.expend_champion(0, target), "rake-expend: champion expended")
	_assert_equal(player.combat_pool, 4, "rake-expend: gains 4 combat")


func test_rasmus_expend_grants_gold() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Rasmus, the Smuggler")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "rasmus-expend: champion played")
	_assert_true(player.expend_champion(0, target), "rasmus-expend: champion expended")
	_assert_equal(player.gold_pool, 2, "rasmus-expend: gains 2 gold")


func test_rasmus_ally_sets_topdeck_flag() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Rasmus, the Smuggler")
	if card == null:
		return
	var trigger := _faction_trigger("guild")
	player.hand.append(trigger)
	player.hand.append(card)
	_assert_true(player.play_card(trigger, target), "rasmus-ally: trigger played")
	_assert_true(player.play_card(card, target), "rasmus-ally: rasmus played → ally fires")
	_assert_equal(player.pending_acquire_to_topdeck_any, 1, "rasmus-ally: next acquire goes to topdeck")


func test_street_thug_expend_grants_gold() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Street Thug")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "street-thug-expend: champion played")
	_assert_true(player.expend_champion(0, target), "street-thug-expend: champion expended")
	_assert_equal(player.gold_pool, 1, "street-thug-expend: gains 1 gold (auto choice picks gold)")


# ── Guild Actions ────────────────────────────────────────────────────────────────

func test_bribe_grants_gold() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Bribe")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "bribe: card played")
	_assert_equal(player.gold_pool, 3, "bribe: gains 3 gold")


func test_bribe_ally_sets_topdeck_action_flag() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Bribe")
	if card == null:
		return
	var trigger := _faction_trigger("guild")
	player.hand.append(trigger)
	player.hand.append(card)
	_assert_true(player.play_card(trigger, target), "bribe-ally: trigger played")
	_assert_true(player.play_card(card, target), "bribe-ally: bribe played → ally fires")
	_assert_equal(player.pending_acquire_to_topdeck_actions, 1, "bribe-ally: next action acquired goes to topdeck")


func test_death_threat_grants_combat_and_draws() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Death Threat")
	if card == null:
		return
	_seed_draw(player, 3)
	player.hand.append(card)
	var hand_before: int = player.hand.size()
	_assert_true(player.play_card(card, target), "death-threat: card played")
	_assert_equal(player.combat_pool, 1, "death-threat: gains 1 combat")
	_assert_equal(player.hand.size(), hand_before + 1, "death-threat: draws a card (net: -1 played +1 drawn)")


func test_death_threat_ally_stuns_champion() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Death Threat")
	if card == null:
		return
	var enemy_champ := _make_champion("Enemy Champ", 4, false, [{"id": "set_faction", "faction": "guild"}])
	target.hand.append(enemy_champ)
	_assert_true(target.play_card(enemy_champ, player), "death-threat-ally: enemy champion placed")
	_assert_equal(target.champions_in_play.size(), 1, "death-threat-ally: enemy has 1 champion")
	var trigger := _faction_trigger("guild")
	player.hand.append(trigger)
	player.hand.append(card)
	_assert_true(player.play_card(trigger, target), "death-threat-ally: trigger played")
	_assert_true(player.play_card(card, target), "death-threat-ally: death threat played → ally fires")
	_assert_equal(target.champions_in_play.size(), 0, "death-threat-ally: enemy champion stunned")


func test_deception_grants_gold_and_draws() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Deception")
	if card == null:
		return
	_seed_draw(player, 3)
	player.hand.append(card)
	var hand_before: int = player.hand.size()
	_assert_true(player.play_card(card, target), "deception: card played")
	_assert_equal(player.gold_pool, 2, "deception: gains 2 gold")
	_assert_equal(player.hand.size(), hand_before + 1, "deception: draws a card (net: -1 played +1 drawn)")


func test_deception_ally_sets_acquire_to_hand_flag() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Deception")
	if card == null:
		return
	var trigger := _faction_trigger("guild")
	player.hand.append(trigger)
	player.hand.append(card)
	_assert_true(player.play_card(trigger, target), "deception-ally: trigger played")
	_assert_true(player.play_card(card, target), "deception-ally: deception played → ally fires")
	_assert_equal(player.pending_acquire_to_hand_any, 1, "deception-ally: next card acquired goes to hand")


func test_fire_bomb_grants_combat_and_draws() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Fire Bomb")
	if card == null:
		return
	_seed_draw(player, 3)
	# Fire Bomb stuns a champion; set up an enemy champion so stun has a target
	var enemy_champ := _make_champion("Enemy Champ", 4, false, [{"id": "set_faction", "faction": "guild"}])
	target.hand.append(enemy_champ)
	_assert_true(target.play_card(enemy_champ, player), "fire-bomb: enemy champion placed")
	player.hand.append(card)
	var hand_before: int = player.hand.size()
	_assert_true(player.play_card(card, target), "fire-bomb: card played")
	_assert_equal(player.combat_pool, 8, "fire-bomb: gains 8 combat")
	_assert_equal(player.hand.size(), hand_before + 1, "fire-bomb: draws a card (net: -1 played +1 drawn)")
	_assert_equal(target.champions_in_play.size(), 0, "fire-bomb: stuns target champion")


func test_fire_bomb_sacrifice_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Fire Bomb")
	if card == null:
		return
	_seed_draw(player, 3)
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "fire-bomb-sacrifice: card played")
	_assert_true(player.has_pending_sacrifice_offer(), "fire-bomb-sacrifice: sacrifice offer queued")
	var combat_before: int = player.combat_pool
	_assert_true(_use_sacrifice(player), "fire-bomb-sacrifice: sacrifice used")
	_assert_equal(player.combat_pool, combat_before + 5, "fire-bomb-sacrifice: gains 5 additional combat")


func test_hit_job_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Hit Job")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "hit-job: card played")
	_assert_equal(player.combat_pool, 7, "hit-job: gains 7 combat")


func test_hit_job_ally_stuns_champion() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Hit Job")
	if card == null:
		return
	var enemy_champ := _make_champion("Enemy Champ", 4, false, [{"id": "set_faction", "faction": "guild"}])
	target.hand.append(enemy_champ)
	_assert_true(target.play_card(enemy_champ, player), "hit-job-ally: enemy champion placed")
	var trigger := _faction_trigger("guild")
	player.hand.append(trigger)
	player.hand.append(card)
	_assert_true(player.play_card(trigger, target), "hit-job-ally: trigger played")
	_assert_true(player.play_card(card, target), "hit-job-ally: hit job played → ally fires")
	_assert_equal(target.champions_in_play.size(), 0, "hit-job-ally: enemy champion stunned")


func test_intimidation_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Intimidation")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "intimidation: card played")
	_assert_equal(player.combat_pool, 5, "intimidation: gains 5 combat")


func test_intimidation_ally_grants_gold() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Intimidation")
	if card == null:
		return
	var trigger := _faction_trigger("guild")
	player.hand.append(trigger)
	player.hand.append(card)
	_assert_true(player.play_card(trigger, target), "intimidation-ally: trigger played")
	_assert_true(player.play_card(card, target), "intimidation-ally: intimidation played → ally fires")
	_assert_equal(player.gold_pool, 2, "intimidation-ally: gains 2 gold from ally")


func test_profit_grants_gold() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Profit")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "profit: card played")
	_assert_equal(player.gold_pool, 2, "profit: gains 2 gold")


func test_profit_ally_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Profit")
	if card == null:
		return
	var trigger := _faction_trigger("guild")
	player.hand.append(trigger)
	player.hand.append(card)
	_assert_true(player.play_card(trigger, target), "profit-ally: trigger played")
	_assert_true(player.play_card(card, target), "profit-ally: profit played → ally fires")
	_assert_equal(player.combat_pool, 4, "profit-ally: gains 4 combat from ally")


func test_smash_and_grab_grants_combat_and_recovers() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Smash and Grab")
	if card == null:
		return
	var saved := _make_action("Saved Card", 3, [{"id": "gain_combat", "value": 3}])
	player.deck.discard_pile.append(saved)
	player.hand.append(card)
	var draw_before: int = player.deck.draw_count()
	_assert_true(player.play_card(card, target), "smash-and-grab: card played")
	_assert_equal(player.combat_pool, 6, "smash-and-grab: gains 6 combat")
	_assert_equal(player.deck.draw_count(), draw_before + 1, "smash-and-grab: recovers a card to topdeck")


# ── Necros Champions ────────────────────────────────────────────────────────────

func test_cult_priest_expend_grants_gold() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Cult Priest")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "cult-priest-expend: champion played")
	_assert_true(player.expend_champion(0, target), "cult-priest-expend: champion expended")
	_assert_equal(player.gold_pool, 1, "cult-priest-expend: gains 1 gold (auto choice picks gold)")
	_assert_equal(player.combat_pool, 0, "cult-priest-expend: does NOT also gain combat (choice is exclusive)")


func test_cult_priest_ally_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Cult Priest")
	if card == null:
		return
	var trigger := _faction_trigger("necros")
	player.hand.append(trigger)
	player.hand.append(card)
	_assert_true(player.play_card(trigger, target), "cult-priest-ally: trigger played")
	_assert_true(player.play_card(card, target), "cult-priest-ally: cult priest played → ally fires")
	_assert_equal(player.combat_pool, 4, "cult-priest-ally: gains 4 combat from ally")


func test_death_cultist_expend_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Death Cultist")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "death-cultist-expend: champion played")
	_assert_true(player.expend_champion(0, target), "death-cultist-expend: champion expended")
	_assert_equal(player.combat_pool, 2, "death-cultist-expend: gains 2 combat")


func test_krythos_expend_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Krythos, Master Vampire")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "krythos-expend: champion played")
	_assert_true(player.expend_champion(0, target), "krythos-expend: champion expended")
	_assert_equal(player.combat_pool, 3, "krythos-expend: gains 3 combat before sacrifice")


func test_krythos_sacrifice_grants_extra_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Krythos, Master Vampire")
	if card == null:
		return
	# Add a starter card (cost=0) to hand for the sacrifice
	var sacrificeable := _make_action("Starter Card", 0, [{"id": "gain_gold", "value": 1}])
	player.hand.append(card)
	player.hand.append(sacrificeable)
	_assert_true(player.play_card(card, target), "krythos-sacrifice: champion played")
	_assert_true(player.expend_champion(0, target), "krythos-sacrifice: champion expended")
	_assert_equal(player.combat_pool, 3, "krythos-sacrifice: gains base 3 combat before sacrifice")
	_assert_true(player.has_pending_sacrifice_offer(), "krythos-sacrifice: sacrifice offer queued")
	_assert_true(_use_sacrifice(player), "krythos-sacrifice: sacrifice used")
	_assert_equal(player.combat_pool, 6, "krythos-sacrifice: gains additional 3 combat after sacrifice")


func test_lys_expend_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Lys, the Unseen")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "lys-expend: champion played")
	_assert_true(player.expend_champion(0, target), "lys-expend: champion expended")
	_assert_equal(player.combat_pool, 2, "lys-expend: gains 2 combat before sacrifice")


func test_lys_sacrifice_grants_extra_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Lys, the Unseen")
	if card == null:
		return
	var sacrificeable := _make_action("Starter Card", 0, [{"id": "gain_gold", "value": 1}])
	player.hand.append(card)
	player.hand.append(sacrificeable)
	_assert_true(player.play_card(card, target), "lys-sacrifice: champion played")
	_assert_true(player.expend_champion(0, target), "lys-sacrifice: champion expended")
	_assert_equal(player.combat_pool, 2, "lys-sacrifice: gains base 2 combat before sacrifice")
	_assert_true(player.has_pending_sacrifice_offer(), "lys-sacrifice: sacrifice offer queued")
	_assert_true(_use_sacrifice(player), "lys-sacrifice: sacrifice used")
	_assert_equal(player.combat_pool, 4, "lys-sacrifice: gains additional 2 combat after sacrifice")


func test_rayla_expend_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Rayla, Endweaver")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "rayla-expend: champion played")
	_assert_true(player.expend_champion(0, target), "rayla-expend: champion expended")
	_assert_equal(player.combat_pool, 3, "rayla-expend: gains 3 combat")


func test_rayla_ally_draws_card() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Rayla, Endweaver")
	if card == null:
		return
	_seed_draw(player, 3)
	var trigger := _faction_trigger("necros")
	player.hand.append(trigger)
	player.hand.append(card)
	_assert_true(player.play_card(trigger, target), "rayla-ally: trigger played")
	var hand_before: int = player.hand.size()
	_assert_true(player.play_card(card, target), "rayla-ally: rayla played → ally fires")
	_assert_equal(player.hand.size(), hand_before + 1, "rayla-ally: draws a card from ally")


func test_tyrannor_expend_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Tyrannor, the Devourer")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "tyrannor-expend: champion played")
	_assert_true(player.expend_champion(0, target), "tyrannor-expend: champion expended")
	_assert_equal(player.combat_pool, 4, "tyrannor-expend: gains 4 combat")


func test_tyrannor_ally_draws_card() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Tyrannor, the Devourer")
	if card == null:
		return
	_seed_draw(player, 3)
	var trigger := _faction_trigger("necros")
	player.hand.append(trigger)
	player.hand.append(card)
	_assert_true(player.play_card(trigger, target), "tyrannor-ally: trigger played")
	var hand_before: int = player.hand.size()
	_assert_true(player.play_card(card, target), "tyrannor-ally: tyrannor played → ally fires")
	_assert_equal(player.hand.size(), hand_before + 1, "tyrannor-ally: draws a card from ally")


func test_varrick_expend_recovers_champion() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Varrick, the Necromancer")
	if card == null:
		return
	var recovered := _make_champion("Lost Champ", 3, false, [{"id": "set_faction", "faction": "necros"}])
	player.deck.discard_pile.append(recovered)
	player.hand.append(card)
	var draw_before: int = player.deck.draw_count()
	_assert_true(player.play_card(card, target), "varrick-expend: champion played")
	_assert_true(player.expend_champion(0, target), "varrick-expend: champion expended")
	_assert_equal(player.deck.draw_count(), draw_before + 1, "varrick-expend: champion moved from discard to topdeck")


func test_varrick_ally_draws_card() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Varrick, the Necromancer")
	if card == null:
		return
	_seed_draw(player, 3)
	var trigger := _faction_trigger("necros")
	player.hand.append(trigger)
	player.hand.append(card)
	_assert_true(player.play_card(trigger, target), "varrick-ally: trigger played")
	var hand_before: int = player.hand.size()
	_assert_true(player.play_card(card, target), "varrick-ally: varrick played → ally fires")
	_assert_equal(player.hand.size(), hand_before + 1, "varrick-ally: draws a card from ally")


# ── Necros Actions ───────────────────────────────────────────────────────────────

func test_dark_energy_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Dark Energy")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "dark-energy: card played")
	_assert_equal(player.combat_pool, 7, "dark-energy: gains 7 combat")


func test_dark_energy_ally_draws_card() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Dark Energy")
	if card == null:
		return
	_seed_draw(player, 3)
	var trigger := _faction_trigger("necros")
	player.hand.append(trigger)
	player.hand.append(card)
	_assert_true(player.play_card(trigger, target), "dark-energy-ally: trigger played")
	var hand_before: int = player.hand.size()
	_assert_true(player.play_card(card, target), "dark-energy-ally: dark energy played → ally fires")
	_assert_equal(player.hand.size(), hand_before + 1, "dark-energy-ally: draws a card from ally")


func test_dark_reward_grants_gold() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Dark Reward")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "dark-reward: card played")
	_assert_equal(player.gold_pool, 3, "dark-reward: gains 3 gold")


func test_death_touch_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Death Touch")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "death-touch: card played")
	_assert_equal(player.combat_pool, 2, "death-touch: gains 2 combat")


func test_death_touch_ally_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Death Touch")
	if card == null:
		return
	var trigger := _faction_trigger("necros")
	player.hand.append(trigger)
	player.hand.append(card)
	_assert_true(player.play_card(trigger, target), "death-touch-ally: trigger played")
	_assert_true(player.play_card(card, target), "death-touch-ally: death touch played → ally fires")
	_assert_equal(player.combat_pool, 2 + 2, "death-touch-ally: 2 base + 2 from ally")


func test_influence_grants_gold() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Influence")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "influence: card played")
	_assert_equal(player.gold_pool, 3, "influence: gains 3 gold")


func test_influence_sacrifice_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Influence")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "influence-sacrifice: card played")
	_assert_true(player.has_pending_sacrifice_offer(), "influence-sacrifice: sacrifice offer queued")
	_assert_true(_use_sacrifice(player), "influence-sacrifice: sacrifice used")
	_assert_equal(player.combat_pool, 3, "influence-sacrifice: gains 3 combat after self-sacrifice")


func test_life_drain_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Life Drain")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "life-drain: card played")
	_assert_equal(player.combat_pool, 8, "life-drain: gains 8 combat")


func test_life_drain_ally_draws_card() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Life Drain")
	if card == null:
		return
	_seed_draw(player, 3)
	var trigger := _faction_trigger("necros")
	player.hand.append(trigger)
	player.hand.append(card)
	_assert_true(player.play_card(trigger, target), "life-drain-ally: trigger played")
	var hand_before: int = player.hand.size()
	_assert_true(player.play_card(card, target), "life-drain-ally: life drain played → ally fires")
	_assert_equal(player.hand.size(), hand_before + 1, "life-drain-ally: draws a card from ally")


func test_the_rot_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("The Rot")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "the-rot: card played")
	_assert_equal(player.combat_pool, 4, "the-rot: gains 4 combat")


func test_the_rot_ally_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("The Rot")
	if card == null:
		return
	var trigger := _faction_trigger("necros")
	player.hand.append(trigger)
	player.hand.append(card)
	_assert_true(player.play_card(trigger, target), "the-rot-ally: trigger played")
	_assert_true(player.play_card(card, target), "the-rot-ally: the rot played → ally fires")
	_assert_equal(player.combat_pool, 4 + 3, "the-rot-ally: 4 base + 3 from ally")


# ── Wild Champions ───────────────────────────────────────────────────────────────

func test_broelyn_expend_grants_gold() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Broelyn, Loreweaver")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "broelyn-expend: champion played")
	_assert_true(player.expend_champion(0, target), "broelyn-expend: champion expended")
	_assert_equal(player.gold_pool, 2, "broelyn-expend: gains 2 gold")


func test_broelyn_ally_forces_discard() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Broelyn, Loreweaver")
	if card == null:
		return
	# Give the opponent a card in hand to discard
	var opp_card := _make_action("Opp Card", 2, [{"id": "gain_gold", "value": 2}])
	target.hand.append(opp_card)
	_assert_equal(target.hand.size(), 1, "broelyn-ally: opponent has 1 card in hand")
	var trigger := _faction_trigger("wild")
	player.hand.append(trigger)
	player.hand.append(card)
	_assert_true(player.play_card(trigger, target), "broelyn-ally: trigger played")
	_assert_true(player.play_card(card, target), "broelyn-ally: broelyn played → ally fires")
	_assert_equal(target.hand.size(), 0, "broelyn-ally: opponent discarded a card")


func test_cron_expend_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Cron, the Berserker")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "cron-expend: champion played")
	_assert_true(player.expend_champion(0, target), "cron-expend: champion expended")
	_assert_equal(player.combat_pool, 5, "cron-expend: gains 5 combat")


func test_cron_ally_draws_card() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Cron, the Berserker")
	if card == null:
		return
	_seed_draw(player, 3)
	var trigger := _faction_trigger("wild")
	player.hand.append(trigger)
	player.hand.append(card)
	_assert_true(player.play_card(trigger, target), "cron-ally: trigger played")
	var hand_before: int = player.hand.size()
	_assert_true(player.play_card(card, target), "cron-ally: cron played → ally fires")
	_assert_equal(player.hand.size(), hand_before + 1, "cron-ally: draws a card from ally")


func test_dire_wolf_expend_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Dire Wolf")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "dire-wolf-expend: champion played")
	_assert_true(player.expend_champion(0, target), "dire-wolf-expend: champion expended")
	_assert_equal(player.combat_pool, 3, "dire-wolf-expend: gains 3 combat")


func test_dire_wolf_ally_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Dire Wolf")
	if card == null:
		return
	var trigger := _faction_trigger("wild")
	player.hand.append(trigger)
	player.hand.append(card)
	_assert_true(player.play_card(trigger, target), "dire-wolf-ally: trigger played")
	_assert_true(player.play_card(card, target), "dire-wolf-ally: dire wolf played → ally fires")
	_assert_equal(player.combat_pool, 4, "dire-wolf-ally: gains 4 combat from ally")


func test_grak_expend_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Grak, Storm Giant")
	if card == null:
		return
	_seed_draw(player, 3)
	var filler := _make_action("Filler", 1, [{"id": "gain_gold", "value": 1}])
	player.hand.append(filler)
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "grak-expend: champion played")
	_assert_true(player.expend_champion(0, target), "grak-expend: champion expended")
	_assert_equal(player.combat_pool, 6, "grak-expend: gains 6 combat")


func test_grak_ally_draws_then_discards() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Grak, Storm Giant")
	if card == null:
		return
	_seed_draw(player, 3)
	var filler := _make_action("Filler", 1, [{"id": "gain_gold", "value": 1}])
	player.hand.append(filler)
	var trigger := _faction_trigger("wild")
	player.hand.append(trigger)
	player.hand.append(card)
	_assert_true(player.play_card(trigger, target), "grak-ally: trigger played")
	var discard_before: int = player.deck.discard_count()
	_assert_true(player.play_card(card, target), "grak-ally: grak played → ally fires draw-then-discard")
	# Ally fires: draw 1, discard 1 → net 0 hand change but discard grows by 1
	_assert_equal(player.deck.discard_count(), discard_before + 1, "grak-ally: drew then discarded a card")


func test_orc_grunt_expend_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Orc Grunt")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "orc-grunt-expend: champion played")
	_assert_true(player.expend_champion(0, target), "orc-grunt-expend: champion expended")
	_assert_equal(player.combat_pool, 2, "orc-grunt-expend: gains 2 combat")


func test_orc_grunt_ally_draws_card() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Orc Grunt")
	if card == null:
		return
	_seed_draw(player, 3)
	var trigger := _faction_trigger("wild")
	player.hand.append(trigger)
	player.hand.append(card)
	_assert_true(player.play_card(trigger, target), "orc-grunt-ally: trigger played")
	var hand_before: int = player.hand.size()
	_assert_true(player.play_card(card, target), "orc-grunt-ally: orc grunt played → ally fires")
	_assert_equal(player.hand.size(), hand_before + 1, "orc-grunt-ally: draws a card from ally")


func test_torgen_expend_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Torgen Rocksplitter")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "torgen-expend: champion played")
	_assert_true(player.expend_champion(0, target), "torgen-expend: champion expended")
	_assert_equal(player.combat_pool, 4, "torgen-expend: gains 4 combat")


func test_wolf_shaman_expend_grants_base_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Wolf Shaman")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "wolf-shaman-expend: champion played")
	_assert_true(player.expend_champion(0, target), "wolf-shaman-expend: champion expended")
	_assert_equal(player.combat_pool, 2, "wolf-shaman-expend: gains 2 combat (no other wild cards)")


# ── Wild Actions ─────────────────────────────────────────────────────────────────

func test_elven_curse_grants_combat_and_forces_discard() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Elven Curse")
	if card == null:
		return
	var opp_card := _make_action("Opp Card", 2, [{"id": "gain_gold", "value": 2}])
	target.hand.append(opp_card)
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "elven-curse: card played")
	_assert_equal(player.combat_pool, 6, "elven-curse: gains 6 combat")
	_assert_equal(target.hand.size(), 0, "elven-curse: opponent discarded a card")


func test_elven_curse_ally_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Elven Curse")
	if card == null:
		return
	var trigger := _faction_trigger("wild")
	player.hand.append(trigger)
	player.hand.append(card)
	_assert_true(player.play_card(trigger, target), "elven-curse-ally: trigger played")
	_assert_true(player.play_card(card, target), "elven-curse-ally: elven curse played → ally fires")
	_assert_equal(player.combat_pool, 6 + 3, "elven-curse-ally: 6 base + 3 from ally")


func test_elven_gift_grants_gold() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Elven Gift")
	if card == null:
		return
	_seed_draw(player, 3)
	var filler := _make_action("Filler", 1, [{"id": "gain_gold", "value": 1}])
	player.hand.append(filler)
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "elven-gift: card played")
	_assert_equal(player.gold_pool, 2, "elven-gift: gains 2 gold")


func test_natures_bounty_grants_gold() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Nature's Bounty")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "natures-bounty: card played")
	_assert_equal(player.gold_pool, 4, "natures-bounty: gains 4 gold")


func test_natures_bounty_ally_forces_discard_only() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Nature's Bounty")
	if card == null:
		return
	var enemy_hand_card := _make_action("Enemy Card", 0, [{"id": "gain_gold", "value": 1}])
	target.hand.append(enemy_hand_card)
	var trigger := _faction_trigger("wild")
	player.hand.append(trigger)
	player.hand.append(card)
	_assert_true(player.play_card(trigger, target), "natures-bounty-ally: trigger played")
	_assert_true(player.play_card(card, target), "natures-bounty-ally: natures bounty played → ally fires")
	_assert_equal(player.combat_pool, 0, "natures-bounty-ally: no phantom combat from sacrifice section bleed")
	_assert_equal(target.hand.size(), 0, "natures-bounty-ally: opponent discarded a card")


func test_natures_bounty_sacrifice_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Nature's Bounty")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "natures-bounty-sacrifice: card played")
	_assert_true(player.has_pending_sacrifice_offer(), "natures-bounty-sacrifice: sacrifice offer queued")
	_assert_true(_use_sacrifice(player), "natures-bounty-sacrifice: sacrifice used")
	_assert_equal(player.combat_pool, 4, "natures-bounty-sacrifice: gains 4 combat after self-sacrifice")


func test_rampage_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Rampage")
	if card == null:
		return
	_seed_draw(player, 3)
	var filler_a := _make_action("Filler A", 1, [{"id": "gain_gold", "value": 1}])
	var filler_b := _make_action("Filler B", 1, [{"id": "gain_gold", "value": 1}])
	player.hand.append(filler_a)
	player.hand.append(filler_b)
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "rampage: card played")
	_assert_equal(player.combat_pool, 6, "rampage: gains 6 combat")


func test_spark_grants_combat_and_forces_discard() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Spark")
	if card == null:
		return
	var opp_card := _make_action("Opp Card", 2, [{"id": "gain_gold", "value": 2}])
	target.hand.append(opp_card)
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "spark: card played")
	_assert_equal(player.combat_pool, 3, "spark: gains 3 combat")
	_assert_equal(target.hand.size(), 0, "spark: opponent discarded a card")


func test_spark_ally_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Spark")
	if card == null:
		return
	var trigger := _faction_trigger("wild")
	player.hand.append(trigger)
	player.hand.append(card)
	_assert_true(player.play_card(trigger, target), "spark-ally: trigger played")
	_assert_true(player.play_card(card, target), "spark-ally: spark played → ally fires")
	_assert_equal(player.combat_pool, 3 + 2, "spark-ally: 3 base + 2 from ally")


func test_wolf_form_grants_combat_and_forces_discard() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Wolf Form")
	if card == null:
		return
	var opp_card := _make_action("Opp Card", 2, [{"id": "gain_gold", "value": 2}])
	target.hand.append(opp_card)
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "wolf-form: card played")
	_assert_equal(player.combat_pool, 8, "wolf-form: gains 8 combat")
	_assert_equal(target.hand.size(), 0, "wolf-form: opponent discarded a card")


func test_wolf_form_sacrifice_forces_opponent_discard() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Wolf Form")
	if card == null:
		return
	var opp_card_a := _make_action("Opp Card A", 2, [{"id": "gain_gold", "value": 2}])
	var opp_card_b := _make_action("Opp Card B", 2, [{"id": "gain_gold", "value": 2}])
	target.hand.append(opp_card_a)
	target.hand.append(opp_card_b)
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "wolf-form-sacrifice: card played (opponent discards 1)")
	_assert_equal(target.hand.size(), 1, "wolf-form-sacrifice: opponent still has 1 card")
	_assert_true(player.has_pending_sacrifice_offer(), "wolf-form-sacrifice: sacrifice offer queued")
	_assert_true(_use_sacrifice(player), "wolf-form-sacrifice: sacrifice used")
	_assert_equal(target.hand.size(), 0, "wolf-form-sacrifice: opponent discards 1 more after sacrifice")


# ── Fire Gem ─────────────────────────────────────────────────────────────────────

func test_fire_gem_grants_gold() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Fire Gem")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "fire-gem: card played")
	_assert_equal(player.gold_pool, 2, "fire-gem: gains 2 gold")


func test_fire_gem_sacrifice_grants_combat() -> void:
	var player := _make_player()
	var target := _make_player()
	var card := _market_card("Fire Gem")
	if card == null:
		return
	player.hand.append(card)
	_assert_true(player.play_card(card, target), "fire-gem-sacrifice: card played")
	_assert_true(player.has_pending_sacrifice_offer(), "fire-gem-sacrifice: sacrifice offer queued")
	_assert_true(_use_sacrifice(player), "fire-gem-sacrifice: sacrifice used")
	_assert_equal(player.combat_pool, 3, "fire-gem-sacrifice: gains 3 combat after self-sacrifice")


# ── Helpers ───────────────────────────────────────────────────────────────────────

func _make_player() -> BattlePlayer:
	var player := BattlePlayer.new()
	player.setup_from_ids("Tester", 50, 0, GameState.starting_deck_ids)
	player.max_hp = 200
	player.current_hp = 100
	player.hand.clear()
	player.deck.draw_pile.clear()
	player.deck.discard_pile.clear()
	return player


func _find_market_entry(card_name: String) -> Dictionary:
	for entry: Dictionary in GameState.marketplace_cards:
		if String(entry.get("name", "")) == card_name:
			return entry.duplicate(true)
	return {}


func _market_card(card_name: String) -> DataCard:
	var entry: Dictionary = _find_market_entry(card_name)
	if entry.is_empty():
		_failed += 1
		push_error("[FAIL] Market card not found: %s" % card_name)
		return null
	var card: Card = GameState.create_market_card_from_entry(entry)
	if card == null or not (card is DataCard):
		_failed += 1
		push_error("[FAIL] Market card failed to create or is not DataCard: %s" % card_name)
		return null
	return card as DataCard


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


func _faction_trigger(faction: String) -> DataCard:
	return _make_action("Faction Trigger", 0, [{"id": "set_faction", "faction": faction}])


func _seed_draw(player: BattlePlayer, count: int) -> void:
	for i: int in range(count):
		var seed: DataCard = _make_action("Seed %d" % i, 0, [{"id": "gain_gold", "value": 1}])
		player.deck.draw_pile.append(seed)


func _assert_equal(actual: Variant, expected: Variant, label: String) -> void:
	if actual == expected:
		_passed += 1
		print("[PASS] %s" % label)
	else:
		_failed += 1
		push_error("[FAIL] %s | expected=%s actual=%s" % [label, str(expected), str(actual)])


func _use_sacrifice(player: BattlePlayer) -> bool:
	var pile: Array[Card] = []
	return player.use_sacrifice_offer(pile)


func _assert_true(value: bool, label: String) -> void:
	_assert_equal(value, true, label)
