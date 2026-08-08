import { text, sqliteTable } from "drizzle-orm/sqlite-core";

export const savedGames = sqliteTable("saved_games", {
  userId: text("user_id").primaryKey(),
  gameState: text("game_state").notNull(),
  updatedAt: text("updated_at").notNull(),
});
