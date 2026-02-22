import os
import sys
import time
import json
import random
import socket
import struct
import traceback
from dataclasses import dataclass

import pygame

# -----------------------------
# Android detection (safe)
# -----------------------------
IS_ANDROID = (
    sys.platform == "android"
    or hasattr(sys, "getandroidapilevel")
    or hasattr(sys, "getandroidrelease")
)

# -----------------------------
# Crash log helpers
# -----------------------------
def _try_get_writable_dir() -> str:
    try:
        import android.storage  # type: ignore
        p = android.storage.app_storage_path()
        if p and os.path.isdir(p):
            return p
    except Exception:
        pass

    try:
        base = os.path.dirname(os.path.abspath(__file__))
        if base and os.path.isdir(base):
            return base
    except Exception:
        pass

    return os.getcwd()

CRASH_DIR = _try_get_writable_dir()
CRASH_LOG_PATH = os.path.join(CRASH_DIR, "crashlog.txt")

def write_crash_log(exc: BaseException) -> None:
    try:
        with open(CRASH_LOG_PATH, "w", encoding="utf-8") as f:
            f.write("=== CRASH LOG ===\n")
            f.write(time.strftime("%Y-%m-%d %H:%M:%S") + "\n\n")
            f.write("Platform: " + sys.platform + "\n")
            f.write("Android: " + str(IS_ANDROID) + "\n\n")
            f.write("Exception:\n")
            f.write("".join(traceback.format_exception(type(exc), exc, exc.__traceback__)))
    except Exception:
        pass


# -----------------------------
# Networking (optional, safe framing)
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
# Game constants (Android friendly)
# -----------------------------
VIRTUAL_W, VIRTUAL_H = 960, 540
TARGET_FPS = 55 if IS_ANDROID else 60

PADDLE_W, PADDLE_H = 40, 150
BALL_SIZE = 26
WIN_SCORE = 10

BALL_SPEED_X_MAX = 18.0
BALL_SPEED_Y_MAX = 14.0

WHITE = (255, 255, 255)

# Smaller paddle tile
PADDLE_TILE_MAX = 16

def clamp(v: float, a: float, b: float) -> float:
    return a if v < a else b if v > b else v


# -----------------------------
# Resources (assets-only)
# -----------------------------
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def asset_path(name: str) -> str:
    return os.path.join(BASE_DIR, "assets", name)

def safe_load_image_raw(path: str) -> pygame.Surface | None:
    try:
        return pygame.image.load(path)
    except Exception:
        return None

def make_placeholder(size: tuple[int, int], color: tuple[int, int, int], alpha: bool) -> pygame.Surface:
    surf = pygame.Surface(size, pygame.SRCALPHA if alpha else 0)
    surf.fill(color)
    return surf

def safe_load_sound(path: str):
    try:
        return pygame.mixer.Sound(path)
    except Exception:
        return None


# -----------------------------
# Texture prep (shrink big tiles)
# -----------------------------
def shrink_to_tile(tex: pygame.Surface, max_tile: int = 16) -> pygame.Surface:
    w, h = tex.get_width(), tex.get_height()
    if w <= 0 or h <= 0:
        return tex

    m = max(w, h)
    if m <= max_tile:
        return tex

    scale = max_tile / float(m)
    nw = max(1, int(w * scale))
    nh = max(1, int(h * scale))

    try:
        return pygame.transform.smoothscale(tex, (nw, nh))
    except Exception:
        return pygame.transform.scale(tex, (nw, nh))


# -----------------------------
# Tile helpers (real textures, no stretching)
# -----------------------------
def tile_texture(texture: pygame.Surface, out_size: tuple[int, int]) -> pygame.Surface:
    out_w, out_h = out_size
    tiled = pygame.Surface((out_w, out_h)).convert()

    tex = texture.convert() if texture.get_alpha() is None else texture.convert_alpha()
    tw, th = tex.get_width(), tex.get_height()
    if tw <= 0 or th <= 0:
        return tiled

    for y in range(0, out_h, th):
        for x in range(0, out_w, tw):
            tiled.blit(tex, (x, y))
    return tiled

