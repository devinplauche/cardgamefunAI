export const SUITS = [
  "red",
  "orange",
  "yellow",
  "green",
  "blue",
  "purple",
] as const;
export type Suit = (typeof SUITS)[number];
export type CardType = "wild" | "bonus" | "mad" | "change" | "out";
export type BotLevel = "easy" | "medium" | "hard";
export type Card = { id: string; suit?: Suit; rank?: number; type?: CardType };
export type PlayedCard = {
  player: number;
  card: Card;
  declaredSuit?: Suit;
  declaredRank?: number;
  chosenTrump?: Suit;
};
export type Phase =
  | "bidding"
  | "playing"
  | "resolving"
  | "roundSummary"
  | "gameOver";
export type Player = {
  id: number;
  name: string;
  bot: BotLevel;
  hand: Card[];
  bid: number | null;
  tricks: number;
  score: number;
  roundBonus: number;
};
export type GameState = {
  seed: number;
  rng: number;
  playerCount: number;
  round: number;
  cardsPerPlayer: number;
  dealer: number;
  leader?: number;
  phase: Phase;
  players: Player[];
  trump: Suit | null;
  stock: Card[];
  trumpReveal: Card[];
  trick: PlayedCard[];
  lastTrick: PlayedCard[];
  leadSuit: Suit | null;
  currentPlayer: number;
  lastWinner: number | null;
  lastRoundScores: number[] | null;
  log: string[];
};
export type Play = {
  cardId: string;
  declaredSuit?: Suit;
  declaredRank?: number;
  chosenTrump?: Suit;
};

export type MctsOptions = {
  iterations?: number;
  rolloutPlies?: number;
};

const next = (rng: number) => (rng * 1664525 + 1013904223) >>> 0;
const pick = <T>(items: T[], rng: number): [T, number] => {
  const updated = next(rng);
  return [items[updated % items.length], updated];
};
const advance = (state: GameState, from = state.currentPlayer) =>
  (from + 1) % state.playerCount;
const roundLeader = (state: GameState) =>
  state.leader ?? advance(state, state.dealer);
const cloneCard = (card: Card) => ({ ...card });

export function cardName(card: Card) {
  return card.type
    ? `${card.type[0].toUpperCase()}${card.type.slice(1)} Rage`
    : `${card.rank} ${card.suit}`;
}

export function createDeck(): Card[] {
  const numbered = SUITS.flatMap((suit) =>
    Array.from({ length: 16 }, (_, rank) => ({
      id: `${suit}-${rank}`,
      suit,
      rank,
    })),
  );
  const specials: Card[] = ["wild", "bonus", "mad"].flatMap((type) =>
    Array.from({ length: 2 }, (_, i) => ({
      id: `${type}-${i}`,
      type: type as CardType,
    })),
  );
  const trumpChangers: Card[] = ["change", "out"].flatMap((type) =>
    Array.from({ length: 4 }, (_, i) => ({
      id: `${type}-${i}`,
      type: type as CardType,
    })),
  );
  return [...numbered, ...specials, ...trumpChangers];
}

function shuffle(cards: Card[], rng: number): [Card[], number] {
  const out = cards.map(cloneCard);
  let current = rng;
  for (let i = out.length - 1; i > 0; i -= 1) {
    current = next(current);
    const j = current % (i + 1);
    [out[i], out[j]] = [out[j], out[i]];
  }
  return [out, current];
}

function dealRound(state: GameState): GameState {
  const cardsEach = 11 - state.round;
  const [deck, rng] = shuffle(createDeck(), state.rng);
  const players = state.players.map((player) => ({
    ...player,
    hand: [],
    bid: null,
    tricks: 0,
    roundBonus: 0,
  }));
  let cursor = 0;
  for (let card = 0; card < cardsEach; card += 1)
    for (let offset = 1; offset <= state.playerCount; offset += 1)
      players[advance(state, state.dealer + offset - 1)].hand.push(
        deck[cursor++],
      );
  let trump: Suit | null = null;
  const trumpReveal: Card[] = [];
  while (cursor < deck.length && !trump) {
    const card = deck[cursor++];
    trumpReveal.push(card);
    if (card.suit) trump = card.suit;
  }
  return {
    ...state,
    rng,
    players,
    cardsPerPlayer: cardsEach,
    stock: deck.slice(cursor),
    trumpReveal,
    trump,
    trick: [],
    lastTrick: [],
    leadSuit: null,
    phase: "bidding",
    currentPlayer: roundLeader(state),
    lastWinner: null,
    lastRoundScores: null,
    log: [
      ...state.log,
      `Round ${state.round}: ${cardsEach} cards, ${trump} trump`,
    ],
  };
}

