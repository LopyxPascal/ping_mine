import os
import sys
import time
import json
import math
import random
import socket
import struct
from dataclasses import dataclass

import pygame


# -----------------------------
# Android detection & settings
# -----------------------------
IS_ANDROID = (sys.platform == "android") or hasattr(sys, "getandroidapilevel") or hasattr(sys, "getandroidrelease")

# Виртуальное разрешение (рендерим сюда, потом масштабируем на экран)
# Для Android это СИЛЬНО снижает нагрузку: blit'ы идут в маленькую поверхность.
VIRTUAL_W, VIRTUAL_H = 960, 540

# FPS: на телефонах лучше 50-60, но 60 может быть тяжелее на слабых.
TARGET_FPS = 60 if not IS_ANDROID else 55

# Ограничения скорости мяча (чтобы не улетал в "пулемёт")
BALL_SPEED_X_MAX = 18.0
BALL_SPEED_Y_MAX = 14.0

# Высота/размер объектов в виртуальных координатах
PADDLE_W, PADDLE_H = 40, 150
BALL_SIZE = 26

# Сколько очков до победы
WIN_SCORE = 10


# -----------------------------
# Helpers: resources
# -----------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def res_path(name: str) -> str:
    return os.path.join(BASE_DIR, name)

def safe_load_image(name: str, size: tuple[int, int], fill_color: tuple[int, int, int], alpha: bool = True) -> pygame.Surface:
    """
    Загружает картинку, масштабирует, делает convert/convert_alpha.
    Если нет файла — создаёт заглушку.
    """
    try:
        img = pygame.image.load(res_path(name))
        img = pygame.transform.smoothscale(img, size)
        if alpha:
            return img.convert_alpha()
        return img.convert()
    except Exception as e:
        # Не скрываем полностью — на ПК будет видно, почему ассет не загрузился.
        if not IS_ANDROID:
            print(f"[WARN] Cannot load image {name}: {e}")
        surf = pygame.Surface(size, pygame.SRCALPHA if alpha else 0)
        surf.fill(fill_color)
        return surf.convert_alpha() if alpha else surf.convert()

def safe_load_sound(name: str):
    try:
        return pygame.mixer.Sound(res_path(name))
    except Exception as e:
        if not IS_ANDROID:
            print(f"[WARN] Cannot load sound {name}: {e}")
        return None


# -----------------------------
# Networking (safe TCP framing)
# -----------------------------
def send_packet(sock: socket.socket, payload: dict) -> None:
    data = json.dumps(payload).encode("utf-8")
    sock.sendall(struct.pack("!I", len(data)) + data)

def recv_exact(sock: socket.socket, n: int) -> bytes:
    buf = b""
    while len(buf) < n:
        chunk = sock.recv(n - len(buf))
        if not chunk:
            raise ConnectionError("Socket closed")
        buf += chunk
    return buf

def recv_packet(sock: socket.socket) -> dict:
    header = recv_exact(sock, 4)
    (length,) = struct.unpack("!I", header)
    data = recv_exact(sock, length)
    return json.loads(data.decode("utf-8"))


# -----------------------------
# Game state
# -----------------------------
@dataclass
class GameState:
    ly: float
    ry: float
    bx: float
    by: float
    ls: int
    rs: int
    lh: int
    rh: int

    @staticmethod
    def fresh():
        return GameState(
            ly=VIRTUAL_H / 2 - PADDLE_H / 2,
            ry=VIRTUAL_H / 2 - PADDLE_H / 2,
            bx=VIRTUAL_W / 2 - BALL_SIZE / 2,
            by=VIRTUAL_H / 2 - BALL_SIZE / 2,
            ls=0, rs=0, lh=0, rh=0
        )


# -----------------------------
# Particle system (cheap + pooled)
# -----------------------------
class Particle:
    __slots__ = ("x", "y", "vx", "vy", "life", "color")

    def __init__(self):
        self.x = 0.0
        self.y = 0.0
        self.vx = 0.0
        self.vy = 0.0
        self.life = 0
        self.color = (255, 255, 255)

    def reset(self, x: float, y: float, color: tuple[int, int, int]):
        self.x, self.y = x, y
        self.vx = random.uniform(-3.5, 3.5)
        self.vy = random.uniform(-3.5, 3.5)
        self.life = 18
        self.color = color

    def update_draw(self, surf: pygame.Surface):
        if self.life <= 0:
            return
        # маленькая "частица-блок"
        pygame.draw.rect(surf, self.color, (int(self.x), int(self.y), 5, 5))
        self.x += self.vx
        self.y += self.vy
        self.life -= 1