def make_tiled_paddle(texture: pygame.Surface, size: tuple[int, int], tile_max: int = 16) -> pygame.Surface:
    w, h = size
    out = pygame.Surface((w, h), pygame.SRCALPHA)

    tex = texture.convert_alpha() if texture.get_alpha() is not None else texture.convert()
    tex = shrink_to_tile(tex, max_tile=tile_max)

    tw, th = tex.get_width(), tex.get_height()
    if tw <= 0 or th <= 0:
        return out

    for y in range(0, h, th):
        for x in range(0, w, tw):
            out.blit(tex, (x, y))

    pygame.draw.rect(out, (0, 0, 0, 90), out.get_rect(), 2)
    return out


# -----------------------------
# Particle pool (low allocations)
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

    def reset(self, x: float, y: float, color):
        self.x, self.y = x, y
        self.vx = random.uniform(-3.5, 3.5)
        self.vy = random.uniform(-3.5, 3.5)
        self.life = 18
        self.color = color

    def update_draw(self, surf: pygame.Surface):
        if self.life <= 0:
            return
        pygame.draw.rect(surf, self.color, (int(self.x), int(self.y), 5, 5))
        self.x += self.vx
        self.y += self.vy
        self.life -= 1


class ParticlePool:
    def __init__(self, max_particles: int):
        self.pool = [Particle() for _ in range(max_particles)]
        self.active: list[Particle] = []

    def spawn(self, x: float, y: float, color, count: int):
        for _ in range(count):
            if not self.pool:
                return
            p = self.pool.pop()
            p.reset(x, y, color)
            self.active.append(p)

    def update_draw(self, surf: pygame.Surface):
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
# UI helpers
# -----------------------------
def draw_text_center(surf: pygame.Surface, font: pygame.font.Font, text: str, y: int, color=WHITE):
    img = font.render(text, True, color)
    surf.blit(img, (VIRTUAL_W // 2 - img.get_width() // 2, y))

def shorten(s: str, n: int = 64) -> str:
    if len(s) <= n:
        return s
    return s[: n - 3] + "..."


# -----------------------------
# Main game
# -----------------------------
def run_game():
    pygame.init()

    # ---- Mixer (safe) ----
    audio_ok = False
    mixer_error = ""
    try:
        pygame.mixer.pre_init(44100, -16, 2, 256 if IS_ANDROID else 512)
        pygame.mixer.init()
        audio_ok = True
    except Exception as e:
        audio_ok = False
        mixer_error = f"{type(e).__name__}: {e}"

    # ---- Display ----
    info = pygame.display.Info()
    real_w = info.current_w or 800
    real_h = info.current_h or 480

    flags = pygame.FULLSCREEN if IS_ANDROID else 0
    screen = pygame.display.set_mode((real_w, real_h), flags)
    pygame.display.set_caption("Craft Pong: Diamond Edition (Android-safe)")

    screen_v = pygame.Surface((VIRTUAL_W, VIRTUAL_H)).convert()

    def present():
        scaled = pygame.transform.scale(screen_v, (real_w, real_h))
        screen.blit(scaled, (0, 0))
        pygame.display.flip()

    def to_virtual_pos(px: int, py: int) -> tuple[int, int]:
        return int(px * (VIRTUAL_W / real_w)), int(py * (VIRTUAL_H / real_h))

    # ---- Fonts ----
    fonts = {
        "big": pygame.font.SysFont("monospace", 44, bold=True),
        "small": pygame.font.SysFont("monospace", 24, bold=True),
        "tiny": pygame.font.SysFont("monospace", 18, bold=True),
    }

    # ---- Load textures ----
    def load_tex_or_placeholder(filename: str, placeholder_color: tuple[int, int, int], alpha: bool) -> pygame.Surface:
        p = asset_path(filename)
        img0 = safe_load_image_raw(p)
        if img0 is None:
            ph = make_placeholder((64, 64), placeholder_color, alpha=alpha)
            return ph.convert_alpha() if alpha else ph.convert()
        try:
            return img0.convert_alpha() if alpha else img0.convert()
        except Exception:
            return img0

    grass_tex = load_tex_or_placeholder("grass.png", (60, 170, 60), alpha=False)
    sand_tex  = load_tex_or_placeholder("sand.png",  (200, 180, 100), alpha=False)
    stone_tex = load_tex_or_placeholder("stone.png", (100, 100, 100), alpha=False)

    BIOMES = {
        1: tile_texture(grass_tex, (VIRTUAL_W, VIRTUAL_H)),
        2: tile_texture(sand_tex,  (VIRTUAL_W, VIRTUAL_H)),
        3: tile_texture(stone_tex, (VIRTUAL_W, VIRTUAL_H)),
    }

    wood_tex = load_tex_or_placeholder("wood.png", (134, 96, 67), alpha=True)
    diamond_tex = load_tex_or_placeholder("diamond.png", (0, 238, 255), alpha=True)

    img_wood = make_tiled_paddle(wood_tex, (PADDLE_W, PADDLE_H), tile_max=PADDLE_TILE_MAX)
    img_diamond = make_tiled_paddle(diamond_tex, (PADDLE_W, PADDLE_H), tile_max=PADDLE_TILE_MAX)

    ball_raw = safe_load_image_raw(asset_path("ball.png"))
    if ball_raw is None:
        img_ball = make_placeholder((BALL_SIZE, BALL_SIZE), WHITE, alpha=True).convert_alpha()
    else:
        try:
            ball_raw = ball_raw.convert_alpha()
        except Exception:
            pass
        img_ball = pygame.transform.smoothscale(ball_raw, (BALL_SIZE, BALL_SIZE)).convert_alpha()

    # WAV stays as-is
    sound_hit = safe_load_sound(asset_path("hit.wav")) if audio_ok else None

    # ---- MENU MUSIC: MP3 ----
    menu_music_path = asset_path("menu_music.mp3")
    music_status = ""
    music_loaded = False
    music_error = ""

    if not audio_ok:
        music_status = "MUSIC: OFF (mixer init failed)"
    else:
        try:
            pygame.mixer.music.load(menu_music_path)
            pygame.mixer.music.set_volume(0.6)
            music_loaded = True
            music_status = "MUSIC: READY (mp3)"
        except Exception as e:
            music_loaded = False
            music_error = f"{type(e).__name__}: {e}"
            music_status = "MUSIC: FAIL (mp3)"

    # ---- Menu ----
    mode = "SOLO"
    user_name = "Steve"
    ALLOW_ONLINE = True

    clock = pygame.time.Clock()
    btn_solo = pygame.Rect(VIRTUAL_W // 2 - 160, VIRTUAL_H // 2 - 40, 320, 64)
    btn_online = pygame.Rect(VIRTUAL_W // 2 - 160, VIRTUAL_H // 2 + 40, 320, 64)

    if audio_ok and music_loaded:
        try:
            pygame.mixer.music.play(-1)
            music_status = "MUSIC: PLAYING (mp3)"
        except Exception as e:
            music_error = f"{type(e).__name__}: {e}"
            music_status = "MUSIC: PLAY FAIL (mp3)"

    while True:
        screen_v.blit(BIOMES[1], (0, 0))
        draw_text_center(screen_v, fonts["big"], "CRAFT PONG", 45)
        draw_text_center(screen_v, fonts["tiny"], f"PADDLE TILE: {PADDLE_TILE_MAX}px (shrunken before tiling)", 100, (220, 220, 220))

        # music status + debug
        draw_text_center(screen_v, fonts["tiny"], music_status, 130, (255, 215, 0))
        draw_text_center(screen_v, fonts["tiny"], "music path: " + shorten(menu_music_path, 72), 155, (230, 230, 230))
        if music_error:
            draw_text_center(screen_v, fonts["tiny"], "music err: " + shorten(music_error, 72), 180, (230, 230, 230))
        if not audio_ok and mixer_error:
            draw_text_center(screen_v, fonts["tiny"], "mixer err: " + shorten(mixer_error, 72), 205, (230, 230, 230))

        pygame.draw.rect(screen_v, (120, 120, 120), btn_solo, border_radius=12)
        draw_text_center(screen_v, fonts["small"], "SINGLEPLAYER", btn_solo.y + 18)

        pygame.draw.rect(screen_v, (120, 120, 120), btn_online, border_radius=12)
        draw_text_center(screen_v, fonts["small"], "MULTIPLAYER", btn_online.y + 18)

        draw_text_center(screen_v, fonts["tiny"], "Back/ESC: exit", VIRTUAL_H - 28, (230, 230, 230))
        present()

        chosen = None
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                return
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                return

            if event.type == pygame.MOUSEBUTTONDOWN:
                vx, vy = to_virtual_pos(*event.pos)
                if btn_solo.collidepoint((vx, vy)):
                    chosen = "SOLO"
                elif btn_online.collidepoint((vx, vy)):
                    chosen = "ONLINE" if ALLOW_ONLINE else "SOLO"

            if event.type == pygame.FINGERDOWN:
                vx = int(event.x * VIRTUAL_W)
                vy = int(event.y * VIRTUAL_H)
                if btn_solo.collidepoint((vx, vy)):
                    chosen = "SOLO"
                elif btn_online.collidepoint((vx, vy)):
                    chosen = "ONLINE" if ALLOW_ONLINE else "SOLO"

        if chosen:
            mode = chosen
            break

        clock.tick(TARGET_FPS)

    # Stop menu music
    if audio_ok:
        try:
            pygame.mixer.music.stop()
        except Exception:
            pass

    # ---- Online connect (optional) ----
    client = None
    if mode == "ONLINE":
        try:
            client = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            client.settimeout(2.0)
            client.connect(("127.0.0.1", 5555))
            send_packet(client, {"hello": user_name, "w": VIRTUAL_W, "h": VIRTUAL_H})
            _ = recv_packet(client)
        except Exception:
            try:
                if client:
                    client.close()
            except Exception:
                pass
            client = None
            mode = "SOLO"

    # ---- Game init ----
    gs = GameState.fresh()
    particles = ParticlePool(max_particles=180 if IS_ANDROID else 240)

    ball_dx = 8.0 * (1 if random.random() < 0.5 else -1)
    ball_dy = random.choice([-6.0, -4.5, 4.5, 6.0])

    touch_y = VIRTUAL_H / 2
    my_y_target = gs.ly
    screen_shake = 0
    game_over = False

    P1_X = 40
    P2_X = VIRTUAL_W - 80

    def reset_round(scored_left: bool | None = None):
        nonlocal ball_dx, ball_dy, screen_shake, game_over
        gs.bx = VIRTUAL_W / 2 - BALL_SIZE / 2
        gs.by = VIRTUAL_H / 2 - BALL_SIZE / 2
        if scored_left is None:
            ball_dx = 8.0 * (1 if random.random() < 0.5 else -1)
        else:
            ball_dx = -8.0 if scored_left else 8.0
        ball_dy = random.choice([-6.0, -4.5, 4.5, 6.0])
        screen_shake = 0
        game_over = False
        particles.clear()
        gs.lh = 0
        gs.rh = 0

    running = True
    while running:
        dt = clock.tick(TARGET_FPS) / 1000.0
        dt = min(dt, 1 / 30)

        biome_idx = min(3, (max(gs.ls, gs.rs) // 4) + 1)
        screen_v.blit(BIOMES[biome_idx], (0, 0))

        # input
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            if event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                if game_over and event.key == pygame.K_r:
                    gs = GameState.fresh()
                    reset_round()

            if event.type in (pygame.FINGERDOWN, pygame.FINGERMOTION):
                touch_y = event.y * VIRTUAL_H

            if event.type == pygame.MOUSEMOTION:
                vx, vy = to_virtual_pos(*event.pos)
                touch_y = vy

            if (event.type == pygame.MOUSEBUTTONDOWN or event.type == pygame.FINGERDOWN) and game_over:
                gs = GameState.fresh()
                reset_round()

        my_y_target = clamp(touch_y - PADDLE_H / 2, 0, VIRTUAL_H - PADDLE_H)

        if mode == "SOLO" and not game_over:
            gs.ly += (my_y_target - gs.ly) * (0.35 if IS_ANDROID else 0.5)

            gs.bx += ball_dx * (dt * 60.0)
            gs.by += ball_dy * (dt * 60.0)

            if gs.by <= 0:
                gs.by = 0
                ball_dy = abs(ball_dy)
            elif gs.by >= VIRTUAL_H - BALL_SIZE:
                gs.by = VIRTUAL_H - BALL_SIZE
                ball_dy = -abs(ball_dy)

            bot_speed = 6.0 if IS_ANDROID else 6.5
            bot_center = gs.ry + PADDLE_H / 2
            ball_center = gs.by + BALL_SIZE / 2
            if bot_center < ball_center:
                gs.ry += bot_speed
            else:
                gs.ry -= bot_speed
            gs.ry = clamp(gs.ry, 0, VIRTUAL_H - PADDLE_H)

            ball_rect = pygame.Rect(int(gs.bx), int(gs.by), BALL_SIZE, BALL_SIZE)
            p1_rect = pygame.Rect(P1_X, int(gs.ly), PADDLE_W, PADDLE_H)
            p2_rect = pygame.Rect(P2_X, int(gs.ry), PADDLE_W, PADDLE_H)

            p1_diamond = gs.lh >= 5
            p2_diamond = gs.rh >= 5

            hit = None
            if ball_rect.colliderect(p1_rect) and ball_dx < 0:
                hit = "L"
            elif ball_rect.colliderect(p2_rect) and ball_dx > 0:
                hit = "R"

            if hit:
                screen_shake = 5 if IS_ANDROID else 7
                if sound_hit:
                    try:
                        sound_hit.play()
                    except Exception:
                        pass

                bcenter = gs.by + BALL_SIZE / 2

                if hit == "L":
                    gs.lh += 1
                    impact = (bcenter - (gs.ly + PADDLE_H / 2)) / (PADDLE_H / 2)
                    impact = clamp(impact, -1.0, 1.0)

                    gs.bx = P1_X + PADDLE_W + 1
                    ball_dx = abs(ball_dx) + 0.35
                    ball_dy = impact * BALL_SPEED_Y_MAX

                    col = (0, 238, 255) if p1_diamond else (134, 96, 67)
                    particles.spawn(gs.bx, gs.by, col, 7 if IS_ANDROID else 10)

                else:
                    gs.rh += 1
                    impact = (bcenter - (gs.ry + PADDLE_H / 2)) / (PADDLE_H / 2)
                    impact = clamp(impact, -1.0, 1.0)

                    gs.bx = P2_X - BALL_SIZE - 1
                    ball_dx = -(abs(ball_dx) + 0.35)
                    ball_dy = impact * BALL_SPEED_Y_MAX

                    col = (0, 238, 255) if p2_diamond else (134, 96, 67)
                    particles.spawn(gs.bx, gs.by, col, 7 if IS_ANDROID else 10)

                ball_dx = clamp(ball_dx, -BALL_SPEED_X_MAX, BALL_SPEED_X_MAX)
                ball_dy = clamp(ball_dy, -BALL_SPEED_Y_MAX, BALL_SPEED_Y_MAX)

            if gs.bx < -BALL_SIZE:
                gs.rs += 1
                reset_round(scored_left=False)
            elif gs.bx > VIRTUAL_W + BALL_SIZE:
                gs.ls += 1
                reset_round(scored_left=True)

            if gs.ls >= WIN_SCORE or gs.rs >= WIN_SCORE:
                game_over = True

        elif mode == "ONLINE" and not game_over:
            try:
                send_packet(client, {"y": float(my_y_target)})
                resp = recv_packet(client)
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
                mode = "SOLO"
                try:
                    if client:
                        client.close()
                except Exception:
                    pass
                client = None

        off_x = off_y = 0
        if screen_shake > 0:
            off_x = random.randint(-screen_shake, screen_shake)
            off_y = random.randint(-screen_shake, screen_shake)
            screen_shake -= 1

        p1_img = img_diamond if gs.lh >= 5 else img_wood
        p2_img = img_diamond if gs.rh >= 5 else img_wood

        screen_v.blit(p1_img, (P1_X + off_x, int(gs.ly) + off_y))
        screen_v.blit(p2_img, (P2_X + off_x, int(gs.ry) + off_y))
        screen_v.blit(img_ball, (int(gs.bx) + off_x, int(gs.by) + off_y))

        particles.update_draw(screen_v)

        score_img = fonts["big"].render(f"{gs.ls} - {gs.rs}", True, WHITE)
        screen_v.blit(score_img, (VIRTUAL_W // 2 - score_img.get_width() // 2, 18))

        hint = "Tap/Move finger | Tap on game over to restart" if IS_ANDROID else "Mouse | R restart | ESC exit"
        hint_img = fonts["tiny"].render(hint, True, (230, 230, 230))
        screen_v.blit(hint_img, (VIRTUAL_W // 2 - hint_img.get_width() // 2, VIRTUAL_H - 30))

        if game_over:
            overlay = pygame.Surface((VIRTUAL_W, VIRTUAL_H), pygame.SRCALPHA)
            overlay.fill((0, 0, 0, 140))
            screen_v.blit(overlay, (0, 0))
            msg = "YOU WIN!" if gs.ls >= WIN_SCORE else "YOU LOSE!"
            draw_text_center(screen_v, fonts["big"], msg, VIRTUAL_H // 2 - 40, (255, 215, 0))
            draw_text_center(screen_v, fonts["small"], "Tap/R to restart", VIRTUAL_H // 2 + 20, WHITE)

        present()

    try:
        if client:
            client.close()
    except Exception:
        pass
    pygame.quit()


def main():
    run_game()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        write_crash_log(e)
        try:
            pygame.quit()
        except Exception:
            pass
        raise