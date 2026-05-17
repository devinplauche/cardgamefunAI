extends HBoxContainer
class_name Hand

signal card_selected(card: Card)

@export var card_scene: PackedScene = preload("res://ui/Card.tscn")

var cards: Array[Card] = []


func set_cards(new_cards: Array[Card]) -> void:
	cards.clear()
	for card: Card in new_cards:
		cards.append(card)
	_rebuild_ui()


func draw_from_deck(deck: Deck, amount: int) -> void:
	for _index in range(amount):
		var drawn_card: Card = deck.draw_card()
		if drawn_card != null:
			cards.append(drawn_card)

	_rebuild_ui()


func add_card(card: Card) -> void:
	if card == null:
		return

	cards.append(card)
	_rebuild_ui()


func remove_card(card: Card, deck: Deck) -> void:
	var card_index: int = cards.find(card)
	if card_index == -1:
		return

	cards.remove_at(card_index)
	if deck != null:
		deck.discard_card(card)

	_rebuild_ui()


func discard_hand(deck: Deck) -> void:
	if deck != null:
		deck.discard_cards(cards)

	cards.clear()
	_rebuild_ui()


func _rebuild_ui() -> void:
	for child: Node in get_children():
		child.queue_free()

	for card: Card in cards:
		var card_view: CardView = card_scene.instantiate()
		card_view.set_card_data(card)
		card_view.card_pressed.connect(_on_card_pressed)
		add_child(card_view)


func _on_card_pressed(card: Card) -> void:
	card_selected.emit(card)
