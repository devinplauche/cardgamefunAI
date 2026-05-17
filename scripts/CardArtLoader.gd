extends RefCounted
class_name CardArtLoader

static var _texture_cache: Dictionary = {}


static func load_texture_for_card(card_name: String, image_path: String = "") -> Texture2D:
	var candidate_paths: Array[String] = []
	if not image_path.is_empty():
		candidate_paths.append(image_path)

	if GameState != null and not card_name.is_empty():
		var indexed_path: String = GameState.find_card_image_path(card_name)
		if not indexed_path.is_empty() and not candidate_paths.has(indexed_path):
			candidate_paths.append(indexed_path)

	if not card_name.is_empty():
		var slug: String = card_name.to_lower().replace("'", "").replace(",", "").replace(" ", "-")
		for extension: String in ["png", "jpg", "jpeg", "webp", "svg"]:
			var path: String = "res://cards/images/%s.%s" % [slug, extension]
			if not candidate_paths.has(path):
				candidate_paths.append(path)

	candidate_paths.append("res://cards/images/market-card.svg")
	candidate_paths.append("res://cards/images/default-card.svg")

	for path: String in candidate_paths:
		var texture: Texture2D = load_texture(path)
		if texture != null:
			return texture

	return _build_default_texture()


static func load_texture(path: String) -> Texture2D:
	if path.is_empty():
		return null
	if _texture_cache.has(path):
		return _texture_cache[path]

	var loaded: Resource = null
	if ResourceLoader.exists(path):
		loaded = load(path)
		if loaded is Texture2D:
			_texture_cache[path] = loaded
			return loaded as Texture2D

	var global_path: String = ProjectSettings.globalize_path(path)
	if global_path.is_empty():
		return null
	if not FileAccess.file_exists(global_path):
		return null

	var image := Image.new()
	var err: int = image.load(global_path)
	if err != OK:
		return null

	var texture := ImageTexture.create_from_image(image)
	_texture_cache[path] = texture
	return texture


static func _build_default_texture() -> Texture2D:
	var gradient := Gradient.new()
	gradient.colors = PackedColorArray([Color(0.25, 0.28, 0.36), Color(0.14, 0.16, 0.22)])
	var tex := GradientTexture2D.new()
	tex.gradient = gradient
	tex.width = 128
	tex.height = 180
	return tex
