"""Multiplayer game persistence: pickled GameSession rows plus invite codes."""

from __future__ import annotations

import pickle
import secrets
import string
import uuid
from copy import deepcopy

from hero_engine import HRCard, BoardChampion

from web import auth, db

_CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"  # no lookalikes


def _new_code() -> str:
    for _ in range(20):
        code = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(6))
        if not db.query_one(
            f"SELECT id FROM games WHERE invite_code = {db.PH}", (code,)
        ):
            return code
    raise RuntimeError("could not mint an invite code")


def _serialize(session) -> bytes:
    # Never persist a live event listener (unpicklable); human games never set
    # one, but a bot turn interrupted mid-stream could.
    session._event_listener = None
    return pickle.dumps(session, protocol=pickle.HIGHEST_PROTOCOL)


def _deserialize(blob: bytes):
    return pickle.loads(blob)


def create_game(host_id: str, session) -> dict:
    game_id = uuid.uuid4().hex
    code = _new_code()
    now = db.now()
    db.execute(
        f"INSERT INTO games (id, invite_code, host_id, guest_id, status, "
        f"turn_count, session, created_at, updated_at) VALUES "
        f"({db.PH}, {db.PH}, {db.PH}, {db.PH}, {db.PH}, {db.PH}, {db.PH}, {db.PH}, {db.PH})",
        (game_id, code, host_id, None, "waiting", 0, _serialize(session), now, now),
    )
    return {"id": game_id, "inviteCode": code}


def get_game(game_id: str) -> dict | None:
    row = db.query_one(f"SELECT * FROM games WHERE id = {db.PH}", (game_id,))
    if not row:
        return None
    row["session"] = _deserialize(bytes(row["session"]))
    return row


def get_by_code(code: str) -> dict | None:
    row = db.query_one(
        f"SELECT * FROM games WHERE invite_code = {db.PH}", (code.strip().upper(),)
    )
    if not row:
        return None
    row["session"] = _deserialize(bytes(row["session"]))
    return row


def save_game(game_id: str, session, bump_turn: bool = True) -> None:
    now = db.now()
    if bump_turn:
        db.execute(
            f"UPDATE games SET session = {db.PH}, turn_count = turn_count + 1, "
            f"updated_at = {db.PH} WHERE id = {db.PH}",
            (_serialize(session), now, game_id),
        )
    else:
        db.execute(
            f"UPDATE games SET session = {db.PH}, updated_at = {db.PH} WHERE id = {db.PH}",
            (_serialize(session), now, game_id),
        )


def join_game(game_id: str, guest_id: str, session) -> bool:
    """Atomically claim a waiting game for a guest.

    The conditional UPDATE makes the claim race-safe: two guests racing to
    join the same code cannot both succeed, since only one row transitions
    out of 'waiting'. Returns True when this caller won the game.
    """
    changed = db.execute(
        f"UPDATE games SET guest_id = {db.PH}, status = 'playing', "
        f"session = {db.PH}, updated_at = {db.PH} "
        f"WHERE id = {db.PH} AND status = 'waiting'",
        (guest_id, _serialize(session), db.now(), game_id),
    )
    return changed == 1


def finish_game(game_id: str) -> None:
    db.execute(
        f"UPDATE games SET status = 'finished', updated_at = {db.PH} WHERE id = {db.PH}",
        (db.now(), game_id),
    )


# ---- bot-match sessions -------------------------------------------------
# Bot games live here (pickled GameSession rows keyed by session id) instead
# of an in-memory dict, so a server restart or deploy cannot wipe a live
# match: every request loads the session fresh from the database and saves
# it back after mutating it.


def create_bot_session(session) -> None:
    now = db.now()
    db.execute(
        f"INSERT INTO bot_sessions (session_id, state, created_at, updated_at) "
        f"VALUES ({db.PH}, {db.PH}, {db.PH}, {db.PH})",
        (session.session_id, _serialize(session), now, now),
    )


def get_bot_session(session_id: str):
    row = db.query_one(
        f"SELECT * FROM bot_sessions WHERE session_id = {db.PH}", (session_id,)
    )
    if not row:
        return None
    return _deserialize(bytes(row["state"]))


