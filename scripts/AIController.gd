extends Node
class_name AIController

signal turn_started
signal turn_ended

# Base class used by any AI driver (enemy AI, PvP AI, boss AI, etc.).
# Override take_turn() in subclasses.
func take_turn(_context: Dictionary) -> void:
	turn_started.emit()
	turn_ended.emit()


# Shared helper to make AI behavior feel natural instead of instant.
func wait_human_delay(min_seconds: float = 0.5, max_seconds: float = 1.5) -> void:
	var wait_time: float = randf_range(min_seconds, max_seconds)
	await get_tree().create_timer(wait_time).timeout


# Optional helper for consumers that want to await AI completion directly.
func run_turn(context: Dictionary) -> void:
	await take_turn(context)