class ParticlePool:
    def __init__(self, max_particles: int = 220):
        self.pool = [Particle() for _ in range(max_particles)]
        self.active = []

    def spawn(self, x: float, y: float, color: tuple[int, int, int], count: int = 10):
        # Берём из пула. Если закончился — не создаём новые (важно для Android).
        for _ in range(count):
            if not self.pool:
                return
            p = self.pool.pop()
            p.reset(x, y, color)
            self.active.append(p)

    def update_draw(self, surf: pygame.Surface):
        # Обновляем активные, умершие возвращаем в пул.
        alive = []
        for p in self.active:
            p.update_draw(surf)
            if p.life > 0:
                alive.append(p)
            else:
                self.pool.append(p)
        self.active = alive

    def clear(self):
        self.pool.extend(self.active)
        self.active.clear()


# -----------------------------
# UI / Menu
# -----------------------------
def clamp(v: float, a: float, b: float) -> float:
    return a if v < a else b if v > b else v

def draw_text_center(surf: pygame.Surface, font: pygame.font.Font, text: str, y: int, color=(255, 255, 255)):
    img = font.render(text, True, color)
    surf.blit(img, (VIRTUAL_W // 2 - img.get_width() // 2, y))

def menu(screen_v: pygame.Surface, fonts: dict, biomes: dict) -> tuple[str, str]:
    """
    Возвращает (user_name, mode)
    Управление:
    - Android: тап по кнопкам; имя можно оставить дефолтным (клавы часто нет)
    - PC: клики + ввод в поле
    """
    clock = pygame.time.Clock()
    user_name = "Steve"
    mode = "SOLO"
    input_active = False

    input_rect = pygame.Rect(VIRTUAL_W // 2 - 160, VIRTUAL_H // 2 - 120, 320, 54)
    btn_solo   = pygame.Rect(VIRTUAL_W // 2 - 160, VIRTUAL_H // 2 - 40,  320, 64)
    btn_online = pygame.Rect(VIRTUAL_W // 2 - 160, VIRTUAL_H // 2 + 40,  320, 64)

    while True:
        screen_v.blit(biomes[1], (0, 0))
        draw_text_center(screen_v, fonts["big"], "CRAFT PONG", 50)

        # input
        pygame.draw.rect(screen_v, (50, 50, 50), input_rect, border_radius=10)
        border = (0, 238, 255) if input_active else (200, 200, 200)
        pygame.draw.rect(screen_v, border, input_rect, 3, border_radius=10)
        screen_v.blit(fonts["small"].render(user_name, True, (255, 255, 255)), (input_rect.x + 12, input_rect.y + 12))

        # buttons
        for btn, txt in ((btn_solo, "SINGLEPLAYER"), (btn_online, "MULTIPLAYER")):
            pygame.draw.rect(screen_v, (120, 120, 120), btn, border_radius=12)
            draw_text_center(screen_v, fonts["small"], txt, btn.y + 18)

        draw_text_center(screen_v, fonts["tiny"], "ESC = exit | Android: tap buttons", VIRTUAL_H - 40, (220, 220, 220))

        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                pygame.quit(); sys.exit()

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    pygame.quit(); sys.exit()
                if input_active and not IS_ANDROID:
                    if event.key == pygame.K_BACKSPACE:
                        user_name = user_name[:-1]
                    elif event.key == pygame.K_RETURN:
                        input_active = False
                    else:
                        if len(user_name) < 12 and event.unicode.isprintable():
                            user_name += event.unicode

            # клики/тапы
            if event.type == pygame.MOUSEBUTTONDOWN:
                mx, my = event.pos
                # в меню мы работаем в виртуальных координатах — но мышь приходит в координатах окна.
                # Это обработаем выше по стеку (в main) через функцию translate_event_pos.
                # Здесь считаем, что event.pos уже виртуальные.
                if input_rect.collidepoint((mx, my)) and not IS_ANDROID:
                    input_active = True
                else:
                    input_active = False
                    if btn_solo.collidepoint((mx, my)):
                        return user_name, "SOLO"
                    if btn_online.collidepoint((mx, my)):
                        return user_name, "ONLINE"

        clock.tick(TARGET_FPS)


# -----------------------------
# Main game
# -----------------------------
def run_game():
    # init pygame
    pygame.init()

    # На Android микшер иногда капризный — делаем попытку с меньшим буфером
    try:
        pygame.mixer.pre_init(44100, -16, 2, 256 if IS_ANDROID else 512)
        pygame.mixer.init()
    except Exception:
        pass

    # Window / screen
    info = pygame.display.Info()
    real_w, real_h = info.current_w or 800, info.current_h or 480

    flags = 0
    if IS_ANDROID:
        # На смартфонах почти всегда fullscreen
        flags |= pygame.FULLSCREEN
    else:
        flags |= 0

    screen = pygame.display.set_mode((real_w, real_h), flags)
    pygame.display.set_caption("Craft Pong: Diamond Edition (Android Optimized)")

    # scaling factor to map real->virtual
    # Будем рисовать на screen_v (VIRTUAL_W/H), потом scale на screen
    screen_v = pygame.Surface((VIRTUAL_W, VIRTUAL_H)).convert()

    def present():
        pygame.transform.smoothscale(screen_v, (real_w, real_h), screen)
        pygame.display.flip()

    def to_virtual_pos(px: int, py: int) -> tuple[int, int]:
        # перевод координат окна в виртуальные
        vx = int(px * (VIRTUAL_W / real_w))
        vy = int(py * (VIRTUAL_H / real_h))
        return vx, vy

    # fonts
    fonts = {
        "big": pygame.font.SysFont("monospace", 44, bold=True),
        "small": pygame.font.SysFont("monospace", 24, bold=True),
        "tiny": pygame.font.SysFont("monospace", 18, bold=True),
    }

    WHITE = (255, 255, 255)

    # resources (virtual-sized)
    biomes = {
        1: safe_load_image("grass.png", (VIRTUAL_W, VIRTUAL_H), (60, 170, 60), alpha=False),
        2: safe_load_image("sand.png",  (VIRTUAL_W, VIRTUAL_H), (200, 180, 100), alpha=False),
        3: safe_load_image("stone.png", (VIRTUAL_W, VIRTUAL_H), (100, 100, 100), alpha=False),
    }
    img_wood    = safe_load_image("wood.png",    (PADDLE_W, PADDLE_H), (134, 96, 67), alpha=True)
    img_diamond = safe_load_image("diamond.png", (PADDLE_W, PADDLE_H), (0, 238, 255), alpha=True)
    img_ball    = safe_load_image("ball.png",    (BALL_SIZE, BALL_SIZE), WHITE, alpha=True)

    sound_hit = safe_load_sound("hit.wav")

    # menu (with scaled mouse positions)
    clock = pygame.time.Clock()

    # Хак: меню ожидает MOUSEBUTTONDOWN в виртуальных координатах
    # Поэтому на время меню мы перехватываем события и подменяем pos.
    user_name, mode = None, None
    while True:
        # custom event pump for menu
        # translate mouse pos to virtual by injecting synthetic events
        evs = pygame.event.get()
        translated = []
        for e in evs:
            if e.type == pygame.MOUSEBUTTONDOWN:
                vx, vy = to_virtual_pos(*e.pos)
                translated.append(pygame.event.Event(pygame.MOUSEBUTTONDOWN, {"pos": (vx, vy), "button": getattr(e, "button", 1)}))
            elif e.type == pygame.QUIT:
                translated.append(e)
            elif e.type == pygame.KEYDOWN:
                translated.append(e)
        # push translated back and call menu loop "one tick"
        # (Мы проще: временно заменим очередь, но pygame так не умеет напрямую.
        # Поэтому — маленький трюк: вручную обработаем тут меню без отдельной функции? Нет.
        # Ок: сделаем меню в этом же цикле, чтобы позицию контролировать.)

        # ---- Inline menu rendering ----
        screen_v.blit(biomes[1], (0, 0))
        draw_text_center(screen_v, fonts["big"], "CRAFT PONG", 50)

        # UI rects
        input_rect = pygame.Rect(VIRTUAL_W // 2 - 160, VIRTUAL_H // 2 - 120, 320, 54)
        btn_solo   = pygame.Rect(VIRTUAL_W // 2 - 160, VIRTUAL_H // 2 - 40,  320, 64)
        btn_online = pygame.Rect(VIRTUAL_W // 2 - 160, VIRTUAL_H // 2 + 40,  320, 64)

        if user_name is None:
            user_name = "Steve"
        if mode is None:
            mode = "SOLO"
        input_active = False if IS_ANDROID else False

        pygame.draw.rect(screen_v, (50, 50, 50), input_rect, border_radius=10)
        pygame.draw.rect(screen_v, (200, 200, 200), input_rect, 3, border_radius=10)
        screen_v.blit(fonts["small"].render(user_name, True, WHITE), (input_rect.x + 12, input_rect.y + 12))

        for btn, txt in ((btn_solo, "SINGLEPLAYER"), (btn_online, "MULTIPLAYER")):
            pygame.draw.rect(screen_v, (120, 120, 120), btn, border_radius=12)
            draw_text_center(screen_v, fonts["small"], txt, btn.y + 18)

        draw_text_center(screen_v, fonts["tiny"], "Android: tap | PC: click + type | ESC: exit", VIRTUAL_H - 40, (220, 220, 220))
        present()

        chosen = None
        for e in evs:
            if e.type == pygame.QUIT:
                pygame.quit(); sys.exit()
            if e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE:
                pygame.quit(); sys.exit()

            if e.type == pygame.KEYDOWN and not IS_ANDROID:
                # allow name typing if clicked — simplified (optional)
                pass

            if e.type == pygame.MOUSEBUTTONDOWN:
                vx, vy = to_virtual_pos(*e.pos)
                if btn_solo.collidepoint((vx, vy)):
                    chosen = "SOLO"
                elif btn_online.collidepoint((vx, vy)):
                    chosen = "ONLINE"

        if chosen:
            mode = chosen
            break

        clock.tick(TARGET_FPS)

    # game init
    gs = GameState.fresh()
    particles = ParticlePool(max_particles=240 if not IS_ANDROID else 180)

    # ball velocity
    ball_dx = 8.0 * (1 if random.random() < 0.5 else -1)
    ball_dy = random.choice([-6.0, -4.5, 4.5, 6.0])

    screen_shake = 0
    game_over = False

    # input
    touch_y = VIRTUAL_H / 2
    my_y_target = gs.ly

    # ONLINE client
    client = None
    if mode == "ONLINE":
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(2.0)
            client.connect(("127.0.0.1", 5555))
            # handshake
            send_packet(client, {"hello": user_name, "w": VIRTUAL_W, "h": VIRTUAL_H})
            _ = recv_packet(client)
        except Exception:
            mode = "SOLO"
            client = None

    def reset_round(scored_left: bool | None = None):
        nonlocal ball_dx, ball_dy, game_over, screen_shake
        gs.bx = VIRTUAL_W / 2 - BALL_SIZE / 2
        gs.by = VIRTUAL_H / 2 - BALL_SIZE / 2
        # Направление после гола
        if scored_left is None:
            ball_dx = 8.0 * (1 if random.random() < 0.5 else -1)
        else:
            ball_dx = -8.0 if scored_left else 8.0  # если забил левый -> мяч к правому
        ball_dy = random.choice([-6.0, -4.5, 4.5, 6.0])
        screen_shake = 0
        game_over = False
        particles.clear()
        gs.lh = 0
        gs.rh = 0

    # Precompute static X positions
    P1_X = 40
    P2_X = VIRTUAL_W - 80

    running = True
    while running:
        dt = clock.tick(TARGET_FPS) / 1000.0
        # ограничим dt, чтобы при лаге физика не улетала
        dt = min(dt, 1/30)

        # biome by max score
        biome_idx = min(3, (max(gs.ls, gs.rs) // 4) + 1)
        screen_v.blit(biomes[biome_idx], (0, 0))

        # events
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                if game_over and event.key == pygame.K_r:
                    gs = GameState.fresh()
                    reset_round()
                # PC control optional: W/S or arrows
                # (на Android обычно не нужно)
            if event.type in (pygame.FINGERDOWN, pygame.FINGERMOTION):
                touch_y = event.y * VIRTUAL_H
            if event.type == pygame.MOUSEMOTION:
                # мышь в координатах окна -> перевести в виртуальные
                vx, vy = to_virtual_pos(*event.pos)
                touch_y = vy
            if event.type == pygame.MOUSEBUTTONDOWN and game_over:
                # тап по экрану тоже перезапускает
                gs = GameState.fresh()
                reset_round()

        # my paddle target
        my_y_target = clamp(touch_y - PADDLE_H / 2, 0, VIRTUAL_H - PADDLE_H)

        # SOLO logic
        if mode == "SOLO" and not game_over:
            # Мягкое следование (приятнее на таче, меньше дрожания)
            gs.ly += (my_y_target - gs.ly) * (0.35 if IS_ANDROID else 0.5)

            # Move ball (independent of dt via base speed scaling)
            gs.bx += ball_dx * (dt * 60.0)
            gs.by += ball_dy * (dt * 60.0)

            # Walls
            if gs.by <= 0:
                gs.by = 0
                ball_dy = abs(ball_dy)
            elif gs.by >= VIRTUAL_H - BALL_SIZE:
                gs.by = VIRTUAL_H - BALL_SIZE
                ball_dy = -abs(ball_dy)

            # Bot (simple AI) — тоже с clamp
            # Чуть медленнее на Android для баланса
            bot_speed = 6.5 if not IS_ANDROID else 6.0
            bot_center = gs.ry + PADDLE_H / 2
            ball_center = gs.by + BALL_SIZE / 2
            if bot_center < ball_center:
                gs.ry += bot_speed
            else:
                gs.ry -= bot_speed
            gs.ry = clamp(gs.ry, 0, VIRTUAL_H - PADDLE_H)

            # Rects for collision (robust)
            ball_rect = pygame.Rect(int(gs.bx), int(gs.by), BALL_SIZE, BALL_SIZE)
            p1_rect = pygame.Rect(P1_X, int(gs.ly), PADDLE_W, PADDLE_H)
            p2_rect = pygame.Rect(P2_X, int(gs.ry), PADDLE_W, PADDLE_H)

            # Diamond logic: after 5 hits
            p1_diamond = gs.lh >= 5
            p2_diamond = gs.rh >= 5

            hit = None
            if ball_rect.colliderect(p1_rect) and ball_dx < 0:
                hit = "L"
            elif ball_rect.colliderect(p2_rect) and ball_dx > 0:
                hit = "R"

            if hit:
                # Screen shake
                screen_shake = 7 if not IS_ANDROID else 5
                if sound_hit:
                    try:
                        sound_hit.play()
                    except Exception:
                        pass

                # "Angle by impact position" (proper Pong feel)
                if hit == "L":
                    gs.lh += 1
                    impact = ((ball_center) - (gs.ly + PADDLE_H / 2)) / (PADDLE_H / 2)
                    impact = clamp(impact, -1.0, 1.0)

                    # push ball outside paddle to avoid sticking
                    gs.bx = P1_X + PADDLE_W + 1
                    ball_dx = abs(ball_dx) + 0.35
                    ball_dy = impact * BALL_SPEED_Y_MAX

                    p_col = (0, 238, 255) if p1_diamond else (134, 96, 67)
                    particles.spawn(gs.bx, gs.by, p_col, 10 if not IS_ANDROID else 7)
                else:
                    gs.rh += 1
                    impact = ((ball_center) - (gs.ry + PADDLE_H / 2)) / (PADDLE_H / 2)
                    impact = clamp(impact, -1.0, 1.0)

                    gs.bx = P2_X - BALL_SIZE - 1
                    ball_dx = -(abs(ball_dx) + 0.35)
                    ball_dy = impact * BALL_SPEED_Y_MAX

                    p_col = (0, 238, 255) if p2_diamond else (134, 96, 67)
                    particles.spawn(gs.bx, gs.by, p_col, 10 if not IS_ANDROID else 7)

                # clamp speed
                ball_dx = clamp(ball_dx, -BALL_SPEED_X_MAX, BALL_SPEED_X_MAX)
                ball_dy = clamp(ball_dy, -BALL_SPEED_Y_MAX, BALL_SPEED_Y_MAX)

            # Goals
            if gs.bx < -BALL_SIZE:
                gs.rs += 1
                reset_round(scored_left=False)
            elif gs.bx > VIRTUAL_W + BALL_SIZE:
                gs.ls += 1
                reset_round(scored_left=True)

            if gs.ls >= WIN_SCORE or gs.rs >= WIN_SCORE:
                game_over = True

        # ONLINE logic (client)
        elif mode == "ONLINE" and not game_over:
            try:
                send_packet(client, {"y": float(my_y_target)})
                resp = recv_packet(client)
                # expected fields
                gs.ly = float(resp.get("ly", gs.ly))
                gs.ry = float(resp.get("ry", gs.ry))
                gs.bx = float(resp.get("bx", gs.bx))
                gs.by = float(resp.get("by", gs.by))
                gs.ls = int(resp.get("ls", gs.ls))
                gs.rs = int(resp.get("rs", gs.rs))
                gs.lh = int(resp.get("lh", gs.lh))
                gs.rh = int(resp.get("rh", gs.rh))
                game_over = bool(resp.get("over", False))
            except Exception:
                # fallback to SOLO on disconnect
                mode = "SOLO"
                try:
                    if client:
                        client.close()
                except Exception:
                    pass
                client = None

        # Shake offsets (cheap)
        off_x = off_y = 0
        if screen_shake > 0:
            off_x = random.randint(-screen_shake, screen_shake)
            off_y = random.randint(-screen_shake, screen_shake)
            screen_shake -= 1

        # Draw paddles & ball
        p1_img = img_diamond if gs.lh >= 5 else img_wood
        p2_img = img_diamond if gs.rh >= 5 else img_wood

        screen_v.blit(p1_img, (P1_X + off_x, int(gs.ly) + off_y))
        screen_v.blit(p2_img, (P2_X + off_x, int(gs.ry) + off_y))
        screen_v.blit(img_ball, (int(gs.bx) + off_x, int(gs.by) + off_y))

        # Particles
        particles.update_draw(screen_v)

        # Score
        score_img = fonts["big"].render(f"{gs.ls} - {gs.rs}", True, WHITE)
        screen_v.blit(score_img, (VIRTUAL_W // 2 - score_img.get_width() // 2, 18))

        # Hint
        hint = "Tap/Move finger to control | R to restart" if IS_ANDROID else "Mouse to control | R restart | ESC exit"
        hint_img = fonts["tiny"].render(hint, True, (230, 230, 230))
        screen_v.blit(hint_img, (VIRTUAL_W // 2 - hint_img.get_width() // 2, VIRTUAL_H - 30))

        # Game over overlay
        if game_over:
            if mode == "SOLO":
                msg = "YOU WIN!" if gs.ls >= WIN_SCORE else "YOU LOSE!"
            else:
                msg = "GAME OVER"
            overlay = pygame.Surface((VIRTUAL_W, VIRTUAL_H), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 140))
            screen_v.blit(overlay, (0, 0))
            draw_text_center(screen_v, fonts["big"], msg, VIRTUAL_H // 2 - 40, (255, 215, 0))
            draw_text_center(screen_v, fonts["small"], "Press R or Tap to restart", VIRTUAL_H // 2 + 20, WHITE)

        present()

    # cleanup
    try:
        if client:
            client.close()
    except Exception:
        pass
    pygame.quit()


# -----------------------------
# Optional: simple server (PC use)
# -----------------------------
def run_server(host="0.0.0.0", port=5555):
    """
    Простой сервер на 2 клиента (левый/правый).
    Для Android обычно не нужен — но для тестов на ПК пригодится.

    Протокол:
    - клиент: {"hello": name, "w":..., "h":...}
    - сервер: {"ok": true, "side": "L"|"R"}
    - клиент периодически: {"y": my_y}
    - сервер отвечает: game state json
    """
    pygame.init()

    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind((host, port))
    srv.listen(2)
    print(f"[SERVER] Listening on {host}:{port}")

    clients = []
    sides = []

    def accept_one(side_label):
        c, addr = srv.accept()
        c.settimeout(5.0)
        hello = recv_packet(c)
        send_packet(c, {"ok": True, "side": side_label})
        print(f"[SERVER] {side_label} connected from {addr}, hello={hello}")
        return c

    # accept two clients
    cL = accept_one("L")
    cR = accept_one("R")
    clients = [cL, cR]
    sides = ["L", "R"]

    gs = GameState.fresh()
    ball_dx = 8.0 * (1 if random.random() < 0.5 else -1)
    ball_dy = random.choice([-6.0, -4.5, 4.5, 6.0])
    over = False

    def reset_round(scored_left: bool | None = None):
        nonlocal ball_dx, ball_dy, over
        gs.bx = VIRTUAL_W / 2 - BALL_SIZE / 2
        gs.by = VIRTUAL_H / 2 - BALL_SIZE / 2
        if scored_left is None:
            ball_dx = 8.0 * (1 if random.random() < 0.5 else -1)
        else:
            ball_dx = -8.0 if scored_left else 8.0
        ball_dy = random.choice([-6.0, -4.5, 4.5, 6.0])
        gs.lh = 0
        gs.rh = 0
        over = False

    # server tick
    last = time.time()
    try:
        while True:
            now = time.time()
            dt = now - last
            last = now
            dt = min(dt, 1/30)

            # recv both
            try:
                dataL = recv_packet(cL)
                dataR = recv_packet(cR)
                gs.ly = clamp(float(dataL.get("y", gs.ly)), 0, VIRTUAL_H - PADDLE_H)
                gs.ry = clamp(float(dataR.get("y", gs.ry)), 0, VIRTUAL_H - PADDLE_H)
            except Exception as e:
                print("[SERVER] client disconnected:", e)
                break

            if not over:
                # ball
                gs.bx += ball_dx * (dt * 60.0)
                gs.by += ball_dy * (dt * 60.0)

                if gs.by <= 0:
                    gs.by = 0
                    ball_dy = abs(ball_dy)
                elif gs.by >= VIRTUAL_H - BALL_SIZE:
                    gs.by = VIRTUAL_H - BALL_SIZE
                    ball_dy = -abs(ball_dy)

                # collision
                ball_rect = pygame.Rect(int(gs.bx), int(gs.by), BALL_SIZE, BALL_SIZE)
                p1_rect = pygame.Rect(40, int(gs.ly), PADDLE_W, PADDLE_H)
                p2_rect = pygame.Rect(VIRTUAL_W - 80, int(gs.ry), PADDLE_W, PADDLE_H)

                hit = None
                if ball_rect.colliderect(p1_rect) and ball_dx < 0:
                    hit = "L"
                elif ball_rect.colliderect(p2_rect) and ball_dx > 0:
                    hit = "R"

                if hit:
                    ball_center = gs.by + BALL_SIZE / 2
                    if hit == "L":
                        gs.lh += 1
                        impact = ((ball_center) - (gs.ly + PADDLE_H / 2)) / (PADDLE_H / 2)
                        impact = clamp(impact, -1.0, 1.0)
                        gs.bx = 40 + PADDLE_W + 1
                        ball_dx = abs(ball_dx) + 0.35
                        ball_dy = impact * BALL_SPEED_Y_MAX
                    else:
                        gs.rh += 1
                        impact = ((ball_center) - (gs.ry + PADDLE_H / 2)) / (PADDLE_H / 2)
                        impact = clamp(impact, -1.0, 1.0)
                        gs.bx = (VIRTUAL_W - 80) - BALL_SIZE - 1
                        ball_dx = -(abs(ball_dx) + 0.35)
                        ball_dy = impact * BALL_SPEED_Y_MAX

                    ball_dx = clamp(ball_dx, -BALL_SPEED_X_MAX, BALL_SPEED_X_MAX)
                    ball_dy = clamp(ball_dy, -BALL_SPEED_Y_MAX, BALL_SPEED_Y_MAX)

                # goals
                if gs.bx < -BALL_SIZE:
                    gs.rs += 1
                    reset_round(scored_left=False)
                elif gs.bx > VIRTUAL_W + BALL_SIZE:
                    gs.ls += 1
                    reset_round(scored_left=True)

                if gs.ls >= WIN_SCORE or gs.rs >= WIN_SCORE:
                    over = True

            payload = {
                "ly": gs.ly, "ry": gs.ry, "bx": gs.bx, "by": gs.by,
                "ls": gs.ls, "rs": gs.rs, "lh": gs.lh, "rh": gs.rh,
                "over": over
            }
            # send to both
            try:
                send_packet(cL, payload)
                send_packet(cR, payload)
            except Exception as e:
                print("[SERVER] send failed:", e)
                break

    finally:
        for c in (cL, cR):
            try: c.close()
            except Exception: pass
        try: srv.close()
        except Exception: pass
        pygame.quit()


if __name__ == "__main__":
    # run as: python game.py server
    if len(sys.argv) >= 2 and sys.argv[1].lower() == "server":
        run_server()
    else:
        run_game()