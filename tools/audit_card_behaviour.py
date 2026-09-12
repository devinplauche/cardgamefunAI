"""Audit what each card's ability actually *does*, and *when*, against its
printed text - by driving the real engine and measuring state deltas.

Why this exists, when tools/audit_cards.py already audits the card set: that
one compares printed text to the parsed `effects` dict. It is a data lint and
is structurally blind to timing. Both ally bugs found in August 2026 had
completely correct card data - `ally_faction` and `ally_combat` were right on
every card - and were entirely about *when* and *how often* the engine fired
them:

  * `has_ally` excluded "the card itself" by object identity, and
    load_hero_cards shares one HRCard across all printed copies, so a second
    copy of a card never counted as a faction partner (12 of the 36 ally
    cards, all the common 2-3x ones).
  * a champion's ally was paid inside expend_champion, so it required
    expending, never fired on the turn the champion was played, and re-paid on
    every later expend.

Neither was visible to audit_cards.py, to the 380-odd unit tests, or to
thousands of benchmark games. Both were found by a human playing the UI. This
closes that gap mechanically.

Two halves:

  MAGNITUDES - parse the printed text into per-trigger-point expectations and
  compare them against measured deltas. Clauses the parser cannot reduce to a
  number are reported as UNPARSED, never silently skipped: a lint that quietly
  drops the hard cards is the exact false comfort that let the bugs above sit
  under a green suite.

  TIMING INVARIANTS - card-agnostic properties checked on every applicable
  card. These are the half that would have caught both bugs, and they need no
  text parsing at all.

Usage:
    python tools/audit_card_behaviour.py            # full report
    python tools/audit_card_behaviour.py --failures # only problems
    python tools/audit_card_behaviour.py --card "Cult Priest"
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from hero_engine import (  # noqa: E402
    GOLD,
    BoardChampion,
    HRCard,
    load_hero_cards,
)
from web.session import create_session  # noqa: E402

CARDS = load_hero_cards(str(REPO / "data" / "hero_realms_cards.json"))
BY_NAME: dict[str, HRCard] = {}
for _c in CARDS:
    BY_NAME.setdefault(_c.name, _c)


# --------------------------------------------------------------------------
# Printed-text parsing
# --------------------------------------------------------------------------

ALLY_HEAD = re.compile(r"^\{(Imperial|Necros|Wild|Guild) Ally\}\s*:?", re.I)
SACRIFICE_HEAD = re.compile(r"^\{Sacrifice\}\s*:?", re.I)
EXPEND_HEAD = re.compile(r"^\{Expend\}\s*:?", re.I)

GAIN = re.compile(r"\{?Gain\s+\{?(\d+)\s*(combat|gold|health)\}?\}?", re.I)
GAIN_BRACED = re.compile(r"\{(\d+)\s+(combat|gold|health)\}", re.I)
DRAW_ONE = re.compile(r"draw a card", re.I)
DRAW_N = re.compile(r"draw (two|three|four|\d+) cards", re.I)
WORD_NUM = {"two": 2, "three": 3, "four": 4}

#: Clauses that are not flat amounts but *are* mechanically checkable: each
#: names a behaviour the harness knows how to set up and observe. Recognising
#: them here is what moves a card from "unaudited" to "checked" - the point of
#: the tool is coverage, and a clause parked in `unparsed` is coverage lost.
OPP_DISCARD = re.compile(r"target opponent discards? (a|one|\d+) cards?", re.I)
MANDATORY_STUN = re.compile(r"^stun target champion$", re.I)
TO_HAND = re.compile(r"put the next card you acquire this turn into your hand", re.I)
TO_TOP = re.compile(r"put the next (card|action) you acquire this turn on top", re.I)
PREPARE = re.compile(r"^prepare a champion$", re.I)
#: "+{2 combat} for each champion you have in play",
#: "+{1 combat} for each other guard you have in play",
#: "Gain {2 health} for each champion you have in play"
SCALES = re.compile(
    r"(?:\+|gain\s+)\{?(\d+)\s*(combat|health)\}?\s+for each\s+(other\s+)?"
    r"(?:\{)?(champion|guard|wild)(?:\})?",
    re.I,
)

#: Clauses that are real abilities but do not reduce to a flat resource
#: amount. Matched only so they can be reported as unparsed rather than
#: silently dropped.
CONDITIONAL_MARKERS = (
    "for each",
    "you may",
    "target opponent",
    "prepare",
    "put it on top",
    "on top of your deck",
    "into your hand",
    "stun target",
    "up to",
    "if you do",
    "each other",
    # a clause that also discards is not a flat hand-size change
    "discard",
)


@dataclass
class Section:
    """One printed section of a card, and what it should do when it fires."""

    kind: str                       # "play" | "expend" | "ally" | "sacrifice"
    body: str
    flat: dict[str, int] = field(default_factory=dict)
    #: "gain 1 gold *or* gain 1 combat" - exactly one branch may fire. Kept
    #: separate from `flat` because summing the branches is precisely the
    #: double-count this is meant to detect.
    choices: list[dict[str, int]] = field(default_factory=list)
    #: Non-numeric but checkable behaviours, as (kind, *args) - see
    #: _check_behaviours.
    behaviours: list[tuple] = field(default_factory=list)
    unparsed: list[str] = field(default_factory=list)


def _strip_markup(text: str) -> str:
    return re.sub(r"<(?!hr)[^>]*>", "", text)


def parse_sections(card: HRCard) -> list[Section]:
    """Split printed text into sections and reduce each to flat amounts."""
    text = _strip_markup(card.text or "")
    out: list[Section] = []
    for raw in re.split(r"<hr\s*/?>", text, flags=re.I):
        part = raw.strip()
        if not part:
            continue
        if ALLY_HEAD.match(part):
            kind, body = "ally", ALLY_HEAD.sub("", part).strip()
        elif SACRIFICE_HEAD.match(part):
            kind, body = "sacrifice", SACRIFICE_HEAD.sub("", part).strip()
        elif EXPEND_HEAD.match(part):
            kind, body = "expend", EXPEND_HEAD.sub("", part).strip()
        else:
            kind, body = "play", part
        section = Section(kind=kind, body=body)
        _reduce(section)
        out.append(section)
    return out


def _clause_amounts(clause: str) -> dict[str, int]:
    """Flat resource amounts stated in one clause, or {} if it states none."""
    amounts: dict[str, int] = {}
    for pattern in (GAIN, GAIN_BRACED):
        for amount, resource in pattern.findall(clause):
            amounts[resource] = amounts.get(resource, 0) + int(amount)
    if DRAW_ONE.search(clause):
        amounts["draw"] = amounts.get("draw", 0) + 1
    for word in DRAW_N.findall(clause):
        n = WORD_NUM.get(word.lower()) or (int(word) if word.isdigit() else 0)
        if n:
            amounts["draw"] = amounts.get("draw", 0) + n
    return amounts


def _reduce(section: Section) -> None:
    """Fill section.flat with unconditional amounts; log the rest as unparsed."""
    for clause in [c.strip() for c in re.split(r"[\n.]", section.body) if c.strip()]:
        lowered = clause.lower()

        # Named behaviours the harness can set up and observe directly.
        if (m := SCALES.search(clause)):
            section.behaviours.append(
                ("scale", int(m.group(1)), m.group(2).lower(), m.group(4).lower()))
            # A clause like "{Gain 2 combat} +{1 combat} for each other guard"
            # also states a flat part; take it from the text before the "+".
            head = clause[:m.start()]
            for resource, value in _clause_amounts(head).items():
                section.flat[resource] = section.flat.get(resource, 0) + value
            continue
        if (m := OPP_DISCARD.search(clause)):
            word = m.group(1).lower()
            section.behaviours.append(
                ("opp_discard", 1 if word in ("a", "one") else int(word)))
            continue
        if MANDATORY_STUN.match(clause):
            section.behaviours.append(("stun",))
            continue
        if TO_HAND.search(clause):
            section.behaviours.append(("to_hand",))
            continue
        if (m := TO_TOP.search(clause)):
            section.behaviours.append(("to_top", m.group(1).lower() == "action"))
            continue
        if PREPARE.match(clause):
            section.behaviours.append(("prepare",))
            continue

        # "+{2 combat} for each champion" is conditional; do not take the number.
        if any(marker in lowered for marker in CONDITIONAL_MARKERS):
            section.unparsed.append(clause)
            continue

        # "{Gain 1 gold} or {Gain 1 combat}" - a choice, not a sum.
        if re.search(r"\bor\b", clause, re.I):
            branches = [_clause_amounts(part)
                        for part in re.split(r"\bor\b", clause, flags=re.I)]
            live = [b for b in branches if b]
            if len(live) > 1:
                section.choices.extend(live)
                continue

        amounts = _clause_amounts(clause)
        if amounts:
            for resource, value in amounts.items():
                section.flat[resource] = section.flat.get(resource, 0) + value
        else:
            section.unparsed.append(clause)


# --------------------------------------------------------------------------
# Observation harness
# --------------------------------------------------------------------------

MEASURED = (
    "combat", "gold", "hp", "hand", "deck", "discard", "banish", "board",
    "next_buy_to_hand", "next_buy_to_top", "next_buy_to_top_action_only",
    "pending_prepares",
    "opp_hand", "opp_hp", "opp_board",
)


def snapshot(session) -> dict[str, int]:
    me, them = session.player, session.bot
    return {
        "combat": me.combat,
        "gold": me.gold,
        "hp": me.hp,
        "hand": len(me.hand),
        "deck": len(me.deck),
        "discard": len(me.discard),
        "banish": len(me.banish),
        "board": len([c for c in me.board if c.alive]),
        "next_buy_to_hand": int(me.next_buy_to_hand),
        "next_buy_to_top": int(me.next_buy_to_top),
        "next_buy_to_top_action_only": int(me.next_buy_to_top_action_only),
        "pending_prepares": me.pending_prepares,
        "opp_hand": len(them.hand),
        "opp_hp": them.hp,
        "opp_board": len([c for c in them.board if c.alive]),
    }


def delta(before: dict[str, int], after: dict[str, int]) -> dict[str, int]:
    return {k: after[k] - before[k] for k in MEASURED if after[k] != before[k]}


def partner_for(faction: str) -> HRCard | None:
    """A card of `faction` to sit in play as an ally partner.

    Placed straight into `played_this_turn` rather than played, so it applies
    no effects of its own, and it is not a champion, so it does not change the
    champion count that "for each champion" clauses scale on. Both matter:
    the partner must be inert or it contaminates the very delta being measured.
    """
    for card in CARDS:
        if card.faction == faction and card.card_type != "champion":
            return card
    for card in CARDS:
        if card.faction == faction:
            return card
    return None


#: Junk kept in hand in every arm. Several abilities are "you may sacrifice a
#: card in your hand" / "sacrifice up to two", which the engine resolves with a
#: heuristic that reads the hand. An empty hand in one arm and a hand holding
#: one freshly-drawn card in the other makes those abilities behave
#: differently, and the difference lands in the delta being attributed to the
#: ally. Holding the hand constant removes that channel.
HAND_FILLER = 3


def fresh(board=(), hand=(), played=(), opp_board=None):
    """A session with every zone under our control and nothing incidental."""
    session = create_session(seed=11)
    session.active_player = "player"
    me, them = session.player, session.bot
    me.hp, me.gold, me.combat = 30, 0, 0
    me.deck = [GOLD] * 12
    me.hand = list(hand) + [GOLD] * HAND_FILLER
    me.discard = []
    me.banish = []
    me.board = [BoardChampion(c) for c in board]
    me.played_this_turn = list(played)
    me.pending_ally = []
    me.pending_prepares = 0
    me.next_buy_to_hand = me.next_buy_to_top = False
    them.hp = 30
    them.hand = [GOLD] * 5
    them.deck = [GOLD] * 5
    if opp_board is None:
        # Constant across every arm. Stun abilities need a legal target or
        # they silently do nothing and read as "the ally did nothing".
        opp_board = [BY_NAME["Man-at-Arms"]]
    them.board = [BoardChampion(c) for c in opp_board]
    return session


def play(session, card: HRCard) -> dict[str, int]:
    before = snapshot(session)
    stun_index = 0 if card.get("stun", False) and session.bot.board else None
    session.play_card(card.id, stun_index)
    return delta(before, snapshot(session))


def expend(session, champion: BoardChampion, choice: str | None = None) -> dict[str, int]:
    before = snapshot(session)
    stun_index = 0 if champion.card.get("stun", False) and session.bot.board else None
    session.expend_champion_action(str(champion.instance_id), stun_index, choice)
    return delta(before, snapshot(session))


# --------------------------------------------------------------------------
# Findings
# --------------------------------------------------------------------------

@dataclass
class Finding:
    card: str
    check: str
    detail: str
    severity: str = "FAIL"   # FAIL | UNPARSED


def _resource_delta(d: dict[str, int], played_from_hand: bool = False) -> dict[str, int]:
    """The measured delta expressed in the vocabulary the text parser uses.

    `played_from_hand` offsets the card itself leaving hand. Without it every
    "draw a card" on a played action reads as +0 hand and looks like a bug -
    the card left as the draw arrived.
    """
    out = {}
    if d.get("combat"):
        out["combat"] = d["combat"]
    if d.get("gold"):
        out["gold"] = d["gold"]
    if d.get("hp"):
        out["health"] = d["hp"]
    drawn = d.get("hand", 0) + (1 if played_from_hand else 0)
    if drawn:
        out["draw"] = drawn
    return out


def _compare(card, check, section: Section, observed, findings):
    """Measured delta vs printed text, for one trigger point.

    An "X *or* Y" clause is verified as a choice: exactly one branch may show
    up. Summing the branches instead is the `or_choice` double-count that has
    bitten this engine before, so the sum is never what is asserted.
    """
    remaining = dict(observed)

    if section.choices:
        matched = None
        for branch in section.choices:
            if all(remaining.get(r, 0) >= v for r, v in branch.items()):
                matched = branch
                break
        if matched is None:
            findings.append(Finding(
                card.name, check,
                f"text offers a choice of {section.choices}, engine gave {observed}",
            ))
            return
        for resource, value in matched.items():
            remaining[resource] = remaining.get(resource, 0) - value
        extra = {r: v for r, v in remaining.items()
                 if v and r not in section.flat}
        if extra:
            findings.append(Finding(
                card.name, check,
                f"took choice {matched} but also paid {extra} - both branches?",
            ))

    # A section whose other clauses the parser could not reduce can only be
    # checked as a lower bound: the measured delta legitimately contains the
    # unparsed clause's contribution too. Krythos reads "{Gain 3 combat}" plus
    # "you may sacrifice a card ... gain an additional 3 combat" - the engine
    # correctly gives 6, and asserting == 3 would be a false positive.
    strict = not section.unparsed and not section.behaviours
    for resource, want in section.flat.items():
        got = remaining.get(resource, 0)
        if got == want:
            continue
        if not strict and got > want:
            continue
        bound = "at least " if not strict else ""
        findings.append(Finding(
            card.name, check,
            f"text says {resource} {bound}{want:+d}, engine gave {got:+d}",
        ))


#: For "for each X you have in play", the extra permanents to add and the
#: engine-side count they scale on.
SCALE_FIXTURE = {
    "champion": "Death Cultist",     # a plain champion, no ally, no expend payload
    "guard":    "Death Cultist",     # ...which is also a Guard
    "wild":     "Wolf Shaman",       # a Wild card, for "each other Wild card"
}


def _check_behaviours(card, check, section, raw_delta, trigger, findings):
    """Verify the non-numeric clauses this card states.

    `trigger` re-runs the ability from a given fixture, so scaling clauses can
    be measured as a difference between two board sizes rather than guessed at.
    """
    for behaviour in section.behaviours:
        kind = behaviour[0]

        if kind == "opp_discard":
            want = behaviour[1]
            got = -raw_delta.get("opp_hand", 0)
            if got != want:
                findings.append(Finding(
                    card.name, check,
                    f"text discards {want} of the opponent's cards, engine took {got}"))

        elif kind == "stun":
            if raw_delta.get("opp_board", 0) >= 0:
                findings.append(Finding(
                    card.name, check,
                    "text stuns a champion, opponent's board did not shrink"))

        elif kind == "to_hand":
            if not raw_delta.get("next_buy_to_hand"):
                findings.append(Finding(
                    card.name, check,
                    "text routes the next acquired card to hand, flag not set"))

        elif kind == "to_top":
            action_only = behaviour[1]
            key = "next_buy_to_top_action_only" if action_only else "next_buy_to_top"
            if not raw_delta.get(key):
                findings.append(Finding(
                    card.name, check,
                    f"text routes the next acquired card to the deck top, {key} not set"))

        elif kind == "prepare":
            if not (raw_delta.get("pending_prepares") or raw_delta.get("prepared")):
                findings.append(Finding(
                    card.name, check,
                    "text prepares a champion, nothing was readied or queued"))

        elif kind == "scale":
            per, resource, unit = behaviour[1], behaviour[2], behaviour[3]
            fixture = BY_NAME[SCALE_FIXTURE[unit]]
            key = {"combat": "combat", "health": "hp"}[resource]
            # On an "X *or* scales-with-Y" card the engine picks a branch, so
            # the scaling only shows when its own branch is taken. Drive each
            # branch and accept if any of them scales as printed - Tithe Priest
            # takes the gold branch by default and would otherwise read as a
            # scaling bug.
            branches = list(card.effects.get("or_choice") or [None])
            results = []
            for branch in branches:
                try:
                    low = trigger(extra=[], choice=branch)
                    high = trigger(extra=[fixture, fixture], choice=branch)
                except Exception as exc:
                    results.append(f"branch {branch}: {exc}")
                    continue
                results.append(high.get(key, 0) - low.get(key, 0))
            if 2 * per not in results:
                findings.append(Finding(
                    card.name, check,
                    f"text gives {per} {resource} per {unit}; two more gave "
                    f"{results}, expected {2 * per:+d}"))


# --------------------------------------------------------------------------
# Per-card audit
# --------------------------------------------------------------------------

def audit_card(card: HRCard) -> list[Finding]:
    findings: list[Finding] = []
    sections = parse_sections(card)
    by_kind = {s.kind: s for s in sections}
    is_champion = card.card_type == "champion"
    partner = partner_for(card.faction) if card.faction else None
    has_ally_text = "ally" in by_kind

    for section in sections:
        for clause in section.unparsed:
            findings.append(Finding(
                card.name, f"{section.kind} clause not machine-checkable",
                clause[:88], severity="UNPARSED",
            ))

    # ---- base ability -----------------------------------------------------
    if is_champion:
        # A champion must do nothing on play but enter the board.
        session = fresh(hand=[card])
        observed = play(session, card)
        stray = {k: v for k, v in observed.items()
                 if k not in ("hand", "board") and v}
        if stray:
            findings.append(Finding(
                card.name, "champion applied effects on play",
                f"expected board+1 only, also saw {stray}",
            ))

        if "expend" in by_kind:
            def expend_trigger(extra=(), choice=None):
                sess = fresh(board=[card, *extra])
                return expend(sess, sess.player.board[0], choice)

            raw = expend_trigger()
            _compare(card, "expend ability", by_kind["expend"],
                     _resource_delta(raw), findings)
            _check_behaviours(card, "expend ability", by_kind["expend"],
                              raw, expend_trigger, findings)
    elif "play" in by_kind:
        def play_trigger(extra=(), choice=None):
            sess = fresh(hand=[card], board=list(extra))
            return play(sess, card)

        raw = play_trigger()
        _compare(card, "on-play ability", by_kind["play"],
                 _resource_delta(raw, played_from_hand=True), findings)
        _check_behaviours(card, "on-play ability", by_kind["play"],
                          raw, play_trigger, findings)

    # ---- ally ability -----------------------------------------------------
    if has_ally_text and partner is not None:
        ally_flat = by_kind["ally"].flat

        from hero_engine import _resolve_board_allies

        def ally_contribution(with_partner: HRCard, extra=(), choice=None):
            """What the ally alone adds, as (with partner) - (without partner).

            Both arms are otherwise identical, so the card leaving hand, the
            board growing and the base ability all cancel and what is left is
            attributable to the ally. Measuring the with-partner arm on its own
            counts the card leaving hand as evidence the ally fired, which is
            how an earlier version of this file passed while the engine could
            not pair two copies of one card at all.
            """
            def arm(partner_card):
                played = [partner_card] if partner_card is not None else []
                if is_champion:
                    sess = fresh(board=[card, *extra], played=played)
                    before = snapshot(sess)
                    _resolve_board_allies(sess.player, sess.bot)
                    return delta(before, snapshot(sess))
                return play(fresh(hand=[card], board=list(extra), played=played), card)

            with_ally, without = arm(with_partner), arm(None)
            return {k: with_ally.get(k, 0) - without.get(k, 0)
                    for k in set(with_ally) | set(without)}

        def ally_trigger(extra=(), choice=None):
            return ally_contribution(partner, extra, choice)

        # I1/I2: a partner in play, and only then, pays the ally.
        ally_only = {k: v for k, v in ally_trigger().items() if v}
        _compare(card, "ally ability", by_kind["ally"], _resource_delta(ally_only), findings)
        _check_behaviours(card, "ally ability", by_kind["ally"],
                          ally_only, ally_trigger, findings)

        if not ally_only:
            findings.append(Finding(
                card.name, "ally ability did nothing",
                "a faction partner was in play and no measured state changed",
            ))

        # I6: a second *copy* of this same card is just as good a partner.
        dup_only = {k: v for k, v in ally_contribution(card).items() if v}
        if dup_only != ally_only:
            findings.append(Finding(
                card.name, "second copy of the card is not an ally partner",
                f"a different-card partner paid {ally_only}, a second copy of "
                f"this card paid {dup_only}",
            ))

        # I3: a champion's ally must not be re-paid by expending it.
        if is_champion and "expend" in by_kind:
            lone = fresh(board=[card])
            lone_expend = expend(lone, lone.player.board[0])

            # The partner is present but the ally is marked already collected,
            # so the only thing that can differ is the expend itself. Letting
            # the ally actually fire here would move cards into hand and change
            # what an optional "you may sacrifice" finds to sacrifice, which
            # lands in the delta and reads as a false positive (Tyrannor and
            # Life Drain both did exactly that).
            withp = fresh(board=[card], played=[partner])
            withp.player.board[0].ally_paid_this_turn = True
            paired_expend = expend(withp, withp.player.board[0])
            if paired_expend != lone_expend:
                findings.append(Finding(
                    card.name, "expend pays the ally as well",
                    f"expend alone {lone_expend}, expend with partner {paired_expend}",
                ))

        # I4/I5: once per turn, and again on the next turn.
        if is_champion:
            partner_champ = _champion_partner(card)
            if partner_champ is not None:
                from hero_engine import _resolve_board_allies
                sess = fresh(board=[card, partner_champ])
                sess._start_turn(sess.player)
                first = snapshot(sess)
                _resolve_board_allies(sess.player, sess.bot)
                if delta(first, snapshot(sess)):
                    findings.append(Finding(
                        card.name, "ally fired twice in one turn",
                        "resolving again in the same turn changed state",
                    ))
                sess._start_turn(sess.player)
                second = snapshot(sess)
                if second["combat"] == 0 and by_kind["ally"].flat.get("combat"):
                    findings.append(Finding(
                        card.name, "ally did not re-fire on a new turn",
                        "a standing faction pair must trigger every turn",
                    ))

    return findings


def _champion_partner(card: HRCard) -> HRCard | None:
    """A *different* champion of the same faction, for turn-start tests."""
    for other in CARDS:
        if (other.card_type == "champion" and other.faction == card.faction
                and other.name != card.name and not other.effects.get("ally_faction")):
            return other
    return None


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--card", help="audit a single card by name")
    ap.add_argument("--failures", action="store_true",
                    help="hide UNPARSED coverage gaps, show only failures")
    args = ap.parse_args()

    targets = ([BY_NAME[args.card]] if args.card
               else sorted(BY_NAME.values(), key=lambda c: c.name))
    if args.card and args.card not in BY_NAME:
        print(f"unknown card: {args.card}")
        return 2

    failures: list[Finding] = []
    unparsed: list[Finding] = []
    errored: list[tuple[str, str]] = []

    for card in targets:
        try:
            for finding in audit_card(card):
                (failures if finding.severity == "FAIL" else unparsed).append(finding)
        except Exception as exc:  # a card the harness cannot drive is a gap too
            errored.append((card.name, f"{type(exc).__name__}: {exc}"))

    print(f"driven {len(targets)} cards through the live engine\n")

    if failures:
        print(f"== {len(failures)} BEHAVIOUR FAILURES ==")
        for f in failures:
            print(f"  {f.card:<26} {f.check:<42} {f.detail}")
        print()
    else:
        print("== no behaviour failures ==\n")

    if errored:
        print(f"== {len(errored)} cards the harness could not drive ==")
        for name, err in errored:
            print(f"  {name:<26} {err}")
        print()

    if not args.failures and unparsed:
        cards = len({f.card for f in unparsed})
        print(f"== {len(unparsed)} clauses on {cards} cards are NOT machine-checkable ==")
        print("   (reported, not skipped: these are the unaudited parts of the set)")
        for f in unparsed:
            print(f"  {f.card:<26} {f.check:<42} {f.detail}")
        print()

    covered = len(targets) - len({f.card for f in unparsed}) - len(errored)
    print(f"fully machine-checked: {covered}/{len(targets)} cards; "
          f"{len(failures)} failures, {len(errored)} undrivable")
    return 1 if failures or errored else 0


if __name__ == "__main__":
    raise SystemExit(main())