def save_bot_session(session) -> None:
    now = db.now()
    changed = db.execute(
        f"UPDATE bot_sessions SET state = {db.PH}, updated_at = {db.PH} "
        f"WHERE session_id = {db.PH}",
        (_serialize(session), now, session.session_id),
    )
    if changed == 0:
        db.execute(
            f"INSERT INTO bot_sessions (session_id, state, created_at, updated_at) "
            f"VALUES ({db.PH}, {db.PH}, {db.PH}, {db.PH})",
            (session.session_id, _serialize(session), now, now),
        )


def delete_bot_session(session_id: str) -> None:
    db.execute(f"DELETE FROM bot_sessions WHERE session_id = {db.PH}", (session_id,))


def cleanup_bot_sessions(max_age_days: float = 7) -> int:
    """Delete bot sessions untouched for longer than the TTL; returns count."""
    cutoff = db.now() - max_age_days * 24 * 3600
    return db.execute(
        f"DELETE FROM bot_sessions WHERE updated_at < {db.PH}", (cutoff,)
    )


def participant_side(game: dict, user_id: str) -> str | None:
    """Engine side ('player' = host, 'bot' = guest) for this user, if any."""
    if user_id == game["host_id"]:
        return "player"
    if game["guest_id"] and user_id == game["guest_id"]:
        return "bot"
    return None


def list_for_user(user_id: str) -> list[dict]:
    rows = db.query_all(
        f"SELECT id, invite_code, host_id, guest_id, status, turn_count, updated_at "
        f"FROM games WHERE host_id = {db.PH} OR guest_id = {db.PH} "
        f"ORDER BY updated_at DESC",
        (user_id, user_id),
    )
    out = []
    for row in rows:
        opponent_id = row["guest_id"] if row["host_id"] == user_id else row["host_id"]
        opponent = auth.public_user(opponent_id) if opponent_id else None
        out.append(
            {
                "id": row["id"],
                "inviteCode": row["invite_code"],
                "status": row["status"],
                "opponent": opponent["username"] if opponent else None,
                "updatedAt": row["updated_at"],
            }
        )
    return out


# ---- single-step Undo: pre-action snapshots -------------------------------
# Pure snapshot/restore for one level of Undo. The integration owner calls
# snapshot() before each player mutation and keeps the most recent dict;
# POST /api/games/{id}/undo calls restore() with it. Snapshots are plain
# JSON-serializable dicts (never pickle) so they can be persisted in a TEXT
# column or round-tripped through the client. restore() rebuilds the mutable
# state in place, so the same session object keeps working afterwards.
#
# Captured: everything a player mutation can change - both seats' zones
# (deck, hand, discard, banish, board, played_this_turn, pending ally
# queues), gold/combat/hp, the market (pool, row, Fire Gem pile), turn
# number, active player, phase, winner, per-turn flags, pending choices, the
# RNG state, and the log/history the mutation appended to.
# Deliberately NOT captured: read-only card definitions (session.cards),
# construction constants (session_id, seed, ...), the bot pipeline's private
# search state (last_bot_insight, opponent_purchase_observations - written
# only by bot turns, never by a player action), and the live event listener
# (a callable, never persisted - see _serialize).


def _snapshot_card(card: HRCard) -> dict:
    # Full per-copy serialisation, uid included: two copies of one card share
    # card.id but are distinct physical cards (ally_used_this_turn is keyed
    # by uid), so id-keyed lookup would collapse them.
    return {
        "id": card.id,
        "name": card.name,
        "cost": card.cost,
        "faction": card.faction,
        "card_type": card.card_type,
        "subtypes": deepcopy(card.subtypes),
        "guard": card.guard,
        "health": card.health,
        "effects": deepcopy(card.effects),
        "text": card.text,
        "uid": card.uid,
    }


