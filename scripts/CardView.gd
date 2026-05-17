extends PanelContainer
class_name CardView

const CardArtLoader = preload("res://scripts/CardArtLoader.gd")

signal card_pressed(card: Card)

@export var hover_scale: Vector2 = Vector2(1.06, 1.06)

var card_data: Card
var _base_scale: Vector2 = Vector2.ONE

@onready var cost_label: Label = $Margin/Content/Header/CostLabel
@onready var type_label: Label = $Margin/Content/Header/TypeLabel
@onready var name_label: Label = $Margin/Content/NameLabel
@onready var art_texture: TextureRect = $Margin/Content/Art
@onready var description_label: Label = $Margin/Content/DescriptionLabel


func _ready() -> void:
	_base_scale = scale
	pivot_offset = size * 0.5
	mouse_entered.connect(_on_mouse_entered)
	mouse_exited.connect(_on_mouse_exited)
	gui_input.connect(_on_gui_input)
	resized.connect(_on_resized)
	_refresh()


func set_card_data(new_card: Card) -> void:
	card_data = new_card
	if is_node_ready():
		_refresh()


func _refresh() -> void:
	name_label.visible = false
	type_label.visible = false
	description_label.visible = false
	if card_data == null:
		cost_label.text = "?"
		type_label.text = "Unknown"
		name_label.text = "Unnamed Card"
		description_label.text = ""
		tooltip_text = ""
		art_texture.texture = CardArtLoader.load_texture_for_card("", "res://cards/images/default-card.svg")
		return

	cost_label.text = str(card_data.cost)
	type_label.text = card_data.card_type
	name_label.text = card_data.card_name
	description_label.text = card_data.description
	tooltip_text = "%s [%s]\n%s" % [card_data.card_name, card_data.card_type, card_data.description]
	art_texture.texture = _resolve_card_texture(card_data)


func _on_mouse_entered() -> void:
	scale = hover_scale


func _on_mouse_exited() -> void:
	scale = _base_scale


func _on_gui_input(event: InputEvent) -> void:
	if event is InputEventMouseButton and event.button_index == MOUSE_BUTTON_LEFT and event.pressed:
		card_pressed.emit(card_data)


func _on_resized() -> void:
	pivot_offset = size * 0.5


func _resolve_card_texture(card: Card) -> Texture2D:
	if card == null:
		return _get_default_texture()
	return CardArtLoader.load_texture_for_card(card.card_name, card.image_path)


func _load_texture_if_exists(path: String) -> Texture2D:
	return CardArtLoader.load_texture(path)


func _get_default_texture() -> Texture2D:
	var from_file: Texture2D = _load_texture_if_exists("res://cards/images/default-card.svg")
	if from_file != null:
		return from_file
	return CardArtLoader._build_default_texture()
