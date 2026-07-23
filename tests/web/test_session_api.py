from web.session import create_session


def test_session_can_create_and_serialize_state():
    session = create_session(seed=7)
    state = session.get_state()

    assert state["turnNumber"] == 1
    assert state["phase"] == "play"
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