export function createGame({
  seed = 1,
  playerCount = 4,
  bots = [],
}: { seed?: number; playerCount?: number; bots?: BotLevel[] } = {}): GameState {
  if (playerCount < 2 || playerCount > 6)
    throw new Error("Rage supports 2–6 players");
  const players = Array.from({ length: playerCount }, (_, id) => ({
    id,
    name: id === 0 ? "You" : ["Mia", "Ken", "Ari", "Zoe", "Sam"][id - 1],
    bot: bots[id] ?? (id === 0 ? "medium" : id % 3 === 0 ? "hard" : "medium"),
    hand: [],
    bid: null,
    tricks: 0,
    score: 0,
    roundBonus: 0,
  }));
  const [leader, rng] = pick(
    Array.from({ length: playerCount }, (_, playerId) => playerId),
    seed >>> 0 || 1,
  );
  return dealRound({
    seed,
    rng,
    playerCount,
    round: 1,
    cardsPerPlayer: 0,
    dealer: leader,
    leader,
    phase: "bidding",
    players,
    trump: null,
    stock: [],
    trumpReveal: [],
    trick: [],
    lastTrick: [],
    leadSuit: null,
    currentPlayer: 0,
    lastWinner: null,
    lastRoundScores: null,
    log: [`Game seed ${seed}`],
  });
}

export function legalPlays(
  state: GameState,
  playerId = state.currentPlayer,
): Card[] {
  if (state.phase !== "playing" || playerId !== state.currentPlayer) return [];
  const hand = state.players[playerId].hand;
  if (!state.leadSuit) {
    return hand;
  }
  const followers = hand.filter((card) => card.suit === state.leadSuit);
  return followers.length ? followers : hand;
}

function establishLead(trick: PlayedCard[]) {
  for (const played of trick) {
    if (played.card.suit) return played.card.suit;
    if (played.card.type === "wild") return played.declaredSuit ?? null;
  }
  return null;
}

function effectiveSuit(played: PlayedCard) {
  return (
    played.card.suit ??
    (played.card.type === "wild" ? played.declaredSuit : undefined)
  );
}

function winsAgainst(
  challenger: PlayedCard,
  current: PlayedCard,
  lead: Suit | null,
  trump: Suit | null,
) {
  const challengerSuit = effectiveSuit(challenger);
  const currentSuit = effectiveSuit(current);
  if (!challengerSuit) return false;
  if (!currentSuit) return true;
  const challengerTrump = trump && challengerSuit === trump;
  const currentTrump = trump && currentSuit === trump;
  if (challengerTrump !== currentTrump) return Boolean(challengerTrump);
  if (challengerSuit !== currentSuit)
    return challengerSuit === lead && currentSuit !== lead;
  return (
    (challenger.card.type === "wild"
      ? (challenger.declaredRank ?? -1)
      : (challenger.card.rank ?? -1)) >
    (current.card.type === "wild"
      ? (current.declaredRank ?? -1)
      : (current.card.rank ?? -1))
  );
}

function resolveTrick(state: GameState): GameState {
  const leadSuit = establishLead(state.trick);
  if (!leadSuit) {
    const base = {
      ...state,
      trick: [],
      lastTrick: state.trick,
      leadSuit: null,
      lastWinner: null,
      log: [...state.log, "No one takes the all-action trick"],
    };
    if (state.players.every((player) => player.hand.length === 0))
      return scoreRound(base);
    return base;
  }
  let winner = state.trick[0];
  for (const challenger of state.trick.slice(1))
    if (winsAgainst(challenger, winner, leadSuit, state.trump))
      winner = challenger;
  const modifiers = state.trick.reduce(
    (sum, played) =>
      sum +
      (played.card.type === "bonus" ? 5 : played.card.type === "mad" ? -5 : 0),
    0,
  );
  const players = state.players.map((player) =>
    player.id === winner.player
      ? {
          ...player,
          tricks: player.tricks + 1,
          roundBonus: player.roundBonus + modifiers,
        }
      : player,
  );
  const base = {
    ...state,
    players,
    trick: [],
    lastTrick: state.trick,
    leadSuit: null,
    currentPlayer: winner.player,
    lastWinner: winner.player,
    log: [...state.log, `${state.players[winner.player].name} takes the trick`],
  };
  if (players.every((player) => player.hand.length === 0))
    return scoreRound(base);
  return base;
}

