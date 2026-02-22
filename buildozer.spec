[app]
title = Craft Pong Diamond
package.name = craftpong
package.domain = org.mugen

source.dir = .
source.main = main.py

version = 1.0

source.include_exts = py,png,jpg,jpeg,wav,ogg,mp3,ttf,txt,json
source.include_patterns = assets/*

source.exclude_exts = pyc,pyo,pyd,so,dylib
source.exclude_dirs = __pycache__,.git,.idea,.vscode,build,dist,bin,.venv,venv

requirements = python3,pygame-ce

orientation = landscape
fullscreen = 1

# Если онлайн реально не нужен — лучше убрать INTERNET (но можно оставить)
android.permissions = INTERNET,WAKE_LOCK

android.api = 34
android.minapi = 21

p4a.bootstrap = sdl2

android.private_storage = True
android.use_androidx = True

# ВОТ ЭТИ 3 — самые полезные добавки
android.accept_sdk_license = True
android.ndk = 25b
android.archs = arm64-v8a,armeabi-v7a

log_level = 2

[buildozer]
log_level = 2
build_dir = .buildozer
warn_on_root = 1