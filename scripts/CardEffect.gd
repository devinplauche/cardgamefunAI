extends RefCounted
class_name CardEffect

# Add new reusable effect helpers here. A good rule is: if multiple cards
# might share the same behavior, place that behavior in this file.
static func deal_damage(target: Object, amount: int) -> void:
	if target == null or amount <= 0:
		return

	if target.has_method("receive_damage"):
		target.receive_damage(amount)


static func gain_block(target: Object, amount: int) -> void:
	if target == null or amount <= 0:
		return

	if target.has_method("gain_block"):
		target.gain_block(amount)


static func gain_health(target: Object, amount: int) -> void:
	if target == null or amount <= 0:
		return

	if target.has_method("gain_health"):
		target.gain_health(amount)


static func apply_status(target: Object, status_name: String, stacks: int) -> void:
	if target == null or status_name.is_empty() or stacks <= 0:
		return

	if target.has_method("apply_status"):
		target.apply_status(status_name, stacks)