function scoreRound(state: GameState): GameState {
  const tricksInRound = state.cardsPerPlayer;
  const roundScores = state.players.map(
    (player) =>
      player.tricks +
      player.roundBonus +
      (player.tricks === tricksInRound ? 5 : 0) +
      (player.tricks === player.bid ? 10 : -5),
  );
  const players = state.players.map((player, index) => ({
    ...player,
    score: player.score + roundScores[index],
  }));
  const scored = {
    ...state,
    players,
    phase:
      state.round === 10 ? ("gameOver" as const) : ("roundSummary" as const),
    lastRoundScores: roundScores,
    log: [...state.log, `Round ${state.round} scored`],
  };
  return scored;
}

function revealNextTrump(stock: Card[]): {
  trump: Suit | null;
  revealed: Card[];
  stock: Card[];
} {
  const revealed: Card[] = [];
  let cursor = 0;
  while (cursor < stock.length) {
    const card = stock[cursor++];
    revealed.push(card);
    if (card.suit)
      return { trump: card.suit, revealed, stock: stock.slice(cursor) };
  }
  return { trump: null, revealed, stock: [] };
}

export function continueGame(state: GameState): GameState {
  if (state.phase !== "roundSummary") return state;
  return dealRound({
    ...state,
    round: state.round + 1,
    dealer: advance(state, state.dealer),
    leader: advance(state, roundLeader(state)),
  });
}

export function submitBid(
  state: GameState,
  playerId: number,
  bid: number,
): GameState {
  if (state.phase !== "bidding" || playerId !== state.currentPlayer)
    throw new Error("Not this player’s bid");
  const max = state.players[playerId].hand.length;
  if (!Number.isInteger(bid) || bid < 0 || bid > max)
    throw new Error("Invalid bid");
  const players = state.players.map((player) =>
    player.id === playerId ? { ...player, bid } : player,
  );
  const allBids = players.every((player) => player.bid !== null);
  return {
    ...state,
    players,
    phase: allBids ? "playing" : "bidding",
    currentPlayer: allBids ? roundLeader(state) : advance(state),
    log: [...state.log, `${state.players[playerId].name} bids ${bid}`],
  };
}

export function playCard(
  state: GameState,
  playerId: number,
  play: Play,
  deferResolution = false,
): GameState {
  if (state.phase !== "playing" || playerId !== state.currentPlayer)
    throw new Error("Not this player’s turn");
  const card = state.players[playerId].hand.find(
    (candidate) => candidate.id === play.cardId,
  );
  if (!card) throw new Error("Card is not in hand");
  if (!legalPlays(state).some((candidate) => candidate.id === card.id))
    throw new Error("Must follow suit");
  if (card.type === "wild" && !play.declaredSuit)
    throw new Error("Wild Rage needs a declared suit");
  if (
    card.type === "wild" &&
    (!Number.isInteger(play.declaredRank) ||
      play.declaredRank! < 0 ||
      play.declaredRank! > 16)
  )
    throw new Error("Wild Rage needs a declared number from 0 to 16");
  const changedTrump =
    card.type === "change" ? revealNextTrump(state.stock) : null;
  const trick = [
    ...state.trick,
    {
      player: playerId,
      card,
      declaredSuit: play.declaredSuit,
      declaredRank: play.declaredRank,
      chosenTrump: changedTrump?.trump ?? undefined,
    },
  ];
  const players = state.players.map((player) =>
    player.id === playerId
      ? {
          ...player,
          hand: player.hand.filter((candidate) => candidate.id !== card.id),
        }
      : player,
  );
  const trump =
    card.type === "change"
      ? (changedTrump?.trump ?? state.trump)
      : card.type === "out"
        ? null
        : state.trump;
  const played = {
    ...state,
    players,
    trick,
    trump,
    stock: changedTrump?.stock ?? state.stock,
    trumpReveal: changedTrump
      ? [...(state.trumpReveal ?? []), ...changedTrump.revealed]
      : (state.trumpReveal ?? []),
    leadSuit: establishLead(trick),
    currentPlayer: advance(state),
    rng: state.rng,
    log: [
      ...state.log,
      `${state.players[playerId].name} plays ${cardName(card)}`,
    ],
  };
  return trick.length === state.playerCount
    ? deferResolution
      ? { ...played, phase: "resolving" }
      : resolveTrick(played)
    : played;
}

