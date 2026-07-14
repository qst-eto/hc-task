from __future__ import annotations

import hashlib
import math
import random
import sys
import time
from typing import Optional, Tuple

try:
    import serial
except Exception:
    serial = None


def derive_rng(master_seed: int, stream: str) -> random.Random:
    seed_bytes = hashlib.sha256((str(master_seed) + ":" + stream).encode()).digest()[:8]
    seed_int = int.from_bytes(seed_bytes, "big")
    return random.Random(seed_int)


def sample_reward(rng: random.Random, p: float) -> Tuple[float, bool]:
    u = rng.random()
    return (u, u < p)


class ArduinoTTLSender:
    def __init__(self, port: Optional[str], baud: int = 115200, dry_run: bool = False):
        self.port = port
        self.baud = baud
        self.dry_run = dry_run
        self.pulse_count = 0
        self.ser = None

        if self.dry_run:
            return

        if serial is None:
            raise RuntimeError("pyserial is required for ArduinoTTLSender when dry_run is False")

        self.ser = serial.Serial(port, baud, timeout=0, write_timeout=0.2)

    def pulse(self) -> None:
        self.pulse_count += 1

        if self.dry_run:
            print("ArduinoTTLSender dry-run: PULSE", file=sys.stderr)
            return

        if self.ser is None:
            raise RuntimeError("Arduino serial connection is not open")

        self.ser.write(b"PULSE\n")
        self.ser.flush()

    def close(self) -> None:
        if self.ser is not None:
            self.ser.close()
            self.ser = None


def make_beep_sound(freq_hz: int, ms: int, volume: float):
    volume = max(0.0, min(1.0, float(volume)))

    try:
        import pygame
    except Exception as exc:
        raise RuntimeError("pygame is required to synthesize beep sounds") from exc

    try:
        import numpy
    except Exception:
        numpy = None

    sample_rate = 44100
    n_samples = int(sample_rate * ms / 1000.0)

    if numpy is not None:
        t = numpy.arange(n_samples, dtype=numpy.float32) / float(sample_rate)
        wave = numpy.sin(2.0 * math.pi * float(freq_hz) * t) * float(volume)
        samples = (wave * 32767.0).astype(numpy.int16)
        stereo = numpy.column_stack((samples, samples))
        return pygame.sndarray.make_sound(stereo)

    array_module = None
    try:
        from array import array as array_module
    except Exception as exc:
        raise RuntimeError("Python array module is required to synthesize beep sounds without numpy") from exc

    samples = array_module("h")
    amp = max(0.0, min(1.0, float(volume))) * 32767.0
    for i in range(n_samples):
        value = int(math.sin(2.0 * math.pi * float(freq_hz) * i / float(sample_rate)) * amp)
        samples.append(value)
        samples.append(value)

    return pygame.mixer.Sound(buffer=samples.tobytes())


def deliver_reward(ttl, beep, pulsecount: int = 1) -> Tuple[bool, bool]:
    ttl_ok = False
    beep_ok = False

    if beep is not None:
        try:
            beep.play()
            beep_ok = True
        except Exception:
            beep_ok = False

    try:
        for i in range(pulsecount):
            ttl.pulse()
            time.sleep(0.28)
            print(pulse)
        ttl_ok = True
    except Exception:
        ttl_ok = False



    return (ttl_ok, beep_ok)


def get_xy(event, screen_w: int, screen_h: int) -> Tuple[int, int]:
    pos = getattr(event, "pos", None)
    if pos is not None:
        return (int(pos[0]), int(pos[1]))

    x = getattr(event, "x", None)
    y = getattr(event, "y", None)
    if x is None or y is None:
        raise AttributeError("event must provide either pos or normalized x/y coordinates")

    return (int(float(x) * screen_w), int(float(y) * screen_h))
