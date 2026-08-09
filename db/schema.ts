import { integer, text, sqliteTable } from "drizzle-orm/sqlite-core";

export const savedGames = sqliteTable("saved_games", {
  userId: text("user_id").primaryKey(),
  gameState: text("game_state").notNull(),
  updatedAt: text("updated_at").notNull(),
});

export const matchResults = sqliteTable("match_results", {
  id: text("id").primaryKey(),
  playerName: text("player_name").notNull(),
  playerScore: integer("player_score").notNull(),
  winnerName: text("winner_name").notNull(),
  winnerScore: integer("winner_score").notNull(),
  playerCount: integer("player_count").notNull(),
  botLevel: text("bot_level").notNull(),
  playedAt: text("played_at").notNull(),
});