export function finishTrick(state: GameState): GameState {
  if (state.phase !== "resolving")
    throw new Error("No trick is ready to resolve");
  return resolveTrick({ ...state, phase: "playing" });
}

function handValue(hand: Card[], trump: Suit | null) {
  return hand.reduce((value, card) => {
    if (card.type === "wild") return value + 1.1;
    const rank = card.rank ?? 0;
    if (card.suit === trump) return value + (rank >= 13 ? 0.95 : rank >= 10 ? 0.65 : rank >= 7 ? 0.3 : 0.05);
    return value + (rank >= 15 ? 0.55 : rank >= 13 ? 0.3 : 0);
  }, 0);
}

function legacyHandValue(hand: Card[], trump: Suit | null) {
  return hand.reduce(
    (value, card) =>
      value +
      (card.type === "wild"
        ? 1.5
        : card.suit === trump && (card.rank ?? 0) >= 9
          ? 1
          : (card.rank ?? 0) >= 13
            ? 0.75
            : 0),
    0,
  );
}
export function chooseBotBid(state: GameState, playerId: number): number {
  const player = state.players[playerId];
  const value = player.bot === "hard" ? handValue(player.hand, state.trump) : legacyHandValue(player.hand, state.trump);
  return Math.max(
    0,
    Math.min(
      state.players[playerId].hand.length,
      Math.round(value),
    ),
  );
}

function preferredSuit(hand: Card[]): Suit {
  return [...SUITS].sort(
    (a, b) =>
      hand.filter((card) => card.suit === b).length -
      hand.filter((card) => card.suit === a).length,
  )[0] ?? SUITS[0];
}

function cloneState(state: GameState): GameState {
  return {
    ...state,
    players: state.players.map((player) => ({ ...player, hand: player.hand.map(cloneCard) })),
    stock: state.stock.map(cloneCard),
    trumpReveal: state.trumpReveal.map(cloneCard),
    trick: state.trick.map((played) => ({ ...played, card: cloneCard(played.card) })),
    lastTrick: state.lastTrick.map((played) => ({ ...played, card: cloneCard(played.card) })),
    log: [...state.log],
  };
}

function shuffleCards(cards: Card[], rng: number): [Card[], number] {
  const out = cards.map(cloneCard);
  let current = rng >>> 0;
  for (let i = out.length - 1; i > 0; i -= 1) {
    current = next(current);
    const j = current % (i + 1);
    [out[i], out[j]] = [out[j], out[i]];
  }
  return [out, current];
}

function determinize(state: GameState, playerId: number, seed: number): GameState {
  const result = cloneState(state);
  const hidden = result.players.filter((player) => player.id !== playerId).flatMap((player) => player.hand);
  const [shuffled, rng] = shuffleCards(hidden, seed);
  let cursor = 0;
  result.players = result.players.map((player) => {
    if (player.id === playerId) return player;
    const hand = shuffled.slice(cursor, cursor + player.hand.length);
    cursor += player.hand.length;
    return { ...player, hand };
  });
  result.rng = rng;
  return result;
}

function declarationFor(state: GameState, playerId: number, card: Card): Play {
  const player = state.players[playerId];
  const needs = (player.bid ?? 0) - player.tricks;
  return {
    cardId: card.id,
    declaredSuit: card.type === "wild" ? state.trump ?? preferredSuit(player.hand) : undefined,
    declaredRank: card.type === "wild" ? (needs > 0 ? 16 : 0) : undefined,
  };
}