def _restore_card(data: dict, memo: dict) -> HRCard:
    """Rebuild one HRCard, memoised by uid so shared references stay shared.

    One physical card can appear in several captured places at once (e.g.
    the played card referenced by a pending_per_champion entry). Rebuilding
    a single object per uid preserves those identity relationships exactly.
    """
    uid = data["uid"]
    card = memo.get(uid)
    if card is None:
        card = HRCard(
            id=data["id"],
            name=data["name"],
            cost=data["cost"],
            faction=data["faction"],
            card_type=data["card_type"],
            subtypes=deepcopy(data["subtypes"]),
            guard=data["guard"],
            health=data["health"],
            effects=deepcopy(data["effects"]),
            text=data["text"],
            uid=uid,
        )
        memo[uid] = card
    return card


def _snapshot_champion(champion: BoardChampion) -> dict:
    return {
        "card": _snapshot_card(champion.card),
        "current_health": champion.current_health,
        "exhausted": champion.exhausted,
        "guard": champion.guard,
        "instance_id": champion.instance_id,
    }


def _restore_champion(data: dict, memo: dict) -> BoardChampion:
    champion = BoardChampion.__new__(BoardChampion)
    champion.card = _restore_card(data["card"], memo)
    champion.current_health = data["current_health"]
    champion.exhausted = data["exhausted"]
    champion.guard = data["guard"]
    # Preserved, not regenerated: the UI addresses champions by instance_id,
    # and the process-global counter only moves forward, so a restored id
    # can never collide with a later one (mirrors _copy_champion).
    champion.instance_id = data["instance_id"]
    return champion


def _snapshot_rng(rng) -> dict:
    version, ints, gauss = rng.getstate()
    return {"version": version, "ints": list(ints), "gauss": gauss}


def _restore_rng(rng, data: dict) -> None:
    rng.setstate((data["version"], tuple(data["ints"]), data["gauss"]))


def _snapshot_player(player) -> dict:
    return {
        "hp": player.hp,
        "gold": player.gold,
        "combat": player.combat,
        "deck": [_snapshot_card(c) for c in player.deck],
        "hand": [_snapshot_card(c) for c in player.hand],
        "discard": [_snapshot_card(c) for c in player.discard],
        "banish": [_snapshot_card(c) for c in player.banish],
        "board": [_snapshot_champion(c) for c in player.board],
        "played_this_turn": [_snapshot_card(c) for c in player.played_this_turn],
        "pending_ally": [_snapshot_card(c) for c in player.pending_ally],
        "available_ally_triggers": [
            _snapshot_card(c) for c in player.available_ally_triggers
        ],
        "ally_used_this_turn": sorted(player.ally_used_this_turn),
        "pending_per_champion": [
            {
                "card": _snapshot_card(e["card"]),
                "resource": e["resource"],
                "per_unit": e["per_unit"],
                "credited": e["credited"],
            }
            for e in player.pending_per_champion
        ],
        "pending_prepares": player.pending_prepares,
        "pending_choices": deepcopy(player.pending_choices),
        "actions_played": player.actions_played,
        "cards_bought": player.cards_bought,
        "next_buy_to_hand": player.next_buy_to_hand,
        "next_buy_to_top": player.next_buy_to_top,
        "next_buy_to_top_action_only": player.next_buy_to_top_action_only,
        "defer_choices": player.defer_choices,
        "log_effects": player.log_effects,
        "effect_log": list(player.effect_log),
    }


