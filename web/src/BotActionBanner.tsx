import { CardArtwork } from "./CardArtwork";
import { CARD_ART } from "./cardArt";
import type { BotActionFrame } from "./useBotPlayback";

const ACTION_NAMES: Record<string, string> = {
  play: "Playing a card",
  buy: "Buying from the market",
  combat: "Attacking",
  expend: "Activating a champion",
  sacrifice: "Sacrificing a card",
  effect: "Resolving an ability",
  phase: "Changing phase",
  turn: "Passing the turn",
};
const CARD_NAMES = Object.keys(CARD_ART).sort((a, b) => b.length - a.length);

export function BotActionBanner({
  action,
  skipping,
  onSkip,
}: {
  action: BotActionFrame | null;
  skipping: boolean;
  onSkip: () => void;
}) {
  const frame = action?.frame;
  const name = frame
    ? CARD_NAMES.find((name) => frame.label.includes(name))
    : undefined;
  const deltas: string[] = [];
  if (action && frame && frame.kind !== "turn") {
    for (const [side, label] of [
      ["bot", "Bot"],
      ["player", "You"],
    ] as const) {
      for (const [stat, unit] of [
        ["hp", "HP"],
        ["gold", "gold"],
        ["combat", "combat"],
      ] as const) {
        const change = frame.state[side][stat] - action.before[side][stat];
        if (change)
          deltas.push(`${label}: ${change > 0 ? "+" : ""}${change} ${unit}`);
      }
    }
  }
  return (
    <aside
      className={`bot-action-banner action-${frame?.kind ?? "thinking"}`}
      aria-label="Live bot actions"
    >
      <div
        className="bot-action-visual"
        key={frame?.id ?? "thinking"}
        aria-hidden="true"
      >
        {name ? (
          <CardArtwork
            card={{
              name,
              cardType: frame?.kind === "expend" ? "champion" : "action",
            }}
            compact
          />
        ) : (
          <span className="bot-action-symbol">
            {frame?.kind === "combat" ? "⚔" : "♜"}
          </span>
        )}
      </div>
      <div
        className="bot-action-copy"
        role="status"
        aria-live="polite"
        aria-atomic="true"
      >
        <span className="bot-action-heading">
          {frame
            ? `BOT · ${action?.number} · ${ACTION_NAMES[frame.kind] ?? "Taking action"}`
            : "BOT · THINKING"}
        </span>
        <strong>{frame?.label ?? "The challenger is choosing a move…"}</strong>
        <div className="bot-action-deltas" key={frame?.id}>
          {deltas.map((delta) => (
            <span key={delta}>{delta}</span>
          ))}
          {!deltas.length && (
            <span>
              {frame
                ? `Action ${action?.number}`
                : "Watch each move here as it happens."}
            </span>
          )}
        </div>
      </div>
      <button className="secondary-button" onClick={onSkip} disabled={skipping}>
        {skipping ? "Finishing…" : "Skip effects"}
      </button>
    </aside>
  );
}
