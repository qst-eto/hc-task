from __future__ import annotations

import csv
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class RectSpec:
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class TwoChoiceRects:
    left: RectSpec
    right: RectSpec
    left_plate: RectSpec
    right_plate: RectSpec


@dataclass(frozen=True)
class ItiRanges:
    rewarded: Tuple[int, int]
    unrewarded: Tuple[int, int]
    outside: Tuple[int, int]


@dataclass(frozen=True)
class TwoChoiceSessionHandles:
    screen: Any
    clock: Any
    font: Any
    sw: int
    sh: int
    FINGERDOWN: Optional[int]
    FINGERUP: Optional[int]
    fullscreen: bool


def empty_csv_row(fieldnames: Sequence[str]) -> Dict[str, str]:
    return {name: "" for name in fieldnames}


def complete_csv_row(row: Mapping[str, Any], fieldnames: Sequence[str]) -> Dict[str, Any]:
    extra = sorted(set(row.keys()) - set(fieldnames))
    if extra:
        raise ValueError("row contains keys not present in CSV_FIELDNAMES: " + ", ".join(extra))

    complete = empty_csv_row(fieldnames)
    complete.update(row)
    return complete


def write_rows_csv(rows: Iterable[Mapping[str, Any]], out_path: Path, fieldnames: Sequence[str]) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        for row in rows:
            w.writerow(complete_csv_row(row, fieldnames))
    return out_path


def bounded_range(min_ms: Optional[int], max_ms: Optional[int], base_min: int, base_max: int) -> Tuple[int, int]:
    lo = base_min if min_ms is None else int(min_ms)
    hi = base_max if max_ms is None else int(max_ms)
    lo = max(0, lo)
    hi = max(lo, hi)
    return lo, hi


def truncate_at_max_rewards(rows, max_rewards: Optional[int]):
    if max_rewards is None:
        return rows

    kept = []
    delivered = 0
    for row in rows:
        kept.append(row)
        if row.get("reward_delivered"):
            delivered += 1
            if delivered >= max_rewards:
                break
    return kept


def compute_two_choice_rects(
    sw: int,
    sh: int,
    item_w: int,
    item_h: int,
    plate_w: int,
    plate_h: int,
    center_offset_px: int,
    edge_margin_px: int,
    sth: float=0,
) -> Tuple[TwoChoiceRects, int]:
    max_offset = max(0, (sw // 2) - (plate_w // 2) - edge_margin_px)
    center_offset = min(max_offset, max(0, center_offset_px))

    cy = sh // 2
    left_cx = (sw // 2) - center_offset
    right_cx = (sw // 2) + center_offset

    rects = TwoChoiceRects(
        left=RectSpec(left_cx - item_w // 2, cy - item_h // 2 + sth, item_w, item_h),
        right=RectSpec(right_cx - item_w // 2, cy - item_h // 2 + sth, item_w, item_h),
        left_plate=RectSpec(left_cx - plate_w // 2, cy - plate_h // 2 + sth, plate_w, plate_h),
        right_plate=RectSpec(right_cx - plate_w // 2, cy - plate_h // 2 + sth, plate_w, plate_h),
    )
    return rects, center_offset


def build_iti_ranges(
    *,
    base_min: int,
    base_max: int,
    rewarded_min_ms: Optional[int],
    rewarded_max_ms: Optional[int],
    unrewarded_min_ms: Optional[int],
    unrewarded_max_ms: Optional[int],
    outside_min_ms: Optional[int],
    outside_max_ms: Optional[int],
) -> ItiRanges:
    return ItiRanges(
        rewarded=bounded_range(rewarded_min_ms, rewarded_max_ms, base_min, base_max),
        unrewarded=bounded_range(unrewarded_min_ms, unrewarded_max_ms, base_min, base_max),
        outside=bounded_range(outside_min_ms, outside_max_ms, base_min, base_max),
    )


def sample_iti(kind: str, ranges: ItiRanges, iti_rng) -> int:
    if kind == "rewarded":
        lo, hi = ranges.rewarded
        return iti_rng.randint(lo, hi)
    if kind == "unrewarded":
        lo, hi = ranges.unrewarded
        return iti_rng.randint(lo, hi)
    if kind == "outside":
        lo, hi = ranges.outside
        return iti_rng.randint(lo, hi)
    raise ValueError("ITI kind must be rewarded, unrewarded, or outside")


def init_two_choice_session(
    *,
    window_title: str,
    fullscreen: bool,
    window_w: int,
    window_h: int,
    kiosk: bool,
    touch_only: bool,
    font_size: int = 28,
) -> TwoChoiceSessionHandles:
    import pygame

    pygame.init()
    try:
        pygame.mixer.init(frequency=44100, size=-16, channels=2)
    except Exception as e:
        print(f"[WARN] mixer init failed: {e}", file=sys.stderr)

    try:
        pygame.display.set_allow_screensaver(False)
    except Exception:
        pass

    FINGERDOWN = getattr(pygame, "FINGERDOWN", None)
    FINGERUP = getattr(pygame, "FINGERUP", None)
    FINGERMOTION = getattr(pygame, "FINGERMOTION", None)
    MOUSEWHEEL = getattr(pygame, "MOUSEWHEEL", None)

    to_block = [pygame.MOUSEMOTION]
    if FINGERMOTION is not None:
        to_block.append(FINGERMOTION)
    if MOUSEWHEEL is not None:
        to_block.append(MOUSEWHEEL)
    pygame.event.set_blocked(to_block)

    if kiosk:
        fullscreen = True
        pygame.mouse.set_visible(False)
        pygame.event.set_grab(True)
    if touch_only:
        pygame.event.set_blocked(pygame.MOUSEBUTTONDOWN)
        pygame.event.set_blocked(pygame.MOUSEBUTTONUP)
        pygame.event.set_blocked(pygame.MOUSEMOTION)

    flags = pygame.FULLSCREEN if fullscreen else pygame.NOFRAME
    screen = pygame.display.set_mode(
        (0, 0) if fullscreen else (window_w, window_h),
        flags,
    )
    pygame.display.set_caption(window_title)
    clock = pygame.time.Clock()
    font = pygame.font.SysFont(None, font_size)
    sw, sh = screen.get_size()

    return TwoChoiceSessionHandles(
        screen=screen,
        clock=clock,
        font=font,
        sw=sw,
        sh=sh,
        FINGERDOWN=FINGERDOWN,
        FINGERUP=FINGERUP,
        fullscreen=fullscreen,
    )
