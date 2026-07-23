"""Regression tests for champion sniping.

Per the official rules, a Guard blocks attacks against BOTH the player and
non-guard champions: "While you have a prepared guard in play... your
non-guard Champions may not be attacked or targeted by an opponent." But
once no guard remains, combat may be freely assigned: "You may use Combat
to attack your opponent and/or their Champions... To attack an opposing
Champion, subtract any amount of Combat from your Combat Pool and the
Champion takes an equal amount of damage."

Every combat resolution path in this codebase - legal_actions/
attack_target_action, hero_ai's attack_weakest/attack_strongest,
hero_engine's HRGame._resolve_combat, hero_rl_env's two combat sites, and
hero_mcts_bench's opponent-profile driver - previously only ever offered
guards-or-face. A non-guard champion could never be attacked at all, no
matter how undefended the board was.
"""

import unittest

from hero_engine import (
    BoardChampion,
    HRPlayer,
    load_hero_cards,
)

CARDS = load_hero_cards("data/hero_realms_cards.json")


def _non_guard_champion(max_health=None):
    for c in CARDS:
        if c.card_type == "champion" and not c.guard:
            if max_health is None or c.health <= max_health:
                return c
    raise AssertionError("no matching non-guard champion in the card set")


def _guard_champion():
    return next(c for c in CARDS if c.card_type == "champion" and c.guard > 0)


class TestSessionLevelSniping(unittest.TestCase):
    def test_a_non_guard_champion_is_a_legal_target_with_no_guard_present(self):
        from web.session import create_session

        champ = _non_guard_champion()
        session = create_session(seed=7)
        session.bot.board = [BoardChampion(champ)]
        session.active_player = "player"
        session.phase = "combat"
        session.player.combat = 3

        actions = session.legal_actions()
        kinds = {(a["type"], a.get("target")) for a in actions}
        self.assertIn(("attack_target", "champion"), kinds)
        self.assertIn(("attack_target", "player"), kinds,
                      "the player must still be offered as a target alongside the champion")

    def test_a_guard_blocks_targeting_non_guard_champions_and_the_player(self):
        champ = _non_guard_champion()
        guard = _guard_champion()
        from web.session import create_session

        session = create_session(seed=7)
        guard_bc = BoardChampion(guard)
        session.bot.board = [BoardChampion(champ), guard_bc]
        session.active_player = "player"
        session.phase = "combat"
        session.player.combat = 3

        actions = session.legal_actions()
        champion_ids = {a["championId"] for a in actions if a["type"] == "attack_target"
                        and a.get("target") == "champion"}
        self.assertEqual(champion_ids, {str(guard_bc.instance_id)},
                         "only the guard should be a legal target")
        self.assertNotIn(("attack_target", "player"),
                         {(a["type"], a.get("target")) for a in actions})

    def test_killing_a_non_guard_champion_moves_it_to_discard(self):
        from web.session import create_session

        champ = _non_guard_champion()
        session = create_session(seed=7)
        session.bot.board = [BoardChampion(champ)]
        session.active_player = "player"
        session.phase = "combat"
        session.player.combat = champ.health + 4

        session.attack_target_action("champion", str(session.bot.board[0].instance_id))

        self.assertEqual(session.bot.board, [])
        self.assertIn(champ, session.bot.discard)

    def test_leftover_combat_after_a_kill_is_not_auto_spilled(self):
        """The player must explicitly choose where any remaining combat goes -
        it used to auto-spill to face the instant no guard remained."""
        from web.session import create_session

        champ = _non_guard_champion()
        session = create_session(seed=7)
        session.bot.board = [BoardChampion(champ)]
        session.bot.hp = 50
        session.active_player = "player"
        session.phase = "combat"
        session.player.combat = champ.health + 4

        session.attack_target_action("champion", str(session.bot.board[0].instance_id))

        self.assertEqual(session.player.combat, 4)
        self.assertEqual(session.bot.hp, 50)

    def test_leftover_combat_can_then_be_explicitly_spent_on_the_player(self):
        from web.session import create_session

        champ = _non_guard_champion()
        session = create_session(seed=7)
        session.bot.board = [BoardChampion(champ)]
        session.bot.hp = 50
        session.active_player = "player"
        session.phase = "combat"
        session.player.combat = champ.health + 4

        session.attack_target_action("champion", str(session.bot.board[0].instance_id))
        session.attack_target_action("player")

        self.assertEqual(session.bot.hp, 46)
        self.assertEqual(session.player.combat, 0)

    def test_a_partial_non_lethal_chip_is_permitted_and_not_auto_completed(self):
        """The engine allows a player to make a suboptimal choice (a chip that
        does not kill); it does not force or forbid this, only an AI policy
        would avoid it."""
        from web.session import create_session

        champ = next(c for c in CARDS if c.card_type == "champion" and not c.guard and c.health >= 4)
        session = create_session(seed=7)
        session.bot.board = [BoardChampion(champ)]
        session.active_player = "player"
        session.phase = "combat"
        session.player.combat = 2

        session.attack_target_action("champion", str(session.bot.board[0].instance_id))

        self.assertTrue(session.bot.board)
        self.assertEqual(session.bot.board[0].current_health, champ.health - 2)
        self.assertEqual(session.player.combat, 0)