function cardWinsCurrentTrick(state: GameState, playerId: number, card: Card): boolean {
  if (!state.trick.length) return false;
  const play = declarationFor(state, playerId, card);
  const candidate: PlayedCard = {
    player: playerId,
    card,
    declaredSuit: play.declaredSuit,
    declaredRank: play.declaredRank,
  };
  const lead = establishLead([...state.trick, candidate]);
  let winner = state.trick[0];
  for (const played of state.trick.slice(1))
    if (winsAgainst(played, winner, lead, state.trump)) winner = played;
  return winsAgainst(candidate, winner, lead, state.trump);
}

function rolloutPlay(state: GameState, playerId: number): Play {
  const legal = legalPlays(state, playerId);
  const player = state.players[playerId];
  const needs = (player.bid ?? 0) - player.tricks;
  const cardScore = (card: Card) =>
    (card.type === "wild" ? 40 : card.suit === state.trump ? 25 : 0) + (card.rank ?? 0);
  let card: Card;
  if (!state.trick.length) {
    const sorted = [...legal].sort((a, b) => cardScore(a) - cardScore(b));
    card = needs > 0 ? sorted[sorted.length - 1] : sorted[0];
  } else {
    const winners = legal.filter((candidate) => cardWinsCurrentTrick(state, playerId, candidate));
    const losers = legal.filter((candidate) => !cardWinsCurrentTrick(state, playerId, candidate));
    if (needs > 0 && winners.length)
      card = [...winners].sort((a, b) => cardScore(a) - cardScore(b))[0];
    else if (needs <= 0 && losers.length)
      card = [...losers].sort((a, b) => cardScore(a) - cardScore(b))[0];
    else {
      const fallback = [...legal].sort((a, b) => cardScore(a) - cardScore(b));
      card = needs > 0 ? fallback[fallback.length - 1] : fallback[0];
    }
  }
  return declarationFor(state, playerId, card);
}

function rolloutValue(state: GameState, playerId: number): number {
  const player = state.players[playerId];
  const opponents = state.players.filter((candidate) => candidate.id !== playerId);
  const averageOpponentScore = opponents.reduce((sum, opponent) => sum + opponent.score, 0) / Math.max(1, opponents.length);
  return player.score - averageOpponentScore - Math.abs(player.tricks - (player.bid ?? 0)) * 2;
}

function rollout(state: GameState, playerId: number, plies: number): number {
  let current = state;
  for (let ply = 0; ply < plies; ply += 1) {
    if (current.phase === "gameOver") return rolloutValue(current, playerId);
    if (current.phase === "roundSummary") current = continueGame(current);
    else if (current.phase === "resolving") current = finishTrick(current);
    else if (current.phase === "bidding") current = submitBid(current, current.currentPlayer, chooseBotBid(current, current.currentPlayer));
    else current = playCard(current, current.currentPlayer, rolloutPlay(current, current.currentPlayer));
  }
  return rolloutValue(current, playerId);
}

