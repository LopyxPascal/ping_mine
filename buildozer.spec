[app]

# Название приложения
title = Craft Pong Diamond

# Имя пакета (без пробелов)
package.name = craftpong

# Домен (любой свой)
package.domain = org.mugen

# Папка проекта
source.dir = .

# Главный файл
source.main = main.py

# ВАЖНО: версия обязательна
version = 1.0

# Что включать в APK
source.include_exts = py,png,jpg,jpeg,wav,ogg,mp3,ttf,txt,json
source.include_patterns = assets/*

# Что исключать
source.exclude_exts = pyc,pyo,pyd,so,dylib
source.exclude_dirs = __pycache__,.git,.idea,.vscode,build,dist,bin,.venv,venv

# Требования (pygame-ce стабильнее на Android)
requirements = python3,pygame-ce

# Экран
orientation = landscape
fullscreen = 1

# Разрешения
android.permissions = INTERNET,WAKE_LOCK

# Android API
android.api = 34
android.minapi = 21

# Используем SDL2 bootstrap (обязательно для pygame)
p4a.bootstrap = sdl2

# Приватное хранилище
android.private_storage = True

# Использовать AndroidX
android.use_androidx = True

# Логирование
log_level = 2


[buildozer]

log_level = 2
build_dir = .buildozer