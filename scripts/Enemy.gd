extends PanelContainer
class_name Enemy

signal defeated

var enemy_name: String = "Enemy"
var max_hp: int = 20
var current_hp: int = 20
var current_block: int = 0
var behavior_pattern: Array[Dictionary] = []
var current_intent_index: int = 0
var current_intent: Dictionary = {}
var statuses: Dictionary = {}

@onready var name_label: Label = $Margin/Content/NameLabel
@onready var hp_bar: ProgressBar = $Margin/Content/HpBar
@onready var hp_label: Label = $Margin/Content/HpLabel
@onready var intent_label: Label = $Margin/Content/IntentLabel
@onready var status_label: Label = $Margin/Content/StatusLabel


func setup_from_dict(data: Dictionary) -> void:
	enemy_name = String(data.get("name", "Enemy"))
	max_hp = int(data.get("hp", 20))
	current_hp = max_hp
	current_block = 0
	statuses.clear()
	current_intent_index = 0
	behavior_pattern.clear()

	for step: Dictionary in data.get("behavior_pattern", []):
		behavior_pattern.append(step.duplicate(true))

	choose_intent()
	update_view()


func choose_intent() -> void:
	if behavior_pattern.is_empty():
		current_intent = {}
		return

	current_intent = behavior_pattern[current_intent_index]
	update_view()


func take_turn() -> String:
	if current_intent.is_empty():
		choose_intent()

	if current_intent.is_empty():
		return "%s waits." % enemy_name

	var action := String(current_intent.get("action", ""))
	var value := int(current_intent.get("value", 0))
	var intent_text := String(current_intent.get("intent_text", action.capitalize()))

	match action:
		"attack":
			CardEffect.deal_damage(GameState, value)
		"block":
			CardEffect.gain_block(self, value)
		_:
			push_warning("Unknown enemy action: %s" % action)

	_tick_statuses()
	if not behavior_pattern.is_empty():
		current_intent_index = (current_intent_index + 1) % behavior_pattern.size()
	choose_intent()
	return "%s uses %s." % [enemy_name, intent_text]


func receive_damage(amount: int) -> void:
	if amount <= 0:
		return

	var final_amount: int = amount
	if int(statuses.get("Vulnerable", 0)) > 0:
		final_amount = ceili(amount * 1.5)

	var damage_after_block: int = max(final_amount - current_block, 0)
	current_block = max(current_block - final_amount, 0)
	current_hp = max(current_hp - damage_after_block, 0)
	update_view()

	if current_hp <= 0:
		defeated.emit()


func gain_block(amount: int) -> void:
	if amount <= 0:
		return

	current_block += amount
	update_view()


func clear_block() -> void:
	current_block = 0
	update_view()


func apply_status(status_name: String, stacks: int) -> void:
	if status_name.is_empty() or stacks <= 0:
		return

	statuses[status_name] = int(statuses.get(status_name, 0)) + stacks
	update_view()


func is_defeated() -> bool:
	return current_hp <= 0


func update_view() -> void:
	if not is_node_ready():
		return

	name_label.text = enemy_name
	hp_bar.max_value = max_hp
	hp_bar.value = current_hp
	hp_label.text = "HP: %d / %d    Block: %d" % [current_hp, max_hp, current_block]

	if current_intent.is_empty():
		intent_label.text = "Intent: None"
	else:
		intent_label.text = "Intent: %s" % String(current_intent.get("intent_text", "Unknown"))

	var status_parts: Array[String] = []
	for status_name: String in statuses.keys():
		status_parts.append("%s %d" % [status_name, int(statuses[status_name])])

	status_label.text = "Statuses: %s" % ", ".join(status_parts) if not status_parts.is_empty() else "Statuses: None"


func _tick_statuses() -> void:
	var expired_statuses: Array[String] = []

	for status_name: String in statuses.keys():
		statuses[status_name] = int(statuses[status_name]) - 1
		if int(statuses[status_name]) <= 0:
			expired_statuses.append(status_name)

	for status_name: String in expired_statuses:
		statuses.erase(status_name)

	update_view()