class TestHeuristicAiSniping(unittest.TestCase):
    def test_attack_weakest_kills_a_full_health_non_guard_champion(self):
        from hero_ai import attack_weakest

        killable = _non_guard_champion(max_health=4)
        attacker = HRPlayer("A")
        defender = HRPlayer("D")
        defender.hp = 50
        defender.board = [BoardChampion(killable)]
        attacker.combat = killable.health + 3

        attack_weakest(attacker, defender, guards=[])

        self.assertEqual(defender.board, [])
        self.assertIn(killable, defender.discard)
        self.assertEqual(attacker.combat, 3, "leftover combat must remain for the caller to spend")

    def test_attack_weakest_never_trades_a_lethal_hit_for_a_champion_kill(self):
        from hero_ai import attack_weakest

        killable = _non_guard_champion(max_health=4)
        attacker = HRPlayer("A")
        defender = HRPlayer("D")
        defender.hp = killable.health  # exactly lethal, and exactly enough to snipe
        defender.board = [BoardChampion(killable)]
        attacker.combat = killable.health

        attack_weakest(attacker, defender, guards=[])

        self.assertTrue(any(bc.card is killable for bc in defender.board),
                        "must not have sniped when the same combat was lethal")
        self.assertEqual(attacker.combat, killable.health)

    def test_attack_weakest_skips_a_champion_it_cannot_fully_kill(self):
        """Damage does not carry over between turns, so a non-lethal chip on a
        non-guard champion is pure waste; the AI should not spend combat on
        one it can't finish."""
        from hero_ai import attack_weakest

        tough = next(c for c in CARDS if c.card_type == "champion" and not c.guard and c.health >= 6)
        attacker = HRPlayer("A")
        defender = HRPlayer("D")
        defender.hp = 50
        defender.board = [BoardChampion(tough)]
        attacker.combat = tough.health - 1  # cannot finish it

        attack_weakest(attacker, defender, guards=[])

        self.assertEqual(defender.board[0].current_health, tough.health,
                         "must not chip a champion it cannot kill outright")
        self.assertEqual(attacker.combat, tough.health - 1, "combat must be untouched, not wasted")

    def test_attack_strongest_also_snipes(self):
        from hero_ai import attack_strongest

        killable = _non_guard_champion(max_health=4)
        attacker = HRPlayer("A")
        defender = HRPlayer("D")
        defender.hp = 50
        defender.board = [BoardChampion(killable)]
        attacker.combat = killable.health + 1

        attack_strongest(attacker, defender, guards=[])

        self.assertEqual(defender.board, [])
        self.assertIn(killable, defender.discard)

    def test_guards_are_still_cleared_before_any_snipe_is_considered(self):
        from hero_ai import attack_weakest

        guard = _guard_champion()
        killable = _non_guard_champion(max_health=4)
        attacker = HRPlayer("A")
        defender = HRPlayer("D")
        defender.hp = 50
        defender.board = [BoardChampion(guard), BoardChampion(killable)]
        attacker.combat = guard.health + killable.health + 5

        attack_weakest(attacker, defender, guards=[bc for bc in defender.board if bc.guard])

        self.assertNotIn(guard, [bc.card for bc in defender.board])
        self.assertNotIn(killable, [bc.card for bc in defender.board])


class TestEngineLevelSniping(unittest.TestCase):
    def test_resolve_combat_snipes_even_with_zero_guards_ever_present(self):
        """The caller used to gate ai_attack behind `if guards`, so a board
        with no guards at all never got a chance to snipe."""
        from hero_ai import attack_weakest
        from hero_engine import HRGame

        killable = _non_guard_champion(max_health=4)
        player = HRPlayer("P")
        opponent = HRPlayer("O")
        opponent.hp = 50
        opponent.board = [BoardChampion(killable)]
        player.combat = killable.health + 3

        game = HRGame(player, opponent, list(CARDS))
        game._resolve_combat(player, opponent, attack_weakest)

        self.assertEqual(opponent.board, [])
        self.assertIn(killable, opponent.discard)
        self.assertEqual(opponent.hp, 50 - 3, "leftover combat after the snipe should still hit face")


if __name__ == "__main__":
    unittest.main()


class TestRolloutPolicyLethalSafety(unittest.TestCase):
    """The MCTS default policy's combat branch used to pick the first
    priority-sorted attack_target action, where a champion's priority is
    10 - current_health and the player's is player.combat. Those are not on
    a comparable scale, so a weak champion could rank above lethal face
    damage and the rollout would snipe it instead of ending the game."""

    def test_rollout_policy_takes_lethal_over_a_low_health_champion(self):
        from web.bot import _heuristic_rollout_action
        from web.session import create_session

        weak = _non_guard_champion(max_health=3)
        session = create_session(seed=3)
        session.bot.board = [BoardChampion(weak)]
        session.bot.hp = 4
        session.active_player = "player"
        session.phase = "combat"
        session.player.combat = 4  # exactly lethal, and enough to snipe the champion

        action = _heuristic_rollout_action(session)
        self.assertEqual(action.get("target"), "player")

    def test_rollout_policy_still_snipes_when_not_lethal(self):
        from web.bot import _heuristic_rollout_action
        from web.session import create_session

        weak = _non_guard_champion(max_health=3)
        session = create_session(seed=3)
        session.bot.board = [BoardChampion(weak)]
        session.bot.hp = 50
        session.active_player = "player"
        session.phase = "combat"
        session.player.combat = 2

        action = _heuristic_rollout_action(session)
        self.assertEqual(action.get("target"), "champion",
                         "non-lethal case should be unaffected by the safety check")


class TestBenchProfileLethalSafety(unittest.TestCase):
    def test_profile_action_takes_lethal_over_sniping(self):
        from hero_mcts_bench import _profile_action
        from web.session import create_session

        weak = _non_guard_champion(max_health=3)
        session = create_session(seed=3)
        session.bot.board = [BoardChampion(weak)]
        session.bot.hp = 4
        session.active_player = "player"
        session.phase = "combat"
        session.player.combat = 4

        action = _profile_action(session, "balanced")
        self.assertEqual(action.get("target"), "player")
