# object_explore.py
# -*- coding: utf-8 -*-
# Object Explore Task: touchscreen interaction preference measurement for macaques.
# Session types: ERC (equal-reward choice), PEC (probe-embedded choice),
#                FOV (free-operant validation), ABA_A/ABA_B (ABA design phases).
# Single self-contained file -- no imports from other project files.
import argparse, csv, sys, time, math, random, array
from abc import ABC, abstractmethod
from collections import deque
from datetime import datetime
from pathlib import Path

import pygame

try:
    import serial
except ImportError:
    serial = None


# =========================
# Arduino TTL sender
# =========================
class ArduinoTTLSender:
    def __init__(self, port: str, baud: int = 115200):
        if serial is None:
            raise RuntimeError("pyserial ga mi-install desu. `pip install pyserial`")
        try:
            self.ser = serial.Serial(port=port, baudrate=baud, timeout=0, write_timeout=0.2)
            time.sleep(0.05)
        except Exception as e:
            raise RuntimeError(f"Serial port open failed: {e}")

    def pulse(self):
        self.ser.write(b"PULSE\n")
        self.ser.flush()

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass


# =========================
# Beep sound
# =========================
def make_beep_sound(freq=1000, duration_ms=100, volume=0.6, sample_rate=44100):
    n = int(sample_rate * duration_ms / 1000)
    buf = array.array("h")
    amp = int(32767 * max(0.0, min(volume, 1.0)))
    for i in range(n):
        t = i / sample_rate
        buf.append(int(amp * math.sin(2 * math.pi * freq * t)))
    return pygame.mixer.Sound(buffer=buf.tobytes())


# =========================
# Tone with optional decay
# =========================
def make_tone(freq=1000, duration_ms=100, volume=0.6, sample_rate=44100, decay=False):
    n = int(sample_rate * duration_ms / 1000)
    buf = array.array("h")
    amp = int(32767 * max(0.0, min(volume, 1.0)))
    for i in range(n):
        t = i / sample_rate
        envelope = math.exp(-t * 10) if decay else 1.0
        val = int(amp * envelope * math.sin(2 * math.pi * freq * t))
        buf.append(max(-32767, min(32767, val)))
    return pygame.mixer.Sound(buffer=buf.tobytes())


# =========================
# Interaction base class
# =========================
class Interaction(ABC):
    REGISTRY = {}

    def __init_subclass__(cls, tag="", **kwargs):
        super().__init_subclass__(**kwargs)
        if tag:
            Interaction.REGISTRY[tag] = cls

    def __init__(self, zone_rect, screen_size):
        self.zone_rect = zone_rect
        self.sw, self.sh = screen_size
        self.active = False
        self.needs_redraw = False
        self._sounds = {}

    @abstractmethod
    def init_sounds(self):
        ...

    @abstractmethod
    def draw_preview(self, screen):
        ...

    @abstractmethod
    def draw_active(self, screen):
        ...

    @abstractmethod
    def on_touch(self, x, y, now):
        ...

    @abstractmethod
    def update(self, dt, now):
        ...

    def activate(self, x, y, now):
        self.active = True
        self.needs_redraw = True
        self.on_touch(x, y, now)

    def deactivate(self):
        self.active = False
        self.needs_redraw = False

    def reset(self):
        self.active = False
        self.needs_redraw = False

    def draw_dimmed(self, screen):
        temp = pygame.Surface(self.zone_rect.size, pygame.SRCALPHA)
        old_rect = self.zone_rect.copy()
        self.zone_rect = pygame.Rect(0, 0, old_rect.w, old_rect.h)
        self.draw_preview(temp)
        self.zone_rect = old_rect
        temp.set_alpha(76)
        screen.blit(temp, self.zone_rect.topleft)


# =========================
# PeekabooReveal
# =========================
class PeekabooReveal(Interaction, tag="peekaboo"):
    DOOR_OPEN_DURATION = 0.3
    REVEAL_DURATION = 2.0
    DOOR_CLOSE_DURATION = 0.3
    CLOSED, OPENING, OPEN, CLOSING = 0, 1, 2, 3

    REVEAL_COLORS = [
        (255, 100, 100), (100, 255, 100), (100, 100, 255),
        (255, 200, 50), (200, 100, 255),
    ]

    def __init__(self, zone_rect, screen_size):
        super().__init__(zone_rect, screen_size)
        self.door_state = self.CLOSED
        self.anim_t0 = 0.0
        self.open_t0 = 0.0
        self.door_offset_x = 0
        self.door_color = (180, 130, 60)
        self.reveal_idx = 0
        self._reveal_surfs = []

    def init_sounds(self):
        self._sounds["swoosh"] = make_tone(1500, 100, volume=0.3, decay=True)
        self._sounds["reveal"] = make_tone(880, 200, volume=0.4, decay=True)

    def _build_reveal_surfaces(self):
        self._reveal_surfs = []
        w, h = self.zone_rect.w, self.zone_rect.h
        for color in self.REVEAL_COLORS:
            surf = pygame.Surface((w, h), pygame.SRCALPHA)
            surf.fill((240, 240, 240))
            cx, cy = w // 2, h // 2
            pygame.draw.circle(surf, color, (cx, cy), min(w, h) // 3)
            self._reveal_surfs.append(surf)

    def on_touch(self, x, y, now):
        if self.door_state == self.CLOSED:
            self.door_state = self.OPENING
            self.anim_t0 = now
            self.reveal_idx = random.randint(0, len(self.REVEAL_COLORS) - 1)
            try:
                self._sounds["swoosh"].play()
            except Exception:
                pass
            self.needs_redraw = True

    def update(self, dt, now):
        if not self.active:
            self.needs_redraw = False
            return
        if self.door_state == self.OPENING:
            progress = (now - self.anim_t0) / self.DOOR_OPEN_DURATION
            self.door_offset_x = int(self.zone_rect.w * min(1.0, progress))
            if progress >= 1.0:
                self.door_state = self.OPEN
                self.open_t0 = now
                try:
                    self._sounds["reveal"].play()
                except Exception:
                    pass
            self.needs_redraw = True
        elif self.door_state == self.OPEN:
            if now - self.open_t0 >= self.REVEAL_DURATION:
                self.door_state = self.CLOSING
                self.anim_t0 = now
            self.needs_redraw = True
        elif self.door_state == self.CLOSING:
            progress = (now - self.anim_t0) / self.DOOR_CLOSE_DURATION
            self.door_offset_x = int(self.zone_rect.w * max(0.0, 1.0 - progress))
            if progress >= 1.0:
                self.door_state = self.CLOSED
                self.door_offset_x = 0
            self.needs_redraw = True
        else:
            self.needs_redraw = False

    def draw_preview(self, screen):
        pygame.draw.rect(screen, self.door_color, self.zone_rect)
        hx = self.zone_rect.right - 20
        hy = self.zone_rect.centery
        pygame.draw.circle(screen, (140, 100, 40), (hx, hy), 8)
        # Question mark circle
        cx, cy = self.zone_rect.center
        pygame.draw.circle(screen, (220, 200, 140), (cx, cy), 30, 3)

    def draw_active(self, screen):
        zr = self.zone_rect
        if self._reveal_surfs:
            screen.blit(self._reveal_surfs[self.reveal_idx], zr.topleft)
        else:
            pygame.draw.rect(screen, (240, 240, 240), zr)
            cx, cy = zr.center
            color = self.REVEAL_COLORS[self.reveal_idx]
            pygame.draw.circle(screen, color, (cx, cy), min(zr.w, zr.h) // 3)
        door_rect = pygame.Rect(
            zr.left + self.door_offset_x, zr.top,
            zr.w - self.door_offset_x, zr.h
        )
        if door_rect.w > 0:
            pygame.draw.rect(screen, self.door_color, door_rect)
            if door_rect.w > 20:
                hx = door_rect.right - 20
                hy = door_rect.centery
                pygame.draw.circle(screen, (140, 100, 40), (hx, hy), 8)

    def reset(self):
        super().reset()
        self.door_state = self.CLOSED
        self.door_offset_x = 0


# =========================
# SquashBlob
# =========================
class SquashBlob(Interaction, tag="squash_blob"):
    SPRING_FREQ = 5.0
    SPRING_DECAY = 6.0
    SQUASH_AMOUNT = 0.3
    PARTICLE_COUNT = 8
    BLOB_RADIUS = 60

    def __init__(self, zone_rect, screen_size):
        super().__init__(zone_rect, screen_size)
        self.sx = 1.0
        self.sy = 1.0
        self.spring_t = None
        self.particles = []
        self.blob_color = (100, 200, 120)
        self.base_color = (100, 200, 120)

    def init_sounds(self):
        self._sounds["boing"] = make_tone(600, 300, volume=0.5, decay=True)
        self._sounds["pff"] = make_tone(2000, 50, volume=0.15, decay=True)

    def on_touch(self, x, y, now):
        self.spring_t = 0.0
        self.particles = []
        cx, cy = self.zone_rect.center
        for i in range(self.PARTICLE_COUNT):
            angle = 2 * math.pi * i / self.PARTICLE_COUNT
            self.particles.append({
                "x": float(cx), "y": float(cy),
                "vx": math.cos(angle) * 4.0,
                "vy": math.sin(angle) * 4.0,
                "alpha": 200,
                "t0": now,
            })
        self.blob_color = tuple(min(255, c + 50) for c in self.base_color)
        try:
            self._sounds["boing"].play()
            self._sounds["pff"].play()
        except Exception:
            pass
        self.needs_redraw = True

    def update(self, dt, now):
        if not self.active:
            self.needs_redraw = False
            return
        anim_running = False
        if self.spring_t is not None:
            self.spring_t += dt
            t = self.spring_t
            decay = math.exp(-self.SPRING_DECAY * t)
            osc = math.cos(2 * math.pi * self.SPRING_FREQ * t)
            self.sy = 1.0 + self.SQUASH_AMOUNT * decay * osc
            self.sx = 1.0 - (self.SQUASH_AMOUNT * 0.5) * decay * osc
            if decay < 0.01:
                self.spring_t = None
                self.sx = 1.0
                self.sy = 1.0
                self.blob_color = self.base_color
            anim_running = True
        alive = []
        for p in self.particles:
            p["x"] += p["vx"]
            p["y"] += p["vy"]
            p["alpha"] -= 8
            if p["alpha"] > 0:
                alive.append(p)
                anim_running = True
        self.particles = alive
        self.needs_redraw = anim_running

    def draw_preview(self, screen):
        cx, cy = self.zone_rect.center
        pygame.draw.ellipse(screen, self.base_color,
            (cx - self.BLOB_RADIUS, cy - self.BLOB_RADIUS,
             self.BLOB_RADIUS * 2, self.BLOB_RADIUS * 2))

    def draw_active(self, screen):
        cx, cy = self.zone_rect.center
        w = int(self.BLOB_RADIUS * 2 * self.sx)
        h = int(self.BLOB_RADIUS * 2 * self.sy)
        pygame.draw.ellipse(screen, self.blob_color,
            (cx - w // 2, cy - h // 2, w, h))
        for p in self.particles:
            pygame.draw.circle(screen, self.base_color,
                (int(p["x"]), int(p["y"])), 5)

    def reset(self):
        super().reset()
        self.sx = 1.0
        self.sy = 1.0
        self.spring_t = None
        self.particles = []
        self.blob_color = self.base_color


# =========================
# SoundBallSpawn
# =========================
class SoundBallSpawn(Interaction, tag="sound_ball"):
    MAX_BALLS = 15
    BALL_LIFETIME_S = 10.0
    PENTATONIC = [262, 294, 330, 392, 440]
    COLORS = [(255, 80, 80), (80, 255, 80), (80, 80, 255),
              (255, 255, 80), (255, 80, 255), (80, 255, 255)]

    def __init__(self, zone_rect, screen_size):
        super().__init__(zone_rect, screen_size)
        self.balls = []

    def init_sounds(self):
        for i, freq in enumerate(self.PENTATONIC):
            self._sounds[f"note_{i}"] = make_tone(freq, 150, volume=0.5, decay=True)
            self._sounds[f"note_hi_{i}"] = make_tone(freq * 2, 80, volume=0.3, decay=True)

    def on_touch(self, x, y, now):
        if len(self.balls) >= self.MAX_BALLS:
            self.balls.pop(0)
        angle = random.uniform(0, 2 * math.pi)
        speed = random.uniform(2, 5)
        note_idx = random.randint(0, 4)
        self.balls.append({
            "x": float(x), "y": float(y),
            "vx": math.cos(angle) * speed,
            "vy": math.sin(angle) * speed,
            "r": random.randint(20, 35),
            "color": random.choice(self.COLORS),
            "note_idx": note_idx,
            "t0": now,
        })
        try:
            self._sounds[f"note_{note_idx}"].play()
        except Exception:
            pass
        self.needs_redraw = True

    def update(self, dt, now):
        if not self.active:
            self.needs_redraw = False
            return
        alive = []
        zr = self.zone_rect
        for b in self.balls:
            age = now - b["t0"]
            if age > self.BALL_LIFETIME_S:
                continue
            b["x"] += b["vx"]
            b["y"] += b["vy"]
            if b["x"] - b["r"] < zr.left:
                b["x"] = zr.left + b["r"]; b["vx"] = abs(b["vx"])
            if b["x"] + b["r"] > zr.right:
                b["x"] = zr.right - b["r"]; b["vx"] = -abs(b["vx"])
            if b["y"] - b["r"] < zr.top:
                b["y"] = zr.top + b["r"]; b["vy"] = abs(b["vy"])
            if b["y"] + b["r"] > zr.bottom:
                b["y"] = zr.bottom - b["r"]; b["vy"] = -abs(b["vy"])
            alive.append(b)
        # Simple pairwise collision
        for i in range(len(alive)):
            for j in range(i + 1, len(alive)):
                a, bb = alive[i], alive[j]
                dx = a["x"] - bb["x"]
                dy = a["y"] - bb["y"]
                dist = math.hypot(dx, dy)
                if dist < a["r"] + bb["r"] and dist > 0:
                    a["vx"], bb["vx"] = bb["vx"], a["vx"]
                    a["vy"], bb["vy"] = bb["vy"], a["vy"]
                    try:
                        idx = min(a["note_idx"], bb["note_idx"])
                        self._sounds[f"note_hi_{idx}"].play()
                    except Exception:
                        pass
        self.balls = alive
        self.needs_redraw = bool(self.balls)

    def draw_preview(self, screen):
        pygame.draw.rect(screen, (40, 40, 40), self.zone_rect)
        cx, cy = self.zone_rect.center
        for i, (dx, dy) in enumerate([(-40, -20), (30, 10), (-10, 30)]):
            pygame.draw.circle(screen, self.COLORS[i], (cx + dx, cy + dy), 20)

    def draw_active(self, screen):
        pygame.draw.rect(screen, (40, 40, 40), self.zone_rect)
        for b in self.balls:
            pygame.draw.circle(screen, b["color"], (int(b["x"]), int(b["y"])), b["r"])

    def reset(self):
        super().reset()
        self.balls = []


# =========================
# BubblePond
# =========================
class BubblePond(Interaction, tag="bubble_pond"):
    MAX_BUBBLES = 20
    MAX_FISH = 4
    FISH_ACCEL = 0.3
    FISH_DRAG = 0.98
    BUBBLE_EXPAND_RATE = 1.5
    BUBBLE_FADE_RATE = 4

    def __init__(self, zone_rect, screen_size):
        super().__init__(zone_rect, screen_size)
        self.bubbles = []
        self.fish = []
        self.last_touch = None
        self.bg_color = (10, 30, 80)
        self._init_fish()

    def _init_fish(self):
        colors = [(255, 140, 40), (40, 220, 180), (220, 60, 160), (120, 200, 255)]
        cx, cy = self.zone_rect.center
        self.fish = []
        for c in colors[:self.MAX_FISH]:
            self.fish.append({
                "x": cx + random.randint(-80, 80),
                "y": cy + random.randint(-60, 60),
                "vx": random.uniform(-0.5, 0.5),
                "vy": random.uniform(-0.5, 0.5),
                "color": c,
                "trail": deque(maxlen=5),
            })

    def init_sounds(self):
        self._sounds["plop"] = make_tone(800, 200, volume=0.4, decay=True)
        self._sounds["blip"] = make_tone(1200, 100, volume=0.3, decay=True)

    def on_touch(self, x, y, now):
        self.last_touch = (x, y)
        for _ in range(random.randint(3, 5)):
            if len(self.bubbles) >= self.MAX_BUBBLES:
                self.bubbles.pop(0)
            self.bubbles.append({
                "x": x + random.randint(-10, 10),
                "y": y + random.randint(-10, 10),
                "r": random.uniform(8, 15),
                "alpha": 200,
                "t0": now,
            })
        try:
            self._sounds["plop"].play()
        except Exception:
            pass
        self.needs_redraw = True

    def update(self, dt, now):
        if not self.active:
            self.needs_redraw = False
            return
        alive_bubbles = []
        for b in self.bubbles:
            b["r"] += self.BUBBLE_EXPAND_RATE
            b["alpha"] -= self.BUBBLE_FADE_RATE
            if b["alpha"] > 0 and b["r"] < 60:
                alive_bubbles.append(b)
        self.bubbles = alive_bubbles

        for f in self.fish:
            f["trail"].append((f["x"], f["y"]))
            if self.last_touch:
                dx = self.last_touch[0] - f["x"]
                dy = self.last_touch[1] - f["y"]
                dist = max(1.0, math.hypot(dx, dy))
                f["vx"] += dx / dist * self.FISH_ACCEL
                f["vy"] += dy / dist * self.FISH_ACCEL
            f["vx"] *= self.FISH_DRAG
            f["vy"] *= self.FISH_DRAG
            f["x"] += f["vx"]
            f["y"] += f["vy"]
            f["x"] = max(self.zone_rect.left + 15, min(self.zone_rect.right - 15, f["x"]))
            f["y"] = max(self.zone_rect.top + 8, min(self.zone_rect.bottom - 8, f["y"]))
            if self.last_touch:
                if math.hypot(f["x"] - self.last_touch[0], f["y"] - self.last_touch[1]) < 50:
                    try:
                        self._sounds["blip"].play()
                    except Exception:
                        pass

        self.needs_redraw = bool(self.bubbles) or bool(self.fish)

    def draw_preview(self, screen):
        pygame.draw.rect(screen, self.bg_color, self.zone_rect)
        for f in self.fish:
            pygame.draw.ellipse(screen, f["color"],
                (int(f["x"]) - 15, int(f["y"]) - 8, 30, 16))

    def draw_active(self, screen):
        pygame.draw.rect(screen, self.bg_color, self.zone_rect)
        for b in self.bubbles:
            alpha = max(0, min(255, int(b["alpha"])))
            r_int = max(1, int(b["r"]))
            # Draw unfilled circle instead of SRCALPHA surface (RPi5 performance)
            pygame.draw.circle(screen, (180, 220, 255), (int(b["x"]), int(b["y"])), r_int, 2)
        for f in self.fish:
            for i, (tx, ty) in enumerate(f["trail"]):
                r = max(1, 3 - i)
                pygame.draw.circle(screen, f["color"], (int(tx), int(ty)), r)
            pygame.draw.ellipse(screen, f["color"],
                (int(f["x"]) - 15, int(f["y"]) - 8, 30, 16))

    def reset(self):
        super().reset()
        self.bubbles.clear()
        self.last_touch = None
        self._init_fish()


# =========================
# ParticleAttractor
# =========================
class ParticleAttractor(Interaction, tag="particle_attractor"):
    N_PARTICLES = 80
    GRAVITY_STRENGTH = 0.5
    DRAG = 0.97
    SCATTER_SPEED = 5.0

    def __init__(self, zone_rect, screen_size):
        super().__init__(zone_rect, screen_size)
        self.px = []
        self.py = []
        self.vx = []
        self.vy = []
        self.base_colors = []
        self.touch_active = False
        self.touch_x = 0
        self.touch_y = 0
        self._init_particles()

    def _init_particles(self):
        zr = self.zone_rect
        self.px = [random.uniform(zr.left, zr.right) for _ in range(self.N_PARTICLES)]
        self.py = [random.uniform(zr.top, zr.bottom) for _ in range(self.N_PARTICLES)]
        self.vx = [random.uniform(-0.5, 0.5) for _ in range(self.N_PARTICLES)]
        self.vy = [random.uniform(-0.5, 0.5) for _ in range(self.N_PARTICLES)]
        self.base_colors = []
        for _ in range(self.N_PARTICLES):
            self.base_colors.append((
                random.randint(100, 255),
                random.randint(60, 200),
                random.randint(150, 255),
            ))

    def init_sounds(self):
        self._sounds["converge"] = make_tone(600, 300, volume=0.3, decay=False)
        self._sounds["scatter"] = make_tone(1500, 200, volume=0.25, decay=True)

    def on_touch(self, x, y, now):
        self.touch_active = True
        self.touch_x = x
        self.touch_y = y
        self.needs_redraw = True
        try:
            self._sounds["converge"].play()
        except Exception:
            pass

    def on_release(self):
        if self.touch_active:
            self.touch_active = False
            # Scatter particles outward
            for i in range(self.N_PARTICLES):
                angle = random.uniform(0, 2 * math.pi)
                self.vx[i] = math.cos(angle) * self.SCATTER_SPEED
                self.vy[i] = math.sin(angle) * self.SCATTER_SPEED
            try:
                self._sounds["scatter"].play()
            except Exception:
                pass
            self.needs_redraw = True

    def update(self, dt, now):
        if not self.active:
            self.needs_redraw = False
            return
        zr = self.zone_rect
        for i in range(self.N_PARTICLES):
            if self.touch_active:
                dx = self.touch_x - self.px[i]
                dy = self.touch_y - self.py[i]
                dist = max(1.0, math.hypot(dx, dy))
                self.vx[i] += dx / dist * self.GRAVITY_STRENGTH
                self.vy[i] += dy / dist * self.GRAVITY_STRENGTH
                if dist < 10:
                    angle = random.uniform(0, 2 * math.pi)
                    self.vx[i] = math.cos(angle) * self.SCATTER_SPEED
                    self.vy[i] = math.sin(angle) * self.SCATTER_SPEED
            else:
                self.vx[i] += random.uniform(-0.05, 0.05)
                self.vy[i] += random.uniform(-0.05, 0.05)

            self.vx[i] *= self.DRAG
            self.vy[i] *= self.DRAG
            self.px[i] += self.vx[i]
            self.py[i] += self.vy[i]
            if self.px[i] < zr.left: self.px[i] = zr.left; self.vx[i] = abs(self.vx[i])
            if self.px[i] > zr.right: self.px[i] = zr.right; self.vx[i] = -abs(self.vx[i])
            if self.py[i] < zr.top: self.py[i] = zr.top; self.vy[i] = abs(self.vy[i])
            if self.py[i] > zr.bottom: self.py[i] = zr.bottom; self.vy[i] = -abs(self.vy[i])

        self.needs_redraw = True  # Continuous animation

    def draw_preview(self, screen):
        pygame.draw.rect(screen, (5, 5, 15), self.zone_rect)
        for i in range(self.N_PARTICLES):
            pygame.draw.circle(screen, self.base_colors[i],
                (int(self.px[i]), int(self.py[i])), 3)

    def draw_active(self, screen):
        pygame.draw.rect(screen, (5, 5, 15), self.zone_rect)
        for i in range(self.N_PARTICLES):
            if self.touch_active:
                dist = math.hypot(self.px[i] - self.touch_x, self.py[i] - self.touch_y)
                warmth = max(0.0, min(1.0, 1.0 - dist / 300.0))
                r = int(self.base_colors[i][0] * (1 - warmth) + 255 * warmth)
                g = int(self.base_colors[i][1] * (1 - warmth) + 100 * warmth)
                b = int(self.base_colors[i][2] * (1 - warmth * 0.5))
                color = (min(255, r), min(255, g), min(255, b))
            else:
                color = self.base_colors[i]
            pygame.draw.circle(screen, color, (int(self.px[i]), int(self.py[i])), 3)

    def reset(self):
        super().reset()
        self.touch_active = False
        self._init_particles()


# =========================
# TrialSequencer
# =========================
INTERACTION_TAGS = ["bubble_pond", "sound_ball", "squash_blob", "peekaboo", "particle_attractor"]


class TrialSequencer:
    BLOCK_A = [0, 1, 4, 7, 9]
    BLOCK_B = [2, 3, 5, 6, 8]

    def __init__(self, session_type, target_trials, block_id, probe_rate=0.15):
        tags = INTERACTION_TAGS
        self.ALL_PAIRS = []
        for i in range(len(tags)):
            for j in range(i + 1, len(tags)):
                self.ALL_PAIRS.append((tags[i], tags[j]))
        block = self.BLOCK_A if block_id == "A" else self.BLOCK_B
        self.session_pairs = [self.ALL_PAIRS[i] for i in block]
        self.trials = self._generate_trials(target_trials, session_type, probe_rate)
        self.current_idx = 0

    def _generate_trials(self, n, session_type, probe_rate):
        reps_per_pair = n // 5
        remainder = n - reps_per_pair * 5
        trials = []
        for pair_idx, (a, b) in enumerate(self.session_pairs):
            reps = reps_per_pair + (1 if pair_idx < remainder else 0)
            half = reps // 2
            for r in range(reps):
                left_is_first = r < half
                trials.append({
                    "pair": f"{a}:{b}",
                    "left": a if left_is_first else b,
                    "right": b if left_is_first else a,
                    "is_probe": False,
                    "pair_idx": pair_idx,
                })
        random.shuffle(trials)

        # Fix: no more than 2 consecutive same pair
        for attempt in range(100):
            ok = True
            for i in range(2, len(trials)):
                if (trials[i]["pair"] == trials[i-1]["pair"] == trials[i-2]["pair"]):
                    j = random.randint(i+1, len(trials)-1) if i+1 < len(trials) else i
                    trials[i], trials[j] = trials[j], trials[i]
                    ok = False
            if ok:
                break

        if session_type == "PEC" and probe_rate > 0:
            n_probes = max(1, int(len(trials) * probe_rate))
            eligible = list(range(3, len(trials) - 2)) if len(trials) > 5 else list(range(len(trials)))
            probe_indices = set()
            random.shuffle(eligible)
            for idx in eligible:
                if len(probe_indices) >= n_probes:
                    break
                if (idx - 1) not in probe_indices and (idx + 1) not in probe_indices:
                    probe_indices.add(idx)
            for idx in probe_indices:
                trials[idx]["is_probe"] = True

        return trials

    def next_trial(self):
        if self.current_idx >= len(self.trials):
            return None
        trial = self.trials[self.current_idx]
        self.current_idx += 1
        return trial

    @property
    def trials_completed(self):
        return self.current_idx

    @property
    def trials_remaining(self):
        return len(self.trials) - self.current_idx


# =========================
# Interaction factory
# =========================
def create_interaction(tag, zone_rect, screen_size):
    cls = Interaction.REGISTRY.get(tag)
    if cls is None:
        raise ValueError(f"Unknown interaction tag: {tag}")
    inst = cls(zone_rect, screen_size)
    inst.init_sounds()
    if hasattr(inst, "_build_reveal_surfaces"):
        inst._build_reveal_surfaces()
    return inst


# =========================
# Main
# =========================
def run(args):
    pygame.init()
    try:
        pygame.mixer.init(frequency=44100, size=-16, channels=1)
    except Exception as e:
        print(f"[WARN] mixer init failed: {e}", file=sys.stderr)

    try:
        pygame.display.set_allow_screensaver(False)
    except Exception:
        pass

    # ---- Pygame event types (environment-dependent) ----
    FINGERDOWN   = getattr(pygame, "FINGERDOWN", None)
    FINGERUP     = getattr(pygame, "FINGERUP", None)
    FINGERMOTION = getattr(pygame, "FINGERMOTION", None)
    MOUSEWHEEL   = getattr(pygame, "MOUSEWHEEL", None)

    # ---- Block unused events ----
    to_block = [pygame.MOUSEMOTION]
    if FINGERMOTION is not None: to_block.append(FINGERMOTION)
    if MOUSEWHEEL   is not None: to_block.append(MOUSEWHEEL)
    pygame.event.set_blocked(to_block)

    # Kiosk / input policy
    if args.kiosk:
        args.fullscreen = True
        pygame.mouse.set_visible(False)
        pygame.event.set_grab(True)
    if args.touch_only:
        pygame.event.set_blocked(pygame.MOUSEBUTTONDOWN)
        pygame.event.set_blocked(pygame.MOUSEBUTTONUP)
        pygame.event.set_blocked(pygame.MOUSEMOTION)

    ttl = None
    csv_f = None
    try:
        flags = pygame.FULLSCREEN if args.fullscreen else pygame.NOFRAME
        screen = pygame.display.set_mode(
            (0, 0) if args.fullscreen else (args.window_w, args.window_h), flags
        )
        pygame.display.set_caption("Object Explore Task")
        clock = pygame.time.Clock()
        font = pygame.font.SysFont(None, 24)
        sw, sh = screen.get_size()

        # ---- TTL ----
        try:
            ttl = ArduinoTTLSender(args.serial_port, args.serial_baud)
        except Exception as e:
            print(f"[WARN] TTL disabled (serial port unavailable): {e}", file=sys.stderr)
            ttl = None

        # ---- Beep ----
        try:
            beep = make_beep_sound(args.beep_freq, args.beep_ms, args.beep_volume)
        except Exception as e:
            beep = None
            print(f"[WARN] beep disabled: {e}", file=sys.stderr)

        # ---- Route by session type ----
        effective_type = args.session_type
        if effective_type == "ABA_A":
            effective_type = "FOV"
        elif effective_type == "ABA_B":
            effective_type = "ERC"

        if effective_type == "FOV":
            _run_fov(args, screen, sw, sh, clock, font, ttl, beep,
                     FINGERDOWN, FINGERUP, FINGERMOTION, MOUSEWHEEL)
        else:
            _run_trial_based(args, effective_type, screen, sw, sh, clock, font,
                             ttl, beep, FINGERDOWN, FINGERUP, FINGERMOTION, MOUSEWHEEL)

    finally:
        try:
            pygame.quit()
        except Exception:
            pass
        if ttl is not None:
            ttl.close()


# =========================
# FOV session (free-operant)
# =========================
def _run_fov(args, screen, sw, sh, clock, font, ttl, beep,
             FINGERDOWN, FINGERUP, FINGERMOTION, MOUSEWHEEL):
    csv_f = None
    try:
        # ---- Pentagon layout ----
        fov_zone_size = max(50, int(args.fov_zone_size_px))
        radius = min(sw, sh) * 0.35
        rotation = int(args.fov_rotation) % 5
        screen_size = (sw, sh)
        interactions = {}
        zone_rects = {}
        for i, tag in enumerate(INTERACTION_TAGS):
            angle = math.radians(90 + rotation * 72 + i * 72)
            cx = sw // 2 + int(radius * math.cos(angle))
            cy = sh // 2 - int(radius * math.sin(angle))
            zr = pygame.Rect(cx - fov_zone_size // 2, cy - fov_zone_size // 2,
                             fov_zone_size, fov_zone_size)
            zone_rects[tag] = zr
            interactions[tag] = create_interaction(tag, zr, screen_size)

        # ---- CSV ----
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        start_dt = datetime.now()
        start_iso = start_dt.isoformat(timespec="milliseconds")
        prefix = "aba_a" if args.session_type == "ABA_A" else "fov"
        out_path = out_dir / f"{prefix}_log_{args.subject_id}_{start_dt.strftime('%Y%m%d_%H%M%S')}.csv"

        fieldnames = [
            "start_iso", "iso", "rel_s", "state", "x", "y", "event",
            "session_type", "subject_id",
            "interaction_hit", "touch_id",
            "fov_elapsed_s",
            "fov_cumul_bubble_pond", "fov_cumul_sound_ball",
            "fov_cumul_squash_blob", "fov_cumul_peekaboo",
            "fov_cumul_particle_attractor",
            "total_touches", "session_duration_s",
        ]
        csv_f = out_path.open("w", newline="", encoding="utf-8")
        csv_w = csv.DictWriter(csv_f, fieldnames=fieldnames)
        csv_w.writeheader()
        write_count = 0

        t0 = time.perf_counter()
        touch_id = 0
        cumul = {tag: 0 for tag in INTERACTION_TAGS}
        last_touch_any_t = t0

        mouse_down = False
        active_fingers = set()

        def append_log(event_name, x, y, hit_tag=""):
            nonlocal write_count
            nowp = time.perf_counter()
            rel = nowp - t0
            iso = datetime.now().isoformat(timespec="milliseconds")
            row = {
                "start_iso": start_iso,
                "iso": iso,
                "rel_s": f"{rel:.6f}",
                "state": "FREE_EXPLORE",
                "x": x, "y": y,
                "event": event_name,
                "session_type": args.session_type,
                "subject_id": args.subject_id,
                "interaction_hit": hit_tag,
                "touch_id": touch_id,
                "fov_elapsed_s": f"{rel:.6f}",
                "fov_cumul_bubble_pond": cumul["bubble_pond"],
                "fov_cumul_sound_ball": cumul["sound_ball"],
                "fov_cumul_squash_blob": cumul["squash_blob"],
                "fov_cumul_peekaboo": cumul["peekaboo"],
                "fov_cumul_particle_attractor": cumul["particle_attractor"],
                "total_touches": touch_id,
                "session_duration_s": "",
            }
            csv_w.writerow(row)
            write_count += 1
            if write_count % 64 == 0:
                csv_f.flush()

        append_log("SESSION_START", -1, -1)

        # ---- Initial draw ----
        screen.fill(args.bg_rgb)
        for tag in INTERACTION_TAGS:
            interactions[tag].draw_preview(screen)
        if args.show_box:
            for tag in INTERACTION_TAGS:
                pygame.draw.rect(screen, (120, 120, 120), zone_rects[tag], 2)
        pygame.display.flip()

        fov_max = max(60, int(args.fov_max_duration_s))
        fov_inactivity = max(30, int(args.fov_inactivity_timeout_s))
        running = True
        stop_file = Path("STOP")

        while running:
            if stop_file.exists():
                print("[INFO] STOP file detected. Exiting...")
                running = False
                break

            for ev in pygame.event.get([pygame.QUIT, pygame.KEYDOWN, pygame.KEYUP]):
                if ev.type == pygame.QUIT:
                    running = False; break
                if ev.type in (pygame.KEYDOWN, pygame.KEYUP):
                    if ev.key in (pygame.K_ESCAPE, pygame.K_q):
                        running = False; break
            if not running: break

            pygame.event.pump()
            keys = pygame.key.get_pressed()
            if keys[pygame.K_ESCAPE] or keys[pygame.K_q]:
                running = False; break

            now = time.perf_counter()

            # Time limits
            if now - t0 >= fov_max:
                append_log("SESSION_TIMEOUT", -1, -1)
                running = False; break
            if now - last_touch_any_t >= fov_inactivity:
                append_log("FOV_INACTIVITY_END", -1, -1)
                running = False; break

            # ---- Touch events ----
            want = [pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP]
            if FINGERDOWN is not None: want.append(FINGERDOWN)
            if FINGERUP   is not None: want.append(FINGERUP)

            for ev in pygame.event.get(want):
                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    mouse_down = True
                elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                    mouse_down = False
                    # Handle particle attractor release
                    for tag in INTERACTION_TAGS:
                        inter = interactions[tag]
                        if inter.active and isinstance(inter, ParticleAttractor):
                            inter.on_release()
                elif FINGERDOWN is not None and ev.type == FINGERDOWN:
                    active_fingers.add(ev.finger_id)
                elif FINGERUP is not None and ev.type == FINGERUP:
                    active_fingers.discard(ev.finger_id)
                    for tag in INTERACTION_TAGS:
                        inter = interactions[tag]
                        if inter.active and isinstance(inter, ParticleAttractor):
                            inter.on_release()

                # Handle touch down
                xy = None
                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    xy = ev.pos
                elif FINGERDOWN is not None and ev.type == FINGERDOWN:
                    xy = (int(ev.x * sw), int(ev.y * sh))

                if xy is not None:
                    x, y = xy
                    last_touch_any_t = now
                    hit_tag = ""
                    hit_margin = max(0, int(args.hit_margin_px))
                    for tag in INTERACTION_TAGS:
                        zr = zone_rects[tag]
                        hit_rect = zr.inflate(2 * hit_margin, 2 * hit_margin)
                        if hit_rect.collidepoint(x, y):
                            hit_tag = tag
                            break
                    touch_id += 1
                    if hit_tag:
                        cumul[hit_tag] += 1
                        inter = interactions[hit_tag]
                        if not inter.active:
                            inter.activate(x, y, now)
                        else:
                            inter.on_touch(x, y, now)
                        append_log("TOUCH_FOV", x, y, hit_tag)
                    else:
                        append_log("TOUCH_FOV_OUTSIDE", x, y, "outside")

            if not running: break

            # ---- Update all interactions ----
            dt = clock.get_time() / 1000.0
            any_redraw = False
            for tag in INTERACTION_TAGS:
                inter = interactions[tag]
                if inter.active:
                    inter.update(dt, now)
                    if inter.needs_redraw:
                        any_redraw = True

            # ---- Redraw if needed ----
            if any_redraw:
                screen.fill(args.bg_rgb)
                for tag in INTERACTION_TAGS:
                    inter = interactions[tag]
                    if inter.active:
                        inter.draw_active(screen)
                    else:
                        inter.draw_preview(screen)
                if args.show_box:
                    for tag in INTERACTION_TAGS:
                        pygame.draw.rect(screen, (120, 120, 120), zone_rects[tag], 2)
                if args.info:
                    elapsed = now - t0
                    fps = clock.get_fps()
                    txt = (f"FOV  elapsed={elapsed:.0f}s/{fov_max}s  "
                           f"inact={now - last_touch_any_t:.0f}s/{fov_inactivity}s  "
                           f"touches={touch_id}  FPS={fps:.0f}")
                    screen.blit(font.render(txt, True, (220, 220, 220)), (10, 10))
                pygame.display.flip()

            clock.tick(60)

        # Session end
        end_time = time.perf_counter()
        touch_id_save = touch_id
        # Write summary row
        nowp = time.perf_counter()
        rel = nowp - t0
        iso = datetime.now().isoformat(timespec="milliseconds")
        row = {
            "start_iso": start_iso,
            "iso": iso,
            "rel_s": f"{rel:.6f}",
            "state": "FREE_EXPLORE",
            "x": -1, "y": -1,
            "event": "SESSION_END",
            "session_type": args.session_type,
            "subject_id": args.subject_id,
            "interaction_hit": "",
            "touch_id": touch_id,
            "fov_elapsed_s": f"{rel:.6f}",
            "fov_cumul_bubble_pond": cumul["bubble_pond"],
            "fov_cumul_sound_ball": cumul["sound_ball"],
            "fov_cumul_squash_blob": cumul["squash_blob"],
            "fov_cumul_peekaboo": cumul["peekaboo"],
            "fov_cumul_particle_attractor": cumul["particle_attractor"],
            "total_touches": touch_id,
            "session_duration_s": f"{rel:.6f}",
        }
        csv_w.writerow(row)
        csv_f.flush()
        print(f"[INFO] FOV session done. Saved CSV: {out_path}")

    finally:
        if csv_f is not None:
            try:
                csv_f.flush()
                csv_f.close()
            except Exception:
                pass



# =========================
# Trial-based session (ERC / PEC)
# =========================
def _run_trial_based(args, effective_type, screen, sw, sh, clock, font,
                     ttl, beep, FINGERDOWN, FINGERUP, FINGERMOTION, MOUSEWHEEL):
    """Trial-based session (ERC / PEC) -- full implementation."""
    csv_f = None
    try:
        screen_size = (sw, sh)

        # ---- Zone layout ----
        zone_size = max(50, int(args.zone_size_px))
        edge_margin = max(0, int(args.edge_margin_px))
        max_offset = max(0, (sw // 2) - (zone_size // 2) - edge_margin)
        center_offset = min(max_offset, max(0, int(args.center_offset_px)))
        cy = sh // 2

        left_cx = (sw // 2) - center_offset
        right_cx = (sw // 2) + center_offset
        left_zone = pygame.Rect(left_cx - zone_size // 2, cy - zone_size // 2,
                                zone_size, zone_size)
        right_zone = pygame.Rect(right_cx - zone_size // 2, cy - zone_size // 2,
                                 zone_size, zone_size)
        hit_margin_px = max(0, int(args.hit_margin_px))

        # ---- Trial sequencer ----
        block_id = getattr(args, "block_id", "A")
        probe_rate = float(args.probe_rate) if effective_type == "PEC" else 0.0
        sequencer = TrialSequencer(effective_type, args.target_trials, block_id, probe_rate)

        # ---- Timing parameters ----
        present_duration_s = max(0, int(args.present_duration_ms)) / 1000.0
        choose_timeout_s = max(1, int(args.choose_timeout_s))
        interact_max_s = max(1, int(args.interact_max_s))
        interact_disengage_s = max(1, int(args.interact_disengage_s))
        iti_min_ms = max(0, int(args.iti_min_ms))
        iti_max_ms = max(iti_min_ms, int(args.iti_max_ms))
        reward_cooldown_s = max(0, int(args.reward_cooldown_ms)) / 1000.0
        max_rewards_per_trial = max(1, int(args.max_rewards_per_trial))
        max_rewards_per_session = max(1, int(args.max_rewards_per_session))
        wait_release_timeout_s = max(0, int(args.wait_release_timeout_ms)) / 1000.0
        min_release_after_iti_s = max(0, int(args.min_release_ms_after_iti_touch)) / 1000.0
        max_consecutive_omissions = max(1, int(args.max_consecutive_omissions))
        max_duration_s = max(60, int(args.max_duration_s))

        # ---- Side bias tracking ----
        bias_window = max(5, int(args.bias_window))
        bias_threshold = float(args.bias_threshold)
        bias_correction_trials = max(1, int(args.bias_correction_trials))
        side_choices = deque(maxlen=bias_window)
        bias_correction_active = False
        bias_correction_remaining = 0
        bias_preferred_side = None

        # ---- State machine ----
        STATE_PRESENT = 0
        STATE_CHOOSE = 1
        STATE_INTERACT = 2
        STATE_ITI = 3
        STATE_WAIT_RELEASE = 4
        STATE_PAUSED = 5
        state_names = ["PRESENT", "CHOOSE", "INTERACT", "ITI", "WAIT_RELEASE", "PAUSED"]

        state = STATE_PRESENT
        mouse_down = False
        active_fingers = set()

        # ---- Current trial state ----
        left_interaction = None
        right_interaction = None
        chosen_interaction = None
        chosen_side = ""
        non_chosen_interaction = None
        trial_is_probe = False
        trial_reward_count = 0
        session_reward_count = 0
        interact_touch_count = 0
        touch_id_global = 0
        trial_num = 0
        present_onset_t = 0.0
        interact_start_t = 0.0
        last_touch_interact_t = 0.0
        last_reward_t = 0.0
        choice_latency_ms = 0
        consecutive_omissions = 0
        omission_count = 0

        # ITI / wait-release
        iti_end_time = 0.0
        iti_ms_current = 0
        touch_during_iti = False
        require_release_dwell = False
        release_clear_start_t = None
        wait_release_enter_t = None

        current_trial = None

        # ---- CSV ----
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        start_dt = datetime.now()
        start_iso = start_dt.isoformat(timespec="milliseconds")
        prefix_map = {"ERC": "erc", "PEC": "pec"}
        csv_prefix = prefix_map.get(effective_type, args.session_type.lower())
        if args.session_type.startswith("ABA"):
            csv_prefix = args.session_type.lower()
        out_path = out_dir / f"{csv_prefix}_log_{args.subject_id}_{start_dt.strftime('%Y%m%d_%H%M%S')}.csv"

        fieldnames = [
            "start_iso", "iso", "rel_s", "state", "x", "y", "event", "iti_ms",
            "session_type", "subject_id",
            "trial_num", "pair", "left_interaction", "right_interaction",
            "chosen_interaction", "chosen_side", "is_probe", "reward_given",
            "choice_latency_ms", "interact_duration_ms", "interact_touch_count",
            "trial_reward_count", "touch_id",
            "interaction_hit", "phase",
            "left_zone_x", "left_zone_y", "left_zone_w", "left_zone_h",
            "right_zone_x", "right_zone_y", "right_zone_w", "right_zone_h",
            "left_choices_recent", "right_choices_recent", "is_correction_trial",
            "total_trials", "total_touches", "total_rewards", "session_duration_s",
            "omission_count",
        ]
        csv_f = out_path.open("w", newline="", encoding="utf-8")
        csv_w = csv.DictWriter(csv_f, fieldnames=fieldnames)
        csv_w.writeheader()
        write_count = 0

        t0 = time.perf_counter()

        def left_recent():
            return sum(1 for s in side_choices if s == "left")

        def right_recent():
            return sum(1 for s in side_choices if s == "right")

        def append_log(event_name, x, y, iti_ms=0, extra=None):
            nonlocal write_count
            nowp = time.perf_counter()
            rel = nowp - t0
            iso_now = datetime.now().isoformat(timespec="milliseconds")
            chosen_tag = ""
            if current_trial and chosen_side:
                chosen_tag = current_trial["left"] if chosen_side == "left" else current_trial["right"]
            row = {
                "start_iso": start_iso,
                "iso": iso_now,
                "rel_s": f"{rel:.6f}",
                "state": state_names[state] if state < len(state_names) else str(state),
                "x": x, "y": y,
                "event": event_name,
                "iti_ms": iti_ms if iti_ms else "",
                "session_type": args.session_type,
                "subject_id": args.subject_id,
                "trial_num": trial_num,
                "pair": current_trial["pair"] if current_trial else "",
                "left_interaction": current_trial["left"] if current_trial else "",
                "right_interaction": current_trial["right"] if current_trial else "",
                "chosen_interaction": chosen_tag,
                "chosen_side": chosen_side,
                "is_probe": 1 if trial_is_probe else 0,
                "reward_given": "",
                "choice_latency_ms": "",
                "interact_duration_ms": "",
                "interact_touch_count": interact_touch_count,
                "trial_reward_count": trial_reward_count,
                "touch_id": touch_id_global,
                "interaction_hit": "",
                "phase": state_names[state] if state < len(state_names) else "",
                "left_zone_x": left_zone.x, "left_zone_y": left_zone.y,
                "left_zone_w": left_zone.w, "left_zone_h": left_zone.h,
                "right_zone_x": right_zone.x, "right_zone_y": right_zone.y,
                "right_zone_w": right_zone.w, "right_zone_h": right_zone.h,
                "left_choices_recent": left_recent(),
                "right_choices_recent": right_recent(),
                "is_correction_trial": 1 if bias_correction_active else 0,
                "total_trials": "", "total_touches": "", "total_rewards": "",
                "session_duration_s": "", "omission_count": "",
            }
            if extra is not None:
                row.update(extra)
            csv_w.writerow(row)
            write_count += 1
            if write_count % 64 == 0:
                csv_f.flush()

        def check_bias():
            nonlocal bias_correction_active, bias_correction_remaining, bias_preferred_side
            if bias_correction_active:
                bias_correction_remaining -= 1
                if bias_correction_remaining <= 0:
                    bias_correction_active = False
                    append_log("BIAS_CORRECTION_END", -1, -1)
                return
            if len(side_choices) >= bias_window:
                lc = left_recent()
                rc = right_recent()
                total = lc + rc
                if total > 0:
                    left_prop = lc / total
                    right_prop = rc / total
                    if left_prop >= bias_threshold:
                        bias_preferred_side = "left"
                        bias_correction_active = True
                        bias_correction_remaining = bias_correction_trials
                        append_log("BIAS_CORRECTION_START", -1, -1)
                    elif right_prop >= bias_threshold:
                        bias_preferred_side = "right"
                        bias_correction_active = True
                        bias_correction_remaining = bias_correction_trials
                        append_log("BIAS_CORRECTION_START", -1, -1)

        def place_trial():
            nonlocal current_trial, left_interaction, right_interaction
            nonlocal chosen_interaction, non_chosen_interaction, chosen_side
            nonlocal trial_is_probe, trial_reward_count, interact_touch_count
            nonlocal trial_num, present_onset_t, state

            trial = sequencer.next_trial()
            if trial is None:
                return False
            current_trial = trial
            trial_num = sequencer.trials_completed
            trial_is_probe = trial["is_probe"]
            trial_reward_count = 0
            interact_touch_count = 0
            chosen_interaction = None
            non_chosen_interaction = None
            chosen_side = ""

            left_tag = trial["left"]
            right_tag = trial["right"]

            # Side bias correction: swap sides so preferred interaction appears on non-preferred side
            if bias_correction_active and bias_preferred_side:
                if bias_preferred_side == "left":
                    left_tag, right_tag = right_tag, left_tag
                elif bias_preferred_side == "right":
                    left_tag, right_tag = right_tag, left_tag

            left_interaction = create_interaction(left_tag, left_zone, screen_size)
            right_interaction = create_interaction(right_tag, right_zone, screen_size)

            state = STATE_PRESENT
            present_onset_t = time.perf_counter()
            return True

        def advance_trial():
            if place_trial():
                append_log("TRIAL_START", -1, -1)
                return True
            return False

        # ---- Drawing ----
        def draw_both_preview():
            screen.fill(args.bg_rgb)
            if left_interaction:
                left_interaction.draw_preview(screen)
            if right_interaction:
                right_interaction.draw_preview(screen)
            if args.show_box:
                pygame.draw.rect(screen, (120, 120, 120), left_zone, 2)
                pygame.draw.rect(screen, (120, 120, 120), right_zone, 2)
            if args.info:
                now_t = time.perf_counter()
                elapsed = now_t - t0
                fps = clock.get_fps()
                probe_str = " PROBE" if trial_is_probe else ""
                corr_str = " CORR" if bias_correction_active else ""
                txt = (f"{state_names[state]}  trial={trial_num}/{args.target_trials}  "
                       f"elapsed={elapsed:.0f}s  rewards={session_reward_count}  "
                       f"omit={omission_count}  FPS={fps:.0f}{probe_str}{corr_str}")
                screen.blit(font.render(txt, True, (220, 220, 220)), (10, 10))
            pygame.display.flip()

        def draw_interact():
            screen.fill(args.bg_rgb)
            if chosen_interaction:
                chosen_interaction.draw_active(screen)
            if non_chosen_interaction:
                non_chosen_interaction.draw_dimmed(screen)
            if args.show_box:
                pygame.draw.rect(screen, (120, 120, 120), left_zone, 2)
                pygame.draw.rect(screen, (120, 120, 120), right_zone, 2)
            if args.info:
                now_t = time.perf_counter()
                fps = clock.get_fps()
                txt = (f"INTERACT  trial={trial_num}  side={chosen_side}  "
                       f"touches={interact_touch_count}  rewards={trial_reward_count}  "
                       f"FPS={fps:.0f}")
                screen.blit(font.render(txt, True, (220, 220, 220)), (10, 10))
            pygame.display.flip()

        def draw_blank():
            screen.fill(args.bg_rgb)
            if args.info:
                now_t = time.perf_counter()
                elapsed = now_t - t0
                txt = (f"{state_names[state]}  trial={trial_num}  "
                       f"elapsed={elapsed:.0f}s")
                screen.blit(font.render(txt, True, (220, 220, 220)), (10, 10))
            pygame.display.flip()

        # ---- Start session ----
        append_log("SESSION_START", -1, -1)

        if not place_trial():
            append_log("SESSION_END", -1, -1)
            print("[INFO] No trials to run.")
            return

        append_log("TRIAL_START", -1, -1)
        draw_both_preview()

        running = True
        stop_file = Path("STOP")

        # ------- Main loop -------
        while running:
            if stop_file.exists():
                print("[INFO] STOP file detected. Exiting...")
                running = False
                break

            now = time.perf_counter()
            if now - t0 >= max_duration_s:
                append_log("SESSION_TIMEOUT", -1, -1)
                running = False
                break

            # Quit events
            for ev in pygame.event.get([pygame.QUIT, pygame.KEYDOWN, pygame.KEYUP]):
                if ev.type == pygame.QUIT:
                    running = False; break
                if ev.type in (pygame.KEYDOWN, pygame.KEYUP):
                    if ev.key in (pygame.K_ESCAPE, pygame.K_q):
                        running = False; break
            if not running: break

            pygame.event.pump()
            keys_pressed = pygame.key.get_pressed()
            if keys_pressed[pygame.K_ESCAPE] or keys_pressed[pygame.K_q]:
                running = False; break

            now = time.perf_counter()

            # ---- Input events ----
            want = [pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP]
            if FINGERDOWN is not None: want.append(FINGERDOWN)
            if FINGERUP   is not None: want.append(FINGERUP)

            for ev in pygame.event.get(want):
                # Track contacts
                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    mouse_down = True
                elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                    mouse_down = False
                    if state == STATE_INTERACT and chosen_interaction and isinstance(chosen_interaction, ParticleAttractor):
                        chosen_interaction.on_release()
                elif FINGERDOWN is not None and ev.type == FINGERDOWN:
                    active_fingers.add(ev.finger_id)
                elif FINGERUP is not None and ev.type == FINGERUP:
                    active_fingers.discard(ev.finger_id)
                    if state == STATE_INTERACT and chosen_interaction and isinstance(chosen_interaction, ParticleAttractor):
                        chosen_interaction.on_release()

                def _get_xy(e):
                    if e.type == pygame.MOUSEBUTTONDOWN and e.button == 1:
                        return e.pos
                    elif FINGERDOWN is not None and e.type == FINGERDOWN:
                        return (int(e.x * sw), int(e.y * sh))
                    return None

                # ---- State machine ----
                if state == STATE_PRESENT:
                    pass

                elif state == STATE_CHOOSE:
                    if (ev.type == pygame.MOUSEBUTTONDOWN) or (FINGERDOWN is not None and ev.type == FINGERDOWN):
                        xy = _get_xy(ev)
                        if xy is None:
                            continue
                        x, y = xy
                        touch_id_global += 1

                        left_hit = left_zone.inflate(2 * hit_margin_px, 2 * hit_margin_px).collidepoint(x, y)
                        right_hit = right_zone.inflate(2 * hit_margin_px, 2 * hit_margin_px).collidepoint(x, y)

                        if left_hit or right_hit:
                            if left_hit:
                                chosen_side = "left"
                                chosen_interaction = left_interaction
                                non_chosen_interaction = right_interaction
                            else:
                                chosen_side = "right"
                                chosen_interaction = right_interaction
                                non_chosen_interaction = left_interaction

                            choice_latency_ms = int((time.perf_counter() - present_onset_t) * 1000)
                            consecutive_omissions = 0
                            side_choices.append(chosen_side)

                            reward_given = 0
                            if not trial_is_probe:
                                try:
                                    if ttl is not None:
                                        ttl.pulse()
                                    reward_given = 1
                                    trial_reward_count += 1
                                    session_reward_count += 1
                                    last_reward_t = now
                                except Exception as e:
                                    print(f"[ERROR] TTL failed: {e}", file=sys.stderr)
                                try:
                                    if beep is not None:
                                        beep.play()
                                except Exception:
                                    pass

                            chosen_tag = current_trial["left"] if chosen_side == "left" else current_trial["right"]
                            append_log("TOUCH_CHOOSE", x, y, extra={
                                "interaction_hit": chosen_tag,
                                "reward_given": reward_given,
                                "choice_latency_ms": choice_latency_ms,
                            })

                            if reward_given:
                                append_log("REWARD_TTL", x, y, extra={"reward_given": 1})

                            chosen_interaction.activate(x, y, now)
                            interact_start_t = now
                            last_touch_interact_t = now
                            interact_touch_count = 1
                            state = STATE_INTERACT
                            draw_interact()
                        else:
                            append_log("TOUCH_CHOOSE_OUTSIDE", x, y, extra={
                                "interaction_hit": "outside",
                            })

                elif state == STATE_INTERACT:
                    if (ev.type == pygame.MOUSEBUTTONDOWN) or (FINGERDOWN is not None and ev.type == FINGERDOWN):
                        xy = _get_xy(ev)
                        if xy is None:
                            continue
                        x, y = xy
                        touch_id_global += 1
                        interact_touch_count += 1
                        last_touch_interact_t = now

                        chosen_zone = left_zone if chosen_side == "left" else right_zone
                        if chosen_zone.inflate(2 * hit_margin_px, 2 * hit_margin_px).collidepoint(x, y):
                            chosen_interaction.on_touch(x, y, now)
                            chosen_tag = current_trial["left"] if chosen_side == "left" else current_trial["right"]
                            append_log("TOUCH_INTERACT", x, y, extra={
                                "interaction_hit": chosen_tag,
                            })

                            if not trial_is_probe and (now - last_reward_t >= reward_cooldown_s):
                                if trial_reward_count < max_rewards_per_trial and session_reward_count < max_rewards_per_session:
                                    try:
                                        if ttl is not None:
                                            ttl.pulse()
                                        trial_reward_count += 1
                                        session_reward_count += 1
                                        last_reward_t = now
                                        append_log("REWARD_TTL", x, y, extra={"reward_given": 1})
                                    except Exception as e:
                                        print(f"[ERROR] TTL failed: {e}", file=sys.stderr)
                                    try:
                                        if beep is not None:
                                            beep.play()
                                    except Exception:
                                        pass
                                else:
                                    append_log("REWARD_COOLDOWN", x, y)
                            elif not trial_is_probe:
                                append_log("REWARD_COOLDOWN", x, y)
                        else:
                            append_log("TOUCH_INTERACT_OUTSIDE", x, y, extra={
                                "interaction_hit": "outside",
                            })

                elif state == STATE_ITI:
                    if (ev.type == pygame.MOUSEBUTTONDOWN) or (FINGERDOWN is not None and ev.type == FINGERDOWN):
                        touch_during_iti = True
                        xy = _get_xy(ev)
                        if xy is None:
                            continue
                        x, y = xy
                        touch_id_global += 1
                        append_log("TOUCH_ITI", x, y)

                elif state == STATE_WAIT_RELEASE:
                    pass

                elif state == STATE_PAUSED:
                    if (ev.type == pygame.MOUSEBUTTONDOWN) or (FINGERDOWN is not None and ev.type == FINGERDOWN):
                        xy = _get_xy(ev)
                        if xy is not None:
                            append_log("SESSION_RESUME", xy[0], xy[1])
                            consecutive_omissions = 0
                            if advance_trial():
                                draw_both_preview()
                            else:
                                running = False

            if not running: break

            # ---- Time-based transitions ----
            now = time.perf_counter()

            if state == STATE_PRESENT:
                if now - present_onset_t >= present_duration_s:
                    state = STATE_CHOOSE
                    append_log("CHOOSE_ENABLED", -1, -1)

            elif state == STATE_CHOOSE:
                if now - present_onset_t >= choose_timeout_s:
                    omission_count += 1
                    consecutive_omissions += 1
                    append_log("OMISSION", -1, -1)

                    if consecutive_omissions >= max_consecutive_omissions:
                        state = STATE_PAUSED
                        append_log("SESSION_PAUSE", -1, -1)
                        screen.fill((20, 20, 20))
                        if args.info:
                            txt = "PAUSED -- touch to resume"
                            screen.blit(font.render(txt, True, (150, 150, 150)),
                                        (sw // 2 - 100, sh // 2))
                        pygame.display.flip()
                    else:
                        iti_ms_current = random.randint(iti_min_ms, iti_max_ms)
                        iti_end_time = now + iti_ms_current / 1000.0
                        state = STATE_ITI
                        touch_during_iti = mouse_down or bool(active_fingers)
                        append_log("ITI_START", -1, -1, iti_ms=iti_ms_current)
                        draw_blank()

            elif state == STATE_INTERACT:
                dt = clock.get_time() / 1000.0
                if chosen_interaction:
                    chosen_interaction.update(dt, now)
                    if chosen_interaction.needs_redraw:
                        draw_interact()

                if now - interact_start_t >= interact_max_s:
                    interact_dur_ms = int((now - interact_start_t) * 1000)
                    if chosen_interaction:
                        chosen_interaction.deactivate()
                    append_log("INTERACT_TIMEOUT", -1, -1, extra={
                        "interact_duration_ms": interact_dur_ms,
                    })
                    iti_ms_current = random.randint(iti_min_ms, iti_max_ms)
                    iti_end_time = now + iti_ms_current / 1000.0
                    state = STATE_ITI
                    touch_during_iti = mouse_down or bool(active_fingers)
                    append_log("ITI_START", -1, -1, iti_ms=iti_ms_current)
                    draw_blank()
                elif now - last_touch_interact_t >= interact_disengage_s:
                    interact_dur_ms = int((now - interact_start_t) * 1000)
                    if chosen_interaction:
                        chosen_interaction.deactivate()
                    append_log("INTERACT_DISENGAGE", -1, -1, extra={
                        "interact_duration_ms": interact_dur_ms,
                    })
                    iti_ms_current = random.randint(iti_min_ms, iti_max_ms)
                    iti_end_time = now + iti_ms_current / 1000.0
                    state = STATE_ITI
                    touch_during_iti = mouse_down or bool(active_fingers)
                    append_log("ITI_START", -1, -1, iti_ms=iti_ms_current)
                    draw_blank()

            elif state == STATE_ITI:
                if now >= iti_end_time:
                    state = STATE_WAIT_RELEASE
                    wait_release_enter_t = now
                    release_clear_start_t = None
                    require_release_dwell = touch_during_iti and (min_release_after_iti_s > 0)
                    append_log("WAIT_RELEASE_START", -1, -1)
                    if require_release_dwell:
                        append_log("RELEASE_DWELL_WILL_REQUIRE", -1, -1)

            elif state == STATE_WAIT_RELEASE:
                no_touch_now = (not mouse_down and not active_fingers)

                if require_release_dwell:
                    if no_touch_now:
                        if release_clear_start_t is None:
                            release_clear_start_t = now
                            append_log("RELEASE_DWELL_START", -1, -1)
                        else:
                            elapsed_dwell = now - release_clear_start_t
                            if elapsed_dwell >= min_release_after_iti_s:
                                append_log("RELEASE_DWELL_OK", -1, -1)
                                append_log("TRIAL_END", -1, -1)
                                check_bias()
                                require_release_dwell = False
                                touch_during_iti = False
                                if advance_trial():
                                    draw_both_preview()
                                else:
                                    running = False
                    else:
                        if release_clear_start_t is not None:
                            append_log("RELEASE_DWELL_RESET", -1, -1)
                        release_clear_start_t = None
                else:
                    if no_touch_now:
                        append_log("TRIAL_END", -1, -1)
                        check_bias()
                        touch_during_iti = False
                        if advance_trial():
                            draw_both_preview()
                        else:
                            running = False

                # Timeout failsafe
                if state == STATE_WAIT_RELEASE and wait_release_enter_t is not None and (now - wait_release_enter_t) >= wait_release_timeout_s:
                    if mouse_down or active_fingers:
                        active_fingers.clear()
                        mouse_down = False
                        if require_release_dwell and release_clear_start_t is None:
                            release_clear_start_t = now
                            append_log("RELEASE_DWELL_START_FORCED", -1, -1)
                        elif not require_release_dwell:
                            append_log("TRIAL_END", -1, -1)
                            check_bias()
                            touch_during_iti = False
                            if advance_trial():
                                draw_both_preview()
                            else:
                                running = False

            # Tick rate
            if state == STATE_INTERACT:
                clock.tick(60)
            else:
                clock.tick(240)

        # ---- Session end ----
        now = time.perf_counter()
        rel = now - t0
        iso_end = datetime.now().isoformat(timespec="milliseconds")
        summary_row = {
            "start_iso": start_iso,
            "iso": iso_end,
            "rel_s": f"{rel:.6f}",
            "state": state_names[state] if state < len(state_names) else "",
            "x": -1, "y": -1,
            "event": "SESSION_END",
            "iti_ms": "",
            "session_type": args.session_type,
            "subject_id": args.subject_id,
            "trial_num": trial_num,
            "pair": "", "left_interaction": "", "right_interaction": "",
            "chosen_interaction": "", "chosen_side": "",
            "is_probe": "", "reward_given": "",
            "choice_latency_ms": "", "interact_duration_ms": "",
            "interact_touch_count": "", "trial_reward_count": "",
            "touch_id": touch_id_global,
            "interaction_hit": "", "phase": "",
            "left_zone_x": left_zone.x, "left_zone_y": left_zone.y,
            "left_zone_w": left_zone.w, "left_zone_h": left_zone.h,
            "right_zone_x": right_zone.x, "right_zone_y": right_zone.y,
            "right_zone_w": right_zone.w, "right_zone_h": right_zone.h,
            "left_choices_recent": left_recent(),
            "right_choices_recent": right_recent(),
            "is_correction_trial": "",
            "total_trials": trial_num,
            "total_touches": touch_id_global,
            "total_rewards": session_reward_count,
            "session_duration_s": f"{rel:.6f}",
            "omission_count": omission_count,
        }
        csv_w.writerow(summary_row)
        csv_f.flush()
        print(f"[INFO] Session done. Trials={trial_num} Rewards={session_reward_count} Saved CSV: {out_path}")

    finally:
        if csv_f is not None:
            try:
                csv_f.flush()
                csv_f.close()
            except Exception:
                pass

# =========================
# Argument parser
# =========================
def parse_args():
    p = argparse.ArgumentParser(
        description="Object Explore Task: touchscreen interaction preference measurement"
    )

    # ====== Session ======
    p.add_argument("--session-type",
        choices=["ERC", "PEC", "FOV", "ABA_A", "ABA_B"],
        required=True,
        help="Session type. ABA_A=FOV baseline, ABA_B=ERC reward phase.")
    p.add_argument("--subject-id", type=str, required=True,
        help="Subject identifier (e.g., '280')")
    p.add_argument("--block-id", choices=["A", "B"], default="A",
        help="BIBD block for pair selection (ERC/PEC).")
    p.add_argument("--target-trials", type=int, default=50,
        help="Target number of trials (ERC/PEC). Default 50.")
    p.add_argument("--max-duration-s", type=int, default=1200,
        help="Hard session cutoff in seconds. Default 1200 (20 min).")

    # ====== Display ======
    p.add_argument("--fullscreen", action="store_true")
    p.add_argument("--window-w", type=int, default=1280)
    p.add_argument("--window-h", type=int, default=720)
    p.add_argument("--kiosk", action="store_true",
        help="Fullscreen + hide cursor + grab input")
    p.add_argument("--bg-rgb", type=int, nargs=3, default=[0, 0, 0])

    # ====== Input ======
    p.add_argument("--touch-only", action="store_true",
        help="Block mouse events, accept only touch (FINGER*)")

    # ====== Layout (ERC/PEC) ======
    p.add_argument("--zone-size-px", type=int, default=280,
        help="Width and height of each interaction zone (px). Default 280.")
    p.add_argument("--center-offset-px", type=int, default=220,
        help="Horizontal distance from screen center to zone center (px).")
    p.add_argument("--edge-margin-px", type=int, default=16)
    p.add_argument("--hit-margin-px", type=int, default=20,
        help="Touch margin around interaction zone for hit detection.")

    # ====== Layout (FOV) ======
    p.add_argument("--fov-zone-size-px", type=int, default=200,
        help="Zone size for FOV pentagon layout (px).")
    p.add_argument("--fov-rotation", type=int, default=0,
        help="Pentagon rotation in units of 72 degrees (0-4).")
    p.add_argument("--fov-max-duration-s", type=int, default=300,
        help="FOV maximum duration. Default 300 (5 min).")
    p.add_argument("--fov-inactivity-timeout-s", type=int, default=120,
        help="FOV auto-terminate after this many seconds of no touches. Default 120.")

    # ====== Trial timing ======
    p.add_argument("--present-duration-ms", type=int, default=500,
        help="Duration of PRESENT phase (ms). Default 500.")
    p.add_argument("--choose-timeout-s", type=int, default=60,
        help="Maximum wait for choice (s). Default 60.")
    p.add_argument("--interact-max-s", type=int, default=10,
        help="Maximum INTERACT phase duration (s). Default 10.")
    p.add_argument("--interact-disengage-s", type=int, default=3,
        help="INTERACT ends after this many seconds of no touch. Default 3.")
    p.add_argument("--iti-min-ms", type=int, default=2000)
    p.add_argument("--iti-max-ms", type=int, default=4000)

    # ====== Reward ======
    p.add_argument("--serial-port", type=str, required=True)
    p.add_argument("--serial-baud", type=int, default=115200)
    p.add_argument("--reward-cooldown-ms", type=int, default=2000,
        help="Minimum interval between rewards within INTERACT phase (ms). Default 2000.")
    p.add_argument("--max-rewards-per-trial", type=int, default=5)
    p.add_argument("--max-rewards-per-session", type=int, default=80)
    p.add_argument("--probe-rate", type=float, default=0.15,
        help="Fraction of unrewarded probe trials (PEC only). Default 0.15.")

    # ====== Sound ======
    p.add_argument("--beep-freq", type=int, default=1000)
    p.add_argument("--beep-ms", type=int, default=100)
    p.add_argument("--beep-volume", type=float, default=0.6)

    # ====== Wait-release ======
    p.add_argument("--wait-release-timeout-ms", type=int, default=5000)
    p.add_argument("--min-release-ms-after-iti-touch", type=int, default=2000)

    # ====== Side bias correction ======
    p.add_argument("--bias-threshold", type=float, default=0.8,
        help="Side bias threshold.")
    p.add_argument("--bias-window", type=int, default=10,
        help="Number of recent trials for bias detection.")
    p.add_argument("--bias-correction-trials", type=int, default=3,
        help="Number of forced-correction trials when bias detected.")

    # ====== Omission handling ======
    p.add_argument("--max-consecutive-omissions", type=int, default=3,
        help="Auto-pause session after this many consecutive omissions.")

    # ====== Output ======
    p.add_argument("--out-dir", type=str, default="logs")
    p.add_argument("--info", action="store_true",
        help="Show debug overlay on screen.")
    p.add_argument("--show-box", action="store_true",
        help="Draw zone boundary boxes.")

    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(args)
