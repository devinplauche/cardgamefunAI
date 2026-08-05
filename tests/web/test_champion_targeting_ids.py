"""Champions are addressed by instance_id, never by card id.

Found by a human playing the web UI, not by any benchmark - and it could not
have been found by one. Every benchmark and A/B in this repo drives the engine
directly through `session.legal_actions()` / `apply_action()`, which pass the
engine's own action dicts straight back in. The web UI is the only consumer
that *constructs* an action from a rendered view, so it is the only place a
wrong identifier can be introduced, and 2800+ benchmark games never touched
that path.

The bug: `_champion_view` emits `instanceId`, `ChampionView` in types.ts did
not declare it, and App.tsx therefore fell back to `champion.id` - the *card*
id. `expend_champion_action` and `attack_target_action` both match on
`str(instance_id)`, so every lookup failed:

    Expend Lys      -> "Champion not found"
    Attack a guard  -> "Champion not found or not a legal target"

One missing field broke champion expend AND all champion-targeted combat,
which between them make the game unplayable past the first champion.

These tests pin the engine contract. The frontend fix is a matching
`instanceId` on ChampionView plus passing it at the two call sites.
"""
import unittest

from hero_engine import BoardChampion, load_hero_cards
from web.session import create_session

CARDS = {card.name: card for card in load_hero_cards("data/hero_realms_cards.json")}


class TestChampionAddressing(unittest.TestCase):
    def _session_with_champion(self, name="Lys, the Unseen", phase="champion"):
        session = create_session(seed=7)
        session.player.board.append(BoardChampion(CARDS[name]))
        session.active_player = "player"
        session.phase = phase
        return session, session.player.board[0]

    def test_expend_rejects_the_card_id(self):
        """The exact failure a human hit in the UI."""
        session, champion = self._session_with_champion()
        with self.assertRaisesRegex(ValueError, "Champion not found"):
            session.expend_champion_action(champion.card.id)

    def test_expend_accepts_the_instance_id(self):
        session, champion = self._session_with_champion()
        session.expend_champion_action(str(champion.instance_id))
        self.assertTrue(session.player.board[0].exhausted)

    def test_attack_rejects_the_card_id(self):
        session, _ = self._session_with_champion(phase="combat")
        session.player.board.clear()
        session.bot.board.append(BoardChampion(CARDS["Lys, the Unseen"]))
        session.player.combat = 10
        target = session.bot.board[0]
        with self.assertRaisesRegex(ValueError, "Champion not found"):
            session.attack_target_action("champion", target.card.id)

    def test_attack_accepts_the_instance_id(self):
        session, _ = self._session_with_champion(phase="combat")
        session.player.board.clear()
        session.bot.board.append(BoardChampion(CARDS["Lys, the Unseen"]))
        session.player.combat = 10
        target = session.bot.board[0]
        session.attack_target_action("champion", str(target.instance_id))
        self.assertEqual(session.bot.board, [], "a stunned champion leaves the board")

    def test_legal_actions_advertise_the_instance_id(self):
        """Whatever legal_actions() puts in championId is what a client must
        send back - this is the contract the UI has to honour."""
        session, champion = self._session_with_champion()
        expends = [a for a in session.legal_actions() if a["type"] == "expend_champion"]
        self.assertTrue(expends)
        for action in expends:
            self.assertEqual(action["championId"], str(champion.instance_id))
            self.assertNotEqual(action["championId"], champion.card.id)

    def test_two_copies_of_one_card_are_separately_addressable(self):
        """Why instance_id exists at all: a card printed in multiple copies can
        appear twice on one board, and card id cannot tell them apart."""
        session = create_session(seed=7)
        card = CARDS["Lys, the Unseen"]
        session.player.board.extend([BoardChampion(card), BoardChampion(card)])
        session.active_player = "player"
        session.phase = "champion"
        first, second = session.player.board
        self.assertEqual(first.card.id, second.card.id)
        self.assertNotEqual(first.instance_id, second.instance_id)

        session.expend_champion_action(str(first.instance_id))
        self.assertTrue(first.exhausted)
        self.assertFalse(second.exhausted, "expending one copy must not exhaust the other")


class TestFireGemIsReachable(unittest.TestCase):
    """Fire Gem is marketIndex 5 but is not part of market.row, which holds only
    the 5 visible slots. The UI rendered tiles from market.row alone, so its
    `index === 5 ? 'Buy Fire Gem'` branch was unreachable and a human could
    never buy one - while the bot buys ~2.9 per game via the engine API."""

    def test_market_row_has_five_slots_and_excludes_fire_gem(self):
        session = create_session(seed=7)
        self.assertEqual(len(session.market.row), 5)
        self.assertNotIn("fire_gem", [c.id for c in session.market.row if c])

    def test_index_five_buys_a_fire_gem(self):
        session = create_session(seed=7)
        session.active_player = "player"
        session.phase = "buy"
        session.player.gold = 2
        before = session.market.fire_gems_remaining
        session.buy_card_action(5)
        self.assertEqual(session.market.fire_gems_remaining, before - 1)
        self.assertIn("fire_gem", [c.id for c in session.player.discard])

    def test_fire_gem_is_offered_in_legal_actions_at_two_gold(self):
        session = create_session(seed=7)
        session.active_player = "player"
        session.phase = "buy"
        session.player.gold = 2
        indices = [int(a["marketIndex"]) for a in session.legal_actions()
                   if a["type"] == "buy_card"]
        self.assertIn(5, indices)


if __name__ == "__main__":
    unittest.main()
