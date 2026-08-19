import type { BotLevel } from "./rage";

export const BOT_LEVELS: BotLevel[] = [
  "easy",
  "medium",
  "hard",
  "extreme",
  "inlaws",
  "absolute-inlaws",
];

export const BOT_NAMES: Record<BotLevel, string> = {
  easy: "Easy",
  medium: "Medium",
  hard: "Hard",
  extreme: "Extreme",
  inlaws: "In-laws — CHEATING",
  "absolute-inlaws": "Absolute In-laws — LEGAL CHEATS",
};

export const BOT_LEVEL_OPTIONS = BOT_LEVELS.map((value) => ({
  value,
  label: BOT_NAMES[value],
}));

export function botLevelFromSave(level: unknown): BotLevel {
  return BOT_LEVELS.includes(level as BotLevel) ? (level as BotLevel) : "medium";
}
