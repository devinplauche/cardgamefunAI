extends Node

var _failed: int = 0
var _passed: int = 0


func _ready() -> void:
	GameState.load_databases()
	run_all()
	print("[ART-TEST] Completed %d tests. Passed=%d Failed=%d" % [_passed + _failed, _passed, _failed])
	get_tree().quit(0 if _failed == 0 else 1)


func run_all() -> void:
	_assert_texture_for("Gold", "res://cards/images/BAS-EN-097-gold.jpg")
	_assert_texture_for("Ruby", "res://cards/images/BAS-EN-133-ruby.jpg")
	_assert_texture_for("Dagger", "res://cards/images/BAS-EN-129-dagger.jpg")
	_assert_texture_for("Man-at-Arms", GameState.find_card_image_path("Man-at-Arms"))
	_assert_texture_for("Broelyn, Loreweaver", GameState.find_card_image_path("Broelyn, Loreweaver"))
	_assert_texture_for("Rayla, Endweaver", GameState.find_card_image_path("Rayla, Endweaver"))
	_assert_texture_for("Rampage", GameState.find_card_image_path("Rampage"))


func _assert_texture_for(card_name: String, image_path: String) -> void:
	_assert_true(not image_path.is_empty(), "art path exists for %s" % card_name)
	var image := Image.new()
	var err: int = image.load(ProjectSettings.globalize_path(image_path))
	_assert_true(err == OK, "art file loads for %s" % card_name)


func _assert_true(value: bool, label: String) -> void:
	if value:
		_passed += 1
		print("[PASS] %s" % label)
	else:
		_failed += 1
		push_error("[FAIL] %s" % label)
