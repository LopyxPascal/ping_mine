[app]
title = Craft Pong Diamond
package.name = craftpong
package.domain = org.mugen

version = 1.0

source.dir = .
source.main = main.py

# Включаем ассеты гарантированно
source.include_exts = py,png,jpg,jpeg,wav,ogg,mp3,ttf,txt,json
source.include_patterns = assets/*

source.exclude_exts = pyc,pyo,pyd,so,dylib
source.exclude_dirs = __pycache__,.git,.idea,.vscode,build,dist,bin,.venv,venv

# Pygame-ce оставляем как у тебя (на Android часто стабильнее)
requirements = python3,pygame-ce

# SDL2 bootstrap
p4a.bootstrap = sdl2

# Экран
orientation = landscape
fullscreen = 1

# Разрешения (если онлайн реально не нужен — можешь потом убрать INTERNET)
android.permissions = INTERNET,WAKE_LOCK

# Версии Android
android.api = 34
android.minapi = 21

# СТАБИЛИЗАТОРЫ (важно)
android.accept_sdk_license = True
android.ndk = 25b
android.archs = arm64-v8a,armeabi-v7a

# Хранилище/AndroidX
android.private_storage = True
android.use_androidx = True

log_level = 2

[buildozer]
log_level = 2
build_dir = .buildozer
warn_on_root = 1