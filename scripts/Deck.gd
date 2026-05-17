extends RefCounted
class_name Deck

var draw_pile: Array[Card] = []
var discard_pile: Array[Card] = []


func setup(cards: Array[Card]) -> void:
	draw_pile = cards.duplicate()
	discard_pile.clear()
	draw_pile.shuffle()


func draw_card() -> Card:
	if draw_pile.is_empty():
		shuffle_discard_into_draw()

	if draw_pile.is_empty():
		return null

	return draw_pile.pop_back()


func discard_card(card: Card) -> void:
	if card == null:
		return

	discard_pile.append(card)


func discard_cards(cards: Array[Card]) -> void:
	for card: Card in cards:
		discard_card(card)


func pop_from_discard_pile() -> Card:
	if discard_pile.is_empty():
		return null

	return discard_pile.pop_back()


func shuffle_discard_into_draw() -> void:
	if discard_pile.is_empty():
		return

	draw_pile.append_array(discard_pile)
	discard_pile.clear()
	draw_pile.shuffle()


func draw_count() -> int:
	return draw_pile.size()


func discard_count() -> int:
	return discard_pile.size()
