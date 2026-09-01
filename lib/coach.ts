/**
 * Post-round coaching.
 *
 * Rage pays +10 for an exact contract and -5 for missing it, on top of +1 per
 * trick, so a one-trick miss is a 14-16 point swing -- larger than any other
 * decision available at the table. Everything here is graded against that fact:
 * the contract drives the grade, and the notes separate a hand that was misread
 * at the bid from one that was bid well and then misplayed.
 */

import { cardName, trickWinner, type Card, type PlayedCard, type Suit } from "./rage";

/** One card the player chose, judged against what the round needed at the time. */
export type PlayDecision = {
  /** 1-based trick number within the round. */
  trick: number;
  /** Tricks still owed on the contract when the card was chosen. */
  needed: number;
  /** True when only one card was legal, so nothing was actually decided. */
  forced: boolean;
  wonTrick: boolean;
  /** In hindsight, a legal card existed that would have taken the trick. */
  couldHaveWon: boolean;
  /** In hindsight, a legal card existed that would have lost the trick. */
  couldHaveDucked: boolean;
  kind: "forced" | "on-plan" | "missed-trick" | "loose-trick" | "unavoidable";
  /** The card that was played. */
  card: string;
  /** The card that would have served the contract, when one existed. */
  betterCard?: string;
};

export type DecisionInput = {
  trick: number;
  needed: number;
  /** Cards that were legal at the moment of choosing. */
  legal: Card[];
  played: Card;
  /** The trick as it finished, including this player's card. */
  resolved: PlayedCard[];
  /** Trump in force when the trick resolved. */
  trump: Suit | null;
  playerId: number;
};

/**
 * Replay a finished trick with each card the player could legally have played
 * instead. This is hindsight -- later opponents might have answered a different
 * card differently -- but it is the same read a person does when they look back
 * at a hand, and it is the only way to say anything concrete about the play.
 */
export function assessDecision(input: DecisionInput): PlayDecision {
  const { trick, needed, legal, played, resolved, trump, playerId } = input;
  const seat = resolved.findIndex((entry) => entry.player === playerId);
  const winner = trickWinner(resolved, trump);
  const wonTrick = winner?.player === playerId;
  const forced = legal.length <= 1;

  const wouldWin = (card: Card) => {
    if (seat < 0) return false;
    const swapped = resolved.map((entry, index) =>
      index === seat
        ? {
            ...entry,
            card,
            // A swapped-in Wild keeps the seat's declaration only if it is one.
            declaredSuit: card.type === "wild" ? entry.declaredSuit : undefined,
            declaredRank: card.type === "wild" ? entry.declaredRank : undefined,
          }
        : entry,
    );
    return trickWinner(swapped, trump)?.player === playerId;
  };

  const winners = forced ? [] : legal.filter(wouldWin);
  const duckers = forced ? [] : legal.filter((card) => !wouldWin(card));
  const couldHaveWon = winners.length > 0;
  const couldHaveDucked = duckers.length > 0;
  const wanted = needed > 0;

  let kind: PlayDecision["kind"];
  let betterCard: string | undefined;
  if (forced) kind = "forced";
  else if (wanted === wonTrick) kind = "on-plan";
  else if (wanted && couldHaveWon) {
    kind = "missed-trick";
    // The cheapest card that would still have taken it.
    betterCard = cardName(cheapest(winners));
  } else if (!wanted && couldHaveDucked) {
    kind = "loose-trick";
    // The biggest card that could safely have been thrown away.
    betterCard = cardName(dearest(duckers));
  } else kind = "unavoidable";

  return {
    trick,
    needed,
    forced,
    wonTrick,
    couldHaveWon,
    couldHaveDucked,
    kind,
    card: cardName(played),
    betterCard,
  };
}

const weight = (card: Card) => (card.type ? -1 : (card.rank ?? 0));
const cheapest = (cards: Card[]) =>
  cards.reduce((best, card) => (weight(card) < weight(best) ? card : best));
const dearest = (cards: Card[]) =>
  cards.reduce((best, card) => (weight(card) > weight(best) ? card : best));

export type RoundPerformance = {
  round: number;
  /** What the player actually bid. */
  bid: number;
  /** What the bid search would have bid on the same hand. */
  suggestedBid: number;
  tricks: number;
  /** Tricks available this round (equals the hand size). */
  tricksInRound: number;
  /** The player's running trick total after each resolved trick. */
  trickTrace: number[];
  /** Rage card modifiers collected this round (+5 Bonus, -5 Mad). */
  roundBonus: number;
  /** Every card the player chose this round. Omit for a bid-only review. */
  decisions?: PlayDecision[];
};

export type RoundReview = {
  grade: "A" | "B" | "C" | "D";
  contract: "exact" | "over" | "under";
  /** Points given up versus taking exactly the bid. Zero when the bid was hit. */
  cost: number;
  /** 1-based trick on which the running count first passed the bid. */
  overshotAt: number | null;
  /** How the bid compared with the search's read of the same hand. */
  bidRead: "sound" | "low" | "high";
  /**
   * How the cards were played, independent of whether the bid was right.
   * "unknown" when no per-card data was captured for the round.
   */
  playVerdict: "clean" | "leaked" | "forced" | "unknown";
  /** The specific tricks that cost the contract, worst first. */
  leaks: PlayDecision[];
  headline: string;
  notes: string[];
};

