CREATE TABLE `match_results` (
	`id` text PRIMARY KEY NOT NULL,
	`player_name` text NOT NULL,
	`player_score` integer NOT NULL,
	`winner_name` text NOT NULL,
	`winner_score` integer NOT NULL,
	`player_count` integer NOT NULL,
	`bot_level` text NOT NULL,
	`played_at` text NOT NULL
);
