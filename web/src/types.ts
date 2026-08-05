/**
 * 'main' is the faithful printed turn structure: play, expend, buy and
 * attack are all legal at once, in any order (web/session.py: MAIN_PHASE).
 * The other four are the legacy fixed-order phases, still reachable for
 * reproducing pre-fix baselines.
 */
export type Phase = 'main' | 'play' | 'champion' | 'buy' | 'combat';

export interface CardView {
  id: string;
  name: string;
  cost: number;
  faction: string;
  cardType: string;
  guard: number;
  health: number;
  effects: Record<string, unknown>;
  text: string;
}

export interface ChampionView extends CardView {
  /**
   * Distinguishes two board champions sharing the same card `id` - a card
   * printed in 2-3 copies can appear twice on one board. The engine matches
   * expend and attack targets on this, NOT on `id` (see
   * GameSession.expend_champion_action / attack_target_action), so sending
   * `id` silently fails every lookup with "Champion not found".
   */
  instanceId: string;
  currentHealth: number;
  exhausted: boolean;
  alive: boolean;
}

export interface PlayerView {
  name: string;
  hp: number;
  gold: number;
  combat: number;
  deckCount: number;
  handCount: number;
  discardCount: number;
  banishCount: number;
  nextBuyToHand: boolean;
  nextBuyToTop: boolean;
  nextBuyToTopActionOnly: boolean;
  hand: CardView[];
  /** Non-champion cards in play this turn (face-up for both seats). */
  playedThisTurn: CardView[];
  board: ChampionView[];
}

export interface MarketView {
  row: Array<CardView | null>;
  fireGemsRemaining: number;
}

export interface LogEntry {
  kind: string;
  message: string;
  turn: number;
  phase: Phase;
  activePlayer: 'player' | 'bot';
  at: number;
  botInsight?: BotInsight | null;
}

export interface BotInsight {
  algorithm: string;
  action?: string;
  label?: string;
  cardId?: string;
  marketIndex?: number;
  championId?: string;
  stunTargetIndex?: number;
  target?: string;
  score?: number;
  iterations?: number;
  worlds?: number;
  rootSampling?: 'independent' | 'paired';
  selection?: 'agreement' | 'heuristic_guard' | 'mcts_override';
  utilityAdvantage?: number | null;
  elapsedMs?: number;
  actions?: Array<Record<string, unknown>>;
  lastAction?: Record<string, unknown> | null;
  finalPhase?: string;
  candidates?: Array<{
    type?: string;
    label?: string;
    cardId?: string;
    marketIndex?: number;
    championId?: string;
    stunTargetIndex?: number;
    target?: string;
    score?: number;
    visits?: number;
    averageScore?: number;
    averageUtility?: number | null;
    priority?: number;
  }>;
}

export interface GameStateCore {
  sessionId: string;
  turnNumber: number;
  phase: Phase;
  activePlayer: 'player' | 'bot';
  winner: 'player' | 'bot' | 'draw' | null;
  player: PlayerView;
  bot: PlayerView;
  market: MarketView;
  legalActions: Array<Record<string, unknown>>;
  log: LogEntry[];
  botInsight: BotInsight | null;
}

export interface HistoryFrame {
  id: string;
  kind: string;
  label: string;
  turn: number;
  phase: Phase;
  activePlayer: 'player' | 'bot';
  botInsight: BotInsight | null;
  state: GameStateCore;
}

export interface GameState extends GameStateCore {
  history: HistoryFrame[];
}
