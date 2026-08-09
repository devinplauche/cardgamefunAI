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
export type BotLevel = "easy" | "medium" | "hard" | "extreme";
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
  shareResults?: boolean;
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
  threatAware?: boolean;
};
export type MctsBidOptions = { simulations?: number; threatAware?: boolean };

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
  playerName = "You",
  shareResults = false,
}: {
  seed?: number;
  playerCount?: number;
  bots?: BotLevel[];
  playerName?: string;
  shareResults?: boolean;
} = {}): GameState {
  if (playerCount < 2 || playerCount > 6)
    throw new Error("Rage supports 2–6 players");
  const players = Array.from({ length: playerCount }, (_, id) => ({
    id,
    name: id === 0 ? playerName : ["Mia", "Ken", "Ari", "Zoe", "Sam"][id - 1],
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
    shareResults,
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
  const wilds = hand.filter((card) => card.type === "wild");
  return followers.length ? [...followers, ...wilds] : hand;
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
      (player.tricks === tricksInRound && player.bid === tricksInRound
        ? 5
        : 0) +
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
function chooseHeuristicBid(state: GameState, playerId: number): number {
  return Math.max(
    0,
    Math.min(
      state.players[playerId].hand.length,
      Math.round(handValue(state.players[playerId].hand, state.trump)),
    ),
  );
}
export function chooseBotBid(state: GameState, playerId: number): number {
  const level = state.players[playerId].bot;
  if (level === "extreme") return chooseExtremeBid(state, playerId);
  return level === "hard" ? chooseMctsBid(state, playerId) : chooseHeuristicBid(state, playerId);
}

function cloneState(state: GameState): GameState {
  return {
    ...state,
    players: state.players.map((player) => ({
      ...player,
      hand: player.hand.map(cloneCard),
    })),
    stock: state.stock.map(cloneCard),
    trumpReveal: state.trumpReveal.map(cloneCard),
    trick: state.trick.map((played) => ({
      ...played,
      card: cloneCard(played.card),
    })),
    lastTrick: state.lastTrick.map((played) => ({
      ...played,
      card: cloneCard(played.card),
    })),
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

function determinizeForMcts(
  state: GameState,
  playerId: number,
  seed: number,
): GameState {
  const determinized = cloneState(state);
  const hidden = determinized.players
    .filter((player) => player.id !== playerId)
    .flatMap((player) => player.hand);
  const [shuffled, rng] = shuffleCards(hidden, seed);
  let cursor = 0;
  determinized.players = determinized.players.map((player) => {
    if (player.id === playerId) return player;
    const hand = shuffled.slice(cursor, cursor + player.hand.length);
    cursor += player.hand.length;
    return { ...player, hand };
  });
  determinized.rng = rng;
  return determinized;
}

function heuristicPlay(state: GameState, playerId: number): Play {
  const legal = legalPlays(state, playerId);
  const player = state.players[playerId];
  const needs = (player.bid ?? 0) - player.tricks;
  const score = (candidate: Card) =>
    (candidate.type === "wild" ? 40 : candidate.suit === state.trump ? 25 : 0) +
    (candidate.rank ?? 0);
  const sorted = [...legal].sort((a, b) => score(a) - score(b));
  const card = needs > 0 ? sorted[sorted.length - 1] : sorted[0];
  return {
    cardId: card.id,
    declaredSuit:
      card.type === "wild"
        ? (state.trump ?? preferredSuit(player.hand))
        : undefined,
    declaredRank: card.type === "wild" ? (needs > 0 ? 16 : 0) : undefined,
  };
}

function preferredSuit(hand: Card[]): Suit {
  return (
    [...SUITS].sort(
      (a, b) =>
        hand.filter((candidate) => candidate.suit === b).length -
        hand.filter((candidate) => candidate.suit === a).length,
    )[0] ?? SUITS[0]
  );
}

function rolloutValue(state: GameState, playerId: number): number {
  const player = state.players[playerId];
  const opponents = state.players.filter(
    (candidate) => candidate.id !== playerId,
  );
  const opponentAverage =
    opponents.reduce((sum, opponent) => sum + opponent.score, 0) /
    Math.max(1, opponents.length);
  const bidProgress = player.tricks - (player.bid ?? 0);
  return player.score - opponentAverage - Math.abs(bidProgress) * 2;
}

function extremeThreatWeights(state: GameState, playerId: number): Map<number, number> {
  const myScore = state.players[playerId].score;
  return new Map(
    state.players
      .filter((player) => player.id !== playerId)
      .map((player) => {
        const gap = player.score - myScore;
        // Nearby leaders matter most: they are the players Extreme should deny.
        const proximity = 0.55 / (1 + Math.abs(gap) / 15);
        return [player.id, 1 + proximity + (gap >= 0 ? 0.35 : 0)];
      }),
  );
}

function extremeRolloutValue(state: GameState, playerId: number): number {
  const player = state.players[playerId];
  const weights = extremeThreatWeights(state, playerId);
  let weightedOpponentScore = 0;
  let totalWeight = 0;
  let opponentExactBids = 0;
  for (const opponent of state.players) {
    if (opponent.id === playerId) continue;
    const weight = weights.get(opponent.id) ?? 1;
    weightedOpponentScore += opponent.score * weight;
    totalWeight += weight;
    if (opponent.bid !== null && opponent.tricks === opponent.bid)
      opponentExactBids += weight;
  }
  const bidProgress = Math.abs(player.tricks - (player.bid ?? 0));
  const scoreEdge =
    player.score - weightedOpponentScore / Math.max(1, totalWeight);
  // Extreme protects a lead more fiercely than it chases one: falling behind
  // is deliberately more expensive than an equal-sized gain is valuable.
  const lossAverseEdge = scoreEdge < 0 ? scoreEdge * 1.65 : scoreEdge;
  return (
    lossAverseEdge - bidProgress * 2.25 -
    opponentExactBids * 0.75
  );
}

function finishBidsForSimulation(
  state: GameState,
  playerId: number,
  bid: number,
): GameState {
  let current = state;
  while (current.phase === "bidding") {
    const bidder = current.currentPlayer;
    current = submitBid(
      current,
      bidder,
      bidder === playerId ? bid : chooseHeuristicBid(current, bidder),
    );
  }
  return current;
}

function simulateBidValue(
  state: GameState,
  playerId: number,
  bid: number,
  seed: number,
  threatAware: boolean,
): number {
  let current = determinizeForMcts(state, playerId, seed);
  current = finishBidsForSimulation(current, playerId, bid);
  let guard = 0;
  while (current.phase === "playing" || current.phase === "resolving") {
    if (guard++ > 500) throw new Error("Bid simulation exceeded its round");
    current =
      current.phase === "resolving"
        ? finishTrick(current)
        : playCard(
            current,
            current.currentPlayer,
            heuristicPlay(current, current.currentPlayer),
          );
  }
  const evaluate = threatAware ? extremeRolloutValue : rolloutValue;
  return evaluate(current, playerId) - evaluate(state, playerId);
}

function hasStrategicOpponents(state: GameState, playerId: number) {
  return state.players.some(
    (player) =>
      player.id !== playerId &&
      (player.bot === "medium" || player.bot === "hard"),
  );
}

export function chooseMctsBid(
  state: GameState,
  playerId: number,
  options: MctsBidOptions = {},
): number {
  const handSize = state.players[playerId].hand.length;
  const simulations = Math.max(
    1,
    options.simulations ??
      (options.threatAware ? 20 : hasStrategicOpponents(state, playerId) ? 16 : 10),
  );
  const rootSeed = (state.seed ^ state.rng ^ (playerId * 2246822519)) >>> 0;
  let bestBid = 0;
  let bestScore = Number.NEGATIVE_INFINITY;
  for (let bid = 0; bid <= handSize; bid += 1) {
    let total = 0;
    for (let simulation = 0; simulation < simulations; simulation += 1)
      total += simulateBidValue(
        state,
        playerId,
        bid,
        next((rootSeed + bid * 4099 + simulation) >>> 0),
        options.threatAware ?? false,
      );
    const expectedScore = total / simulations;
    if (
      expectedScore > bestScore ||
      (expectedScore === bestScore &&
        Math.abs(bid - chooseHeuristicBid(state, playerId)) <
          Math.abs(bestBid - chooseHeuristicBid(state, playerId)))
    ) {
      bestBid = bid;
      bestScore = expectedScore;
    }
  }
  return bestBid;
}

export function chooseExtremeBid(state: GameState, playerId: number): number {
  // Bids set the bot's own contract; threat targeting belongs in trick play,
  // where it can deliberately deny a nearby rival without sacrificing a sound bid.
  return chooseMctsBid(state, playerId, { simulations: 24 });
}

function runMctsRollout(
  state: GameState,
  playerId: number,
  rolloutPlies: number,
  threatAware: boolean,
): number {
  let current = state;
  for (let ply = 0; ply < rolloutPlies; ply += 1) {
    if (current.phase === "gameOver")
      return (threatAware ? extremeRolloutValue : rolloutValue)(current, playerId);
    if (current.phase === "roundSummary") {
      current = continueGame(current);
      continue;
    }
    if (current.phase === "resolving") {
      current = finishTrick(current);
      continue;
    }
    if (current.phase === "bidding") {
      current = submitBid(
        current,
        current.currentPlayer,
        chooseHeuristicBid(current, current.currentPlayer),
      );
      continue;
    }
    current = playCard(
      current,
      current.currentPlayer,
      heuristicPlay(current, current.currentPlayer),
    );
  }
  return (threatAware ? extremeRolloutValue : rolloutValue)(current, playerId);
}

export function chooseMctsPlay(
  state: GameState,
  playerId: number,
  options: MctsOptions = {},
): Play {
  const legal = legalPlays(state, playerId);
  if (!legal.length) throw new Error("No legal bot move");
  const declare = (card: Card): Play => ({
    cardId: card.id,
    declaredSuit:
      card.type === "wild"
        ? (state.trump ?? preferredSuit(state.players[playerId].hand))
        : undefined,
    declaredRank:
      card.type === "wild"
        ? (state.players[playerId].bid ?? 0) > state.players[playerId].tricks
          ? 16
          : 0
        : undefined,
  });
  if (legal.length === 1) return declare(legal[0]);
  const deeperSearch = hasStrategicOpponents(state, playerId);
  const iterations = Math.max(
    legal.length,
    options.iterations ?? (deeperSearch ? 36 : 24),
  );
  const rolloutPlies = Math.max(
    1,
    options.rolloutPlies ?? (options.threatAware ? 120 : deeperSearch ? 100 : 80),
  );
  const totals = new Map<string, number>(legal.map((card) => [card.id, 0]));
  const visits = new Map<string, number>(legal.map((card) => [card.id, 0]));
  const rootSeed = (state.seed ^ state.rng ^ (playerId * 2654435761)) >>> 0;

  for (let iteration = 0; iteration < iterations; iteration += 1) {
    const logTotal = Math.log(iteration + 2);
    let selected = legal[0];
    let bestUct = Number.NEGATIVE_INFINITY;
    for (const card of legal) {
      const count = visits.get(card.id)!;
      const mean = count ? totals.get(card.id)! / count : 0;
      const exploration = count
        ? Math.sqrt(logTotal / count)
        : Number.POSITIVE_INFINITY;
      const uct = mean + Math.SQRT2 * exploration;
      if (uct > bestUct) {
        bestUct = uct;
        selected = card;
      }
    }
    const seed = next((rootSeed + iteration) >>> 0);
    const determinized = determinizeForMcts(state, playerId, seed);
    const afterAction = playCard(determinized, playerId, declare(selected));
    const value = runMctsRollout(
      afterAction,
      playerId,
      rolloutPlies,
      options.threatAware ?? false,
    );
    visits.set(selected.id, visits.get(selected.id)! + 1);
    totals.set(selected.id, totals.get(selected.id)! + value);
  }

  const best = legal.reduce((winner, card) =>
    visits.get(card.id)! > visits.get(winner.id)! ||
    (visits.get(card.id) === visits.get(winner.id) &&
      totals.get(card.id)! / visits.get(card.id)! >
        totals.get(winner.id)! / visits.get(winner.id)!)
      ? card
      : winner,
  );
  return declare(best);
}

export function chooseExtremePlay(state: GameState, playerId: number): Play {
  return chooseMctsPlay(state, playerId, {
    iterations: 48,
    rolloutPlies: 120,
    threatAware: true,
  });
}

export function chooseBotPlay(state: GameState, playerId: number): Play {
  const legal = legalPlays(state, playerId);
  const player = state.players[playerId];
  if (!legal.length) throw new Error("No legal bot move");
  let card: Card;
  let rng = state.rng;
  if (player.bot === "easy") [card, rng] = pick(legal, rng);
  else if (player.bot === "hard") return chooseMctsPlay(state, playerId);
  else if (player.bot === "extreme") return chooseExtremePlay(state, playerId);
  else {
    const chosen = heuristicPlay(state, playerId);
    card = legal.find((candidate) => candidate.id === chosen.cardId)!;
  }
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
