/**
 * Post-round coaching.
 *
 * Rage pays +10 for an exact contract and -5 for missing it, on top of +1 per
 * trick, so a one-trick miss is a 14-16 point swing -- larger than any other
 * decision available at the table. Everything here is graded against that fact:
 * the contract drives the grade, and the notes separate a hand that was misread
 * at the bid from one that was bid well and then misplayed.
 */

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
  headline: string;
  notes: string[];
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
  const { bid, suggestedBid, tricks, tricksInRound, trickTrace, roundBonus } =
    performance;
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

  const notes: string[] = [];
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
        contract === "over"
          ? "The bid was sound — this one got away in the play. Once you are on your number, shed the highest card that cannot win rather than the lowest."
          : "The bid was sound — this one got away in the play. While you are short, lead your strongest card instead of ducking with a low one.",
      );
    else if (suggestedBid === tricks)
      notes.push(
        `The search read the hand as exactly ${suggestedBid}, which is what you took. This was a bidding miss, not a playing one.`,
      );
    else
      notes.push(
        `The search read the hand as ${suggestedBid} against your ${bid}. Re-read your trump length and top cards before committing.`,
      );
    notes.push(
      `Missing the contract cost ${cost} points; extra tricks are only worth 1 each.`,
    );
  }

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
    headline,
    notes,
  };
}