export type GameAnalysisEntry = {
  round: number;
  bid: number;
  suggestedBid: number;
  tricks: number;
  score: number;
  review: RoundReview;
};

const EXACT_BID = 10;
const MISSED_BID = 5;

/** Grade purely on how far the trick count finished from the contract. */
function gradeFor(deviation: number): RoundReview["grade"] {
  if (deviation === 0) return "A";
  if (deviation === 1) return "B";
  if (deviation === 2) return "C";
  return "D";
}

export function reviewRound(performance: RoundPerformance): RoundReview {
  const {
    bid,
    suggestedBid,
    tricks,
    tricksInRound,
    trickTrace,
    roundBonus,
    decisions,
  } = performance;
  const deviation = Math.abs(tricks - bid);
  const contract = tricks === bid ? "exact" : tricks > bid ? "over" : "under";
  // Taking exactly the bid would have scored bid + EXACT_BID; the round instead
  // scored tricks - MISSED_BID. Rage modifiers apply either way and cancel.
  const cost = contract === "exact" ? 0 : bid - tricks + EXACT_BID + MISSED_BID;
  const overshootIndex = trickTrace.findIndex((running) => running > bid);
  const overshotAt =
    contract === "over" && overshootIndex >= 0 ? overshootIndex + 1 : null;
  const bidRead =
    suggestedBid === bid ? "sound" : bid < suggestedBid ? "low" : "high";

  // Play is judged on its own terms. A hand can be bid badly and played well,
  // or bid well and thrown away, and the player needs to be told which.
  const leaks = (decisions ?? []).filter(
    (decision) =>
      decision.kind === "missed-trick" || decision.kind === "loose-trick",
  );
  const open = (decisions ?? []).filter((decision) => !decision.forced);
  const playVerdict: RoundReview["playVerdict"] = !decisions?.length
    ? "unknown"
    : leaks.length
      ? "leaked"
      : open.length
        ? "clean"
        : "forced";

  const notes: string[] = [];

  // --- the contract ---------------------------------------------------------
  if (contract === "exact") {
    notes.push(
      bidRead === "sound"
        ? "Bid and play agreed with the search. Nothing to change."
        : `The search read this hand as ${suggestedBid}, so you found a contract it would have missed.`,
    );
    if (tricks === tricksInRound && bid === tricksInRound)
      notes.push("Called clean sweep — every trick, plus the sweep bonus.");
  } else {
    if (bidRead === "sound")
      notes.push(
        `The bid was sound — this one was lost in the play. Missing the contract cost ${cost} points; extra tricks are only worth 1 each.`,
      );
    else if (suggestedBid === tricks)
      notes.push(
        `The search read the hand as exactly ${suggestedBid}, which is what you took. This was a bidding miss, not a playing one — it cost ${cost} points.`,
      );
    else
      notes.push(
        `The search read the hand as ${suggestedBid} against your ${bid}. Re-read your trump length and top cards before committing; this cost ${cost} points.`,
      );
  }

  // --- the play, reported whether or not the bid was right ------------------
  for (const leak of leaks.slice(0, 3))
    notes.push(
      leak.kind === "loose-trick"
        ? `Trick ${leak.trick}: you were already on your number but took it with the ${leak.card}. The ${leak.betterCard} would have gone under safely.`
        : `Trick ${leak.trick}: you still needed ${leak.needed}, and the ${leak.betterCard} would have taken it. You played the ${leak.card}.`,
    );
  if (leaks.length > 3)
    notes.push(`${leaks.length - 3} more trick(s) went the same way.`);

  if (playVerdict === "clean" && contract !== "exact")
    notes.push(
      "The card play was sound — every trick went the way the contract needed. This one was decided at the bid.",
    );
  else if (playVerdict === "forced" && contract !== "exact")
    notes.push(
      "You never had a real choice this round; every card was forced. Nothing to fix in the play.",
    );
  else if (playVerdict === "clean" && contract === "exact" && open.length)
    notes.push(
      `Every one of your ${open.length} real decision(s) served the contract.`,
    );

  // --- Rage cards -----------------------------------------------------------
  if (roundBonus <= -5)
    notes.push(
      `Mad Rage landed on you for ${roundBonus}. Take your tricks before it appears, or let someone else win that one.`,
    );
  else if (roundBonus >= 5)
    notes.push(`Bonus Rage came your way for +${roundBonus}.`);

  const headline =
    contract === "exact"
      ? `Bid ${bid}, took ${tricks} — exact.`
      : contract === "over"
        ? `Bid ${bid}, took ${tricks} — ${tricks - bid} too many` +
          (overshotAt ? `, going past it on trick ${overshotAt}.` : ".")
        : `Bid ${bid}, took ${tricks} — ${bid - tricks} short.`;

  return {
    grade: gradeFor(deviation),
    contract,
    cost,
    overshotAt,
    bidRead,
    playVerdict,
    leaks,
    headline,
    notes,
  };
}
