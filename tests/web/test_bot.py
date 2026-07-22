from web.bot import choose_bot_action
from web.session import create_session


def test_bot_returns_legal_action():
    session = create_session(seed=3)
    action = choose_bot_action(session, budget_ms=20, algorithm="mcts")

    assert action["type"] in {"play_card", "buy_card", "expend_champion", "attack_target", "advance_phase"}
    assert "score" in action
    assert "iterations" in action
    assert "candidates" in action
    assert len(action["candidates"]) <= 5
