[app]
title = Craft Pong Diamond
package.name = craftpong
package.domain = org.mugen

source.dir = .
source.main = main.py

# Чтобы ассеты точно попали в APK:
source.include_exts = py,png,jpg,jpeg,wav,ogg,mp3,ttf,json,txt
# Если ассеты в папке assets:
source.include_patterns = assets/*

requirements = python3,pygame-ce
orientation = landscape
fullscreen = 1

android.permissions = INTERNET,WAKE_LOCK
android.api = 34
android.minapi = 21
p4a.bootstrap = sdl2
android.private_storage = True