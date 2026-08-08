CREATE TABLE `saved_games` (
	`user_id` text PRIMARY KEY NOT NULL,
	`game_state` text NOT NULL,
	`updated_at` text NOT NULL
);