export function chooseMctsPlay(state: GameState, playerId: number, options: MctsOptions = {}): Play {
  const legal = legalPlays(state, playerId);
  if (!legal.length) throw new Error("No legal bot move");
  const declare = (card: Card): Play => declarationFor(state, playerId, card);
  if (legal.length === 1) return declare(legal[0]);
  const player = state.players[playerId];
  const needs = (player.bid ?? 0) - player.tricks;
  const highStakes = state.trick.length > 0 && needs !== 0;
  const endgame = player.hand.length <= 3;
  const defaultIterations = highStakes || endgame ? 32 : 24;
  const defaultRolloutPlies = highStakes || endgame ? 96 : 80;
  const iterations = Math.max(legal.length, options.iterations ?? defaultIterations);
  const rolloutPlies = Math.max(1, options.rolloutPlies ?? defaultRolloutPlies);
  const tacticalPrior = (card: Card) => {
    if (!state.trick.length) return 0;
    const wins = cardWinsCurrentTrick(state, playerId, card);
    if (needs > 0) return wins ? 3 : -1;
    return wins ? -2 : 2;
  };
  const totals = new Map(legal.map((card) => [card.id, tacticalPrior(card)]));
  const visits = new Map(legal.map((card) => [card.id, 0]));
  const rootSeed = (state.seed ^ state.rng ^ (playerId * 2654435761)) >>> 0;
  for (let iteration = 0; iteration < iterations; iteration += 1) {
    let selected = legal[0];
    let bestUct = Number.NEGATIVE_INFINITY;
    for (const card of legal) {
      const count = visits.get(card.id)!;
      const mean = count ? totals.get(card.id)! / count : 0;
      const uct = mean + (count ? Math.SQRT2 * Math.sqrt(Math.log(iteration + 2) / count) : Number.POSITIVE_INFINITY);
      if (uct > bestUct) {
        bestUct = uct;
        selected = card;
      }
    }
    const simulated = determinize(state, playerId, next((rootSeed + iteration) >>> 0));
    const after = playCard(simulated, playerId, declare(selected));
    const value = rollout(after, playerId, rolloutPlies);
    visits.set(selected.id, visits.get(selected.id)! + 1);
    totals.set(selected.id, totals.get(selected.id)! + value);
  }
  const best = legal.reduce((winner, card) => {
    const winnerVisits = visits.get(winner.id)!;
    const cardVisits = visits.get(card.id)!;
    const winnerMean = totals.get(winner.id)! / winnerVisits;
    const cardMean = totals.get(card.id)! / cardVisits;
    return cardVisits > winnerVisits || (cardVisits === winnerVisits && cardMean > winnerMean) ? card : winner;
  });
  return declare(best);
}

export function chooseBotPlay(state: GameState, playerId: number): Play {
  const legal = legalPlays(state, playerId);
  const player = state.players[playerId];
  if (!legal.length) throw new Error("No legal bot move");
  let card: Card;
  let rng = state.rng;
  if (player.bot === "easy") [card, rng] = pick(legal, rng);
  else if (player.bot === "hard") return chooseMctsPlay(state, playerId);
  else card = legal.sort((a, b) => ((a.rank ?? 0) + (a.suit === state.trump ? 25 : 0)) - ((b.rank ?? 0) + (b.suit === state.trump ? 25 : 0)))[(player.bid ?? 0) > player.tricks ? legal.length - 1 : 0];
  void rng;
  const preferredTrump = preferredSuit(player.hand);
  return {
    cardId: card.id,
    declaredSuit:
      card.type === "wild" ? (state.trump ?? preferredTrump) : undefined,
    declaredRank:
      card.type === "wild"
        ? (player.bid ?? 0) > player.tricks
          ? 16
          : 0
        : undefined,
  };
}

export function advanceBots(state: GameState, humanPlayer = 0): GameState {
  let current = state;
  let guard = 0;
  while (
    current.phase !== "gameOver" &&
    current.phase !== "roundSummary" &&
    (current.phase === "resolving" || current.currentPlayer !== humanPlayer) &&
    guard++ < 5000
  ) {
    current =
      current.phase === "resolving"
        ? finishTrick(current)
        : current.phase === "bidding"
          ? submitBid(
              current,
              current.currentPlayer,
              chooseBotBid(current, current.currentPlayer),
            )
          : playCard(
              current,
              current.currentPlayer,
              chooseBotPlay(current, current.currentPlayer),
            );
  }
  if (guard >= 5000) throw new Error("Bot loop stalled");
  return current;
}

export function simulateGame(
  seed: number,
  playerCount: number,
  bots: BotLevel[] = Array.from({ length: playerCount }, () => "medium"),
): GameState {
  let state = createGame({ seed, playerCount, bots });
  let guard = 0;
  while (state.phase !== "gameOver" && guard++ < 20000) {
    if (state.phase === "roundSummary") state = continueGame(state);
    else if (state.phase === "resolving") state = finishTrick(state);
    else if (state.phase === "bidding")
      state = submitBid(
        state,
        state.currentPlayer,
        chooseBotBid(state, state.currentPlayer),
      );
    else
      state = playCard(
        state,
        state.currentPlayer,
        chooseBotPlay(state, state.currentPlayer),
      );
  }
  if (guard >= 20000) throw new Error("Simulation stalled");
  return state;
}
