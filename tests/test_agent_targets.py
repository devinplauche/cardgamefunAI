"""Sacrifice/discard *targeting* as a real decision (AGENT_CHOOSES_TARGETS).

`defer_choices` and the pending-choices queue have existed for a while, but
only `hero_rl_env_v3.py` ever set the flag - the MCTS bot never did. So
`_find_worst_idx`, which fires ~14 times per game, chose which card to
sacrifice and which to discard on the bot's behalf. These are, by
`hero_engine.py`'s own comment, "the decisions a strong player spends the most
thought on".
"""
import pytest

import hero_engine
from hero_engine import GOLD, SHORTSWORD
from web.session import GameSession


@pytest.fixture
def agent_targets():
    before = hero_engine.AGENT_CHOOSES_TARGETS
    hero_engine.AGENT_CHOOSES_TARGETS = True
    yield
    hero_engine.AGENT_CHOOSES_TARGETS = before


def _session(hand_names, seed=11):
    session = GameSession(seed=seed, algorithm="heuristic", budget_ms=1)
    by_name = {c.name: c for c in session.cards}
    session.player.hand = [by_name[n] if n in by_name else n for n in hand_names]
    session.player.combat = 0
    session.player.gold = 0
    session.player.played_this_turn.clear()
    session.player.banish.clear()
    return session


def test_legacy_targeting_is_silent_and_unreachable():
    """What every existing baseline measured."""
    session = _session(["Death Touch"])
    session.player.hand += [GOLD, SHORTSWORD]
    death_touch = session.player.hand[0]
    session.play_card(death_touch.id)

    assert not session.player.pending_choices
    assert "resolve_choice" not in {a["type"] for a in session.legal_actions()}
    assert session.player.banish, "engine sacrificed something on its own"


def test_targeting_becomes_a_legal_action(agent_targets):
    session = _session(["Death Touch"])
    session.player.hand += [GOLD, SHORTSWORD]
    death_touch = session.player.hand[0]
    session.play_card(death_touch.id)

    assert session.player.pending_choices, "the effect must wait for a target"
    actions = session.legal_actions()
    assert {a["type"] for a in actions} == {"resolve_choice"}, (
        "a half-resolved effect must block everything else")

    labels = [a["label"] for a in actions]
    assert any("Gold" in label for label in labels)
    assert any("Shortsword" in label for label in labels)
    assert any("Decline" in label for label in labels), "'you may sacrifice'"


def test_the_agents_pick_is_honoured(agent_targets):
    session = _session(["Death Touch"])
    session.player.hand += [GOLD, SHORTSWORD]
    session.play_card(session.player.hand[0].id)

    chosen = next(a for a in session.legal_actions() if "Shortsword" in a["label"])
    session.resolve_choice_action(chosen["candidateIndex"])

    assert SHORTSWORD in session.player.banish
    assert GOLD in session.player.hand, "the heuristic would have taken the Gold"
    assert not session.player.pending_choices


def test_declining_is_reachable(agent_targets):
    session = _session(["Death Touch"])
    session.player.hand += [GOLD, SHORTSWORD]
    session.play_card(session.player.hand[0].id)

    decline = next(a for a in session.legal_actions() if a["candidateIndex"] < 0)
    session.resolve_choice_action(decline["candidateIndex"])

    assert not session.player.banish
    assert not session.player.pending_choices
    assert "play_card" in {a["type"] for a in session.legal_actions()}


def test_a_forced_discard_cannot_be_declined(agent_targets):
    """Elven Gift is "draw a card, then discard a card" - not optional."""
    session = _session(["Elven Gift"])
    session.player.hand += [GOLD, SHORTSWORD]
    session.play_card(session.player.hand[0].id)

    actions = session.legal_actions()
    assert actions and {a["type"] for a in actions} == {"resolve_choice"}
    assert not any(a["candidateIndex"] < 0 for a in actions), "discard is forced"