def _restore_player(player, data: dict, memo: dict, rng) -> None:
    player.hp = data["hp"]
    player.gold = data["gold"]
    player.combat = data["combat"]
    player.deck = [_restore_card(c, memo) for c in data["deck"]]
    player.hand = [_restore_card(c, memo) for c in data["hand"]]
    player.discard = [_restore_card(c, memo) for c in data["discard"]]
    player.banish = [_restore_card(c, memo) for c in data["banish"]]
    player.board = [_restore_champion(c, memo) for c in data["board"]]
    player.played_this_turn = [_restore_card(c, memo) for c in data["played_this_turn"]]
    player.pending_ally = [_restore_card(c, memo) for c in data["pending_ally"]]
    player.available_ally_triggers = [
        _restore_card(c, memo) for c in data["available_ally_triggers"]
    ]
    player.ally_used_this_turn = set(data["ally_used_this_turn"])
    player.pending_per_champion = [
        {
            "card": _restore_card(e["card"], memo),
            "resource": e["resource"],
            "per_unit": e["per_unit"],
            "credited": e["credited"],
        }
        for e in data["pending_per_champion"]
    ]
    player.pending_prepares = data["pending_prepares"]
    player.pending_choices = deepcopy(data["pending_choices"])
    player.actions_played = data["actions_played"]
    player.cards_bought = data["cards_bought"]
    player.next_buy_to_hand = data["next_buy_to_hand"]
    player.next_buy_to_top = data["next_buy_to_top"]
    player.next_buy_to_top_action_only = data["next_buy_to_top_action_only"]
    player.defer_choices = data["defer_choices"]
    player.log_effects = data["log_effects"]
    player.effect_log = list(data["effect_log"])
    player._rng = rng


def _snapshot_market(market) -> dict:
    return {
        "pool": [_snapshot_card(c) for c in market.pool],
        "row": [_snapshot_card(c) if c is not None else None for c in market.row],
        "fire_gems_remaining": market.fire_gems_remaining,
    }


def _restore_market(market, data: dict, memo: dict) -> None:
    market.pool = [_restore_card(c, memo) for c in data["pool"]]
    market.row = [
        _restore_card(c, memo) if c is not None else None for c in data["row"]
    ]
    market.fire_gems_remaining = data["fire_gems_remaining"]


def _unique_rngs(session) -> tuple[list, dict[int, int]]:
    """RNG objects in discovery order, deduped: the two seats normally share
    the session RNG, so there is usually exactly one."""
    rngs: list = []
    index: dict[int, int] = {}
    for holder in (session.rng, session.player._rng, session.bot._rng):
        key = id(holder)
        if key not in index:
            index[key] = len(rngs)
            rngs.append(holder)
    return rngs, index


def snapshot(session) -> dict:
    """Capture the full mutable game state as a plain JSON-serializable dict.

    Call before each player mutation; hand the dict to restore() to undo.
    """
    rngs, rng_index = _unique_rngs(session)
    return {
        "turn_number": session.turn_number,
        "active_player": session.active_player,
        "phase": session.phase,
        "winner": session.winner,
        "history_sequence": session.history_sequence,
        "bot_is_human": session.bot_is_human,
        "record_history": session.record_history,
        "rngs": [_snapshot_rng(r) for r in rngs],
        "player_rng": rng_index[id(session.player._rng)],
        "bot_rng": rng_index[id(session.bot._rng)],
        "player": _snapshot_player(session.player),
        "bot": _snapshot_player(session.bot),
        "market": _snapshot_market(session.market),
        "log": deepcopy(session.log),
        "history": deepcopy(session.history),
    }


def restore(session, snap: dict):
    """Restore the mutable game state from snapshot() in place.

    Rebuilds every zone from the snapshot so the session is byte-equivalent
    to the captured state (a fresh snapshot() afterwards compares equal).
    Returns the session for chaining.
    """
    memo: dict[str, HRCard] = {}
    live_rngs, _ = _unique_rngs(session)
    for holder, state in zip(live_rngs, snap["rngs"]):
        _restore_rng(holder, state)
    session.turn_number = snap["turn_number"]
    session.active_player = snap["active_player"]
    session.phase = snap["phase"]
    session.winner = snap["winner"]
    session.history_sequence = snap["history_sequence"]
    session.bot_is_human = snap["bot_is_human"]
    session.record_history = snap["record_history"]
    _restore_market(session.market, snap["market"], memo)
    _restore_player(
        session.player, snap["player"], memo, live_rngs[snap["player_rng"]]
    )
    _restore_player(session.bot, snap["bot"], memo, live_rngs[snap["bot_rng"]])
    # Keep the engine's back-references consistent: sacrifice routing sends
    # Fire Gems to the live market pile, and players draw from the live RNG.
    session.player.market = session.market
    session.bot.market = session.market
    session.log = deepcopy(snap["log"])
    session.history = deepcopy(snap["history"])
    return session
