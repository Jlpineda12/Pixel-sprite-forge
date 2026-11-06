extends CharacterBody2D
## Personaje top-down de 8 direcciones para sprites de Pixel Sprite Forge.
##
## Escena mínima:
##   CharacterBody2D (este script)
##   ├── AnimatedSprite2D  → sprite_frames = character_frames.tres
##   │                       (o character_frames_lit.tres para luces 2D)
##   └── CollisionShape2D
##
## Las animaciones se llaman "<accion>_<direccion>", p. ej. "walk_SE".
## Funciona con hojas de 8 direcciones y también con 4 (cae a la cardinal).

@export var speed := 80.0
@export var idle_action := "idle"
@export var walk_action := "walk"
@export var attack_action := "attack"

@onready var sprite: AnimatedSprite2D = $AnimatedSprite2D

# Orden por ángulo en pantalla (y hacia abajo): 0 rad = derecha (E), PI/2 = abajo (S).
const DIRS_8 := ["E", "SE", "S", "SW", "W", "NW", "N", "NE"]
const DIRS_4 := ["E", "S", "W", "N"]

var facing := "S"
var attacking := false


func _ready() -> void:
	sprite.animation_finished.connect(_on_animation_finished)
	sprite.texture_filter = CanvasItem.TEXTURE_FILTER_NEAREST  # píxeles nítidos
	_play(idle_action)


func _physics_process(_delta: float) -> void:
	if attacking:
		return
	var input := Input.get_vector("ui_left", "ui_right", "ui_up", "ui_down")
	velocity = input * speed
	move_and_slide()

	if Input.is_action_just_pressed("ui_accept") and _has(attack_action):
		attacking = true
		_play(attack_action)
		return

	if input != Vector2.ZERO:
		facing = direction_from_vector(input)
		_play(walk_action)
	else:
		_play(idle_action)


func direction_from_vector(v: Vector2) -> String:
	if _has_any_diagonal():
		return DIRS_8[posmod(roundi(v.angle() / (PI / 4.0)), 8)]
	return DIRS_4[posmod(roundi(v.angle() / (PI / 2.0)), 4)]


func _play(action: String) -> void:
	var anim_name := "%s_%s" % [action, facing]
	if not sprite.sprite_frames.has_animation(anim_name):
		# sin animación "idle": usa el primer frame de "walk"
		anim_name = "%s_%s" % [walk_action, facing]
		if sprite.animation != anim_name:
			sprite.play(anim_name)
		sprite.pause()
		sprite.frame = 0
		return
	if sprite.animation != anim_name or not sprite.is_playing():
		sprite.play(anim_name)


func _has(action: String) -> bool:
	return sprite.sprite_frames.has_animation("%s_%s" % [action, facing])


func _has_any_diagonal() -> bool:
	return sprite.sprite_frames.has_animation("%s_SE" % walk_action)


func _on_animation_finished() -> void:
	if attacking:
		attacking = false
		_play(idle_action)