def test_bot_can_play_a_whole_turn_with_targeting_on(agent_targets):
    """The queue blocks every other action, so a bot that cannot answer it
    would deadlock. This is the check that matters before any A/B.

    The bot's hand is seeded with a sacrifice card and the choice is spied on,
    so the test fails loudly if it ever stops exercising the path rather than
    passing vacuously.
    """
    session = GameSession(seed=4, algorithm="mcts", budget_ms=20)
    by_name = {c.name: c for c in session.cards}
    session.bot.hand = [by_name["Death Touch"], GOLD, SHORTSWORD]
    session.active_player = "bot"

    seen = []
    original = session.legal_actions

    def spy():
        actions = original()
        if actions and actions[0]["type"] == "resolve_choice":
            seen.append(len(actions))
        return actions

    session.legal_actions = spy
    session.run_bot_turn()

    assert seen, "the bot never faced the decision; this test proved nothing"
    assert not session.bot.pending_choices, "bot left a choice unresolved"
    assert session.active_player == "player"


def test_tyrannor_sacrifice_is_a_two_pick_player_choice(agent_targets):
    """Tyrannor's "you may sacrifice up to two" enqueues one choice answered
    twice; declining stops early. The source names the card for the sheet."""
    session = _session(["Tyrannor, the Devourer"])
    session.player.hand += [GOLD, SHORTSWORD]
    session.player.discard = [GOLD]
    session.play_card(session.player.hand[0].id)

    champion = session.player.board[-1]
    session.expend_champion_action(str(champion.instance_id))

    assert len(session.player.pending_choices) == 1
    choice = session.player.pending_choices[0]
    assert choice["kind"] == "sacrifice" and choice["count"] == 2
    assert choice["zone"] == "hand_or_discard"
    assert choice["source"] == "Tyrannor, the Devourer"
    assert not session.player.banish, "nothing sacrificed until the player picks"

    actions = session.legal_actions()
    assert {a["type"] for a in actions} == {"resolve_choice"}, \
        "a half-resolved effect must block everything else"
    assert all(a.get("remaining") == 2 for a in actions)
    assert any(a["candidateIndex"] < 0 for a in actions), "'you may' is declinable"

    first = next(a for a in actions if a["candidateIndex"] >= 0)
    session.resolve_choice_action(first["candidateIndex"])
    assert len(session.player.pending_choices) == 1, "one pick left"
    assert len(session.player.banish) == 1

    actions = session.legal_actions()
    assert all(a.get("remaining") == 1 for a in actions), \
        "the sheet must know one pick is left"

    decline = next(a for a in actions if a["candidateIndex"] < 0)
    session.resolve_choice_action(decline["candidateIndex"])
    assert not session.player.pending_choices
    assert len(session.player.banish) == 1, "declining stops at one"


def test_bot_answers_a_multi_pick_sacrifice(agent_targets):
    """Tyrannor through the bot's own turn: it sacrifices the junk, declines
    the rest, and never leaves the choice hanging."""
    from hero_engine import BoardChampion
    session = GameSession(seed=4, algorithm="heuristic", budget_ms=20)
    by_name = {c.name: c for c in session.cards}
    good = next(c for c in session.cards if c.get("gold", 0) > 0 and c.cost >= 2)
    session.bot.hand = []
    session.bot.discard = [GOLD, SHORTSWORD, good]
    champion = BoardChampion(by_name["Tyrannor, the Devourer"])
    session.bot.board.append(champion)
    session.active_player = "bot"

    session.expend_champion_action(str(champion.instance_id))
    assert session.bot.pending_choices, "expected the two-pick choice"

    session.run_bot_turn()

    assert not session.bot.pending_choices, "bot left a choice unresolved"
    assert len(session.bot.banish) == 2, \
        f"bot should thin exactly the junk, banished {[c.name for c in session.bot.banish]}"
    assert good in session.bot.discard, "the good card must survive"
