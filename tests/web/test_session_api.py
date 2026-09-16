from web.session import create_session

import pytest

import hero_engine


@pytest.fixture
def agent_targets():
    """Mirror production: backend.main() enables AGENT_CHOOSES_TARGETS, so
    real sessions defer choices to the player instead of auto-resolving."""
    before = hero_engine.AGENT_CHOOSES_TARGETS
    hero_engine.AGENT_CHOOSES_TARGETS = True
    yield
    hero_engine.AGENT_CHOOSES_TARGETS = before


def test_session_can_create_and_serialize_state():
    session = create_session(seed=7)
    state = session.get_state()

    assert state["turnNumber"] == 1
    # The engine now opens in the faithful Main phase (see
    # web/session.py: MAIN_PHASE); the old fixed phases remain
    # settable for legacy harnesses and baseline reproduction.
    assert state["phase"] == "main"
    assert state["activePlayer"] == "player"
    assert state["player"]["name"] == "Player"
    assert state["bot"]["name"] == "Bot"
    assert state["player"]["handCount"] == 3
    assert state["bot"]["handCount"] == 5
    assert len(state["market"]["row"]) == 5


def test_session_legal_actions_are_present():
    session = create_session(seed=11)
    state = session.get_state()

    assert any(action["type"] == "play_card" for action in state["legalActions"])
    assert any(action["type"] == "advance_phase" for action in state["legalActions"])


def test_market_cards_preserve_rules_text():
    session = create_session(seed=7)
    state = session.get_state()

    assert any(card and card["text"] for card in state["market"]["row"])


def test_session_history_and_log_capture_bot_candidates():
    session = create_session(seed=13)
    session.end_turn()
    state = session.run_bot_turn()

    assert state["history"]
    assert state["history"][-1]["state"]["botInsight"] is not None
    assert any((entry.get("botInsight") or {}).get("candidates") for entry in state["log"])


def test_invalid_buy_index_does_not_spend_gold():
    session = create_session(seed=7)
    session.phase = "buy"
    session.player.gold = 4

    try:
        session.buy_card_action(-1)
    except ValueError:
        pass
    else:
        raise AssertionError("negative market index should be rejected")

    assert session.player.gold == 4


def test_recycle_choice_is_offered_and_declinable(agent_targets):
    """Smash and Grab: the player picks the recycled card and may decline."""
    from hero_engine import GOLD, DAGGER

    session = create_session(seed=21)
    smash = next(c for c in session.cards if c.name == "Smash and Grab")
    session.player.hand = [smash]
    session.player.discard = [GOLD, DAGGER]
    deck_before = [c.name for c in session.player.deck]

    session.play_card(smash.id)

    actions = session.legal_actions()
    assert actions and all(a["type"] == "resolve_choice" for a in actions)
    assert {a["kind"] for a in actions} == {"recycle"}
    assert any(a["candidateIndex"] == -1 for a in actions), \
        "'you may' recycle must be declinable"

    # Declining leaves the discard pile and the deck untouched.
    session.resolve_choice_action(-1)
    assert [c.name for c in session.player.discard] == ["Gold", "Dagger"]
    assert [c.name for c in session.player.deck] == deck_before
    assert not session.player.pending_choices


def test_reanimate_choice_offers_champions_only_and_cannot_be_declined(agent_targets):
    """Varrick: the player picks which champion returns; no declining."""
    from hero_engine import GOLD, BoardChampion

    session = create_session(seed=22)
    varrick = next(c for c in session.cards if c.name == "Varrick, the Necromancer")
    cron = next(c for c in session.cards
                if c.card_type == "champion" and c.id != varrick.id)
    session.player.board = [BoardChampion(varrick)]
    session.player.discard = [GOLD, cron]

    session.expend_champion_action(str(session.player.board[0].instance_id))

    actions = session.legal_actions()
    assert actions and all(a["type"] == "resolve_choice" for a in actions)
    assert {a["kind"] for a in actions} == {"reanimate"}
    assert not any(a["candidateIndex"] == -1 for a in actions), \
        "reanimate has no 'may' - it cannot be declined"
    offered = [a for a in actions if a["candidateIndex"] >= 0]
    assert len(offered) == 1, "only the champion is offered, not the Gold"

    session.resolve_choice_action(0)
    assert session.player.deck[0] is cron
    assert not session.player.pending_choices
