extends Resource
class_name Card

@export var card_name: String = "Card"
@export var cost: int = 1
@export_multiline var description: String = ""
@export var card_type: String = "Skill"
@export var image_path: String = ""


func play(_target: Node) -> void:
	push_error("Card.play() must be implemented by a subclass.")
