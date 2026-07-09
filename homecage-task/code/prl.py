from __future__ import annotations

import argparse
import csv
import re
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import task_common
import touch_task_runner as ttr
from schedules import ReversalSchedule, validate_reversal_schedule
from task_common import ArduinoTTLSender, deliver_reward, derive_rng, get_xy, make_beep_sound

STATE_NAMES = ["SHOW", "ITI", "WAIT_RELEASE"]

CSV_FIELDNAMES = [
    "start_iso", "iso", "rel_s", "state",
    "x", "y",
    "left_x", "left_y", "left_w", "left_h",
    "right_x", "right_y", "right_w", "right_h",
    "left_plate_x", "left_plate_y", "left_plate_w", "left_plate_h",
    "right_plate_x", "right_plate_y", "right_plate_w", "right_plate_h",
    "hit_margin_px", "hit_area",
    "event",
    "iti_ms", "iti_kind",
    "outside_in_trial", "max_outside_before_fail",
    "trial_outcome", "fail_reason",
    "stim_set", "left_label", "right_label",
    "left_image", "right_image", "target_image", "non_target_image",
    "trial_index_global", "trial_index_in_set",
    "correction_mode", "is_correction_trial",
    "seed", "schedule_hash",
    "block_index", "trial_in_block", "scheduled_reversal_trial", "is_post_reversal",
    "high_label", "p_high", "p_low", "chosen_label", "is_correct",
    "p_chosen", "reward_draw", "reward_won", "reward_delivered",
]


class StimPair:
    def __init__(self, idx_num: int, r_path: Path, nr_path: Path):
        self.idx_num = idx_num
        self.r_path = r_path
        self.nr_path = nr_path
        self.r_surf = None
        self.nr_surf = None

    @property
    def label(self):
        return f"stim_{self.idx_num:02d}"


def find_stim_pairs(stim_dir: Path):
    rx_r = re.compile(r"^stim_(\d+)_r\.png$", re.IGNORECASE)
    rx_nr = re.compile(r"^stim_(\d+)_nr\.png$", re.IGNORECASE)

    r_map = {}
    nr_map = {}
    for p in stim_dir.glob("*.png"):
        m = rx_r.match(p.name)
        if m:
            r_map[int(m.group(1))] = p
            continue
        m = rx_nr.match(p.name)
        if m:
            nr_map[int(m.group(1))] = p
            continue

    idxs = sorted(set(r_map.keys()) & set(nr_map.keys()))
    return [StimPair(i, r_map[i], nr_map[i]) for i in idxs]


def _schedule_len(sched) -> int:
    return int(sched.n_blocks) * int(sched.block_len)


def load_or_generate_schedule(args):
    if args.schedule_json:
        sched = ReversalSchedule.from_json(args.schedule_json)
    else:
        sched = ReversalSchedule.generate(
            seed=args.seed,
            n_blocks=args.n_blocks,
            block_len=args.block_len_trials,
            reversal_min=args.reversal_min_trial,
            reversal_max=args.reversal_max_trial,
            schedule_set=args.schedule_set,
            initial_high_label=args.initial_high_label,
        )

    validate_reversal_schedule(sched)

    if args.save_schedule_json:
        sched.to_json(args.save_schedule_json)

    return sched


def resolve_trial(
    sched,
    global_trial: int,
    chosen_label: str,
    reward_rng,
    reverse_high=False,
) -> Dict:
    if chosen_label not in ("r", "nr"):
        raise ValueError("chosen_label must be 'r' or 'nr'")

    info = dict(sched.lookup(global_trial))
    high_label = info["high_label"]

    if reverse_high:
        high_label = "nr" if high_label == "r" else "r"
        info["high_label"] = high_label
    p_high = info["p_high"]
    p_low = info["p_low"]
    is_correct = chosen_label == high_label
    p_chosen = p_high if is_correct else p_low
    u, won = task_common.sample_reward(reward_rng, p_chosen)

    return {
        "block_index": info["block_index"],
        "trial_in_block": info["trial_in_block"],
        "scheduled_reversal_trial": info["scheduled_reversal_trial"],
        "is_post_reversal": info["is_post_reversal"],
        "high_label": high_label,
        "p_high": p_high,
        "p_low": p_low,
        "chosen_label": chosen_label,
        "is_correct": is_correct,
        "p_chosen": p_chosen,
        "reward_draw": u,
        "reward_won": 1 if won else 0,
    }


def simulate(sched, seed: int, sim_choices: str, total_trials: int) -> List[Dict]:
    if sim_choices not in ("high", "low", "random", "alternate"):
        raise ValueError("sim_choices must be high, low, random, or alternate")

    layout_rng = derive_rng(seed, "layout")
    reward_rng = derive_rng(seed, "reward")
    sim_rng = derive_rng(seed, "sim")
    schedule_hash = sched.schedule_hash()

    rows = []
    for t in range(total_trials):
        left_is_r = bool(layout_rng.getrandbits(1))
        info = sched.lookup(t)
        high_label = info["high_label"]
        other = "nr" if high_label == "r" else "r"

        if sim_choices == "high":
            chosen_label = high_label
        elif sim_choices == "low":
            chosen_label = other
        elif sim_choices == "random":
            chosen_label = high_label if sim_rng.random() < 0.5 else other
        else:
            chosen_label = high_label if (t % 2 == 0) else other

        r = resolve_trial(sched, t, chosen_label, reward_rng)
        r["start_iso"] = ""
        r["iso"] = ""
        r["rel_s"] = ""
        r["state"] = "SIM"
        r["event"] = "SIM_CHOICE"
        r["seed"] = seed
        r["schedule_hash"] = schedule_hash
        r["reward_delivered"] = 1 if r["reward_won"] else 0
        r["iti_kind"] = "rewarded" if r["reward_won"] else "unrewarded"
        r["left_label"] = "r" if left_is_r else "nr"
        r["right_label"] = "nr" if left_is_r else "r"
        r["trial_index_global"] = t
        r["trial_index_in_set"] = info["trial_in_block"]
        r["trial_outcome"] = "correct" if r["is_correct"] else "incorrect"
        rows.append(r)

    return rows


def _empty_csv_row() -> Dict:
    return ttr.empty_csv_row(CSV_FIELDNAMES)


def _complete_csv_row(row: Dict) -> Dict:
    return ttr.complete_csv_row(row, CSV_FIELDNAMES)


def write_rows_csv(rows: List[Dict], out_path: Path) -> Path:
    return ttr.write_rows_csv(rows, out_path, CSV_FIELDNAMES)


def write_simulation_csv(rows: List[Dict], out_dir: str, filename: Optional[str] = None) -> Path:
    out_dir_path = Path(out_dir)
    if filename is None:
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"prl_sim_log_{stamp}.csv"
    return write_rows_csv(rows, out_dir_path / filename)


def _bounded_range(min_ms: Optional[int], max_ms: Optional[int], base_min: int, base_max: int) -> Tuple[int, int]:
    return ttr.bounded_range(min_ms, max_ms, base_min, base_max)


def _truncate_at_max_rewards(rows: List[Dict], max_rewards: Optional[int]) -> List[Dict]:
    return ttr.truncate_at_max_rewards(rows, max_rewards)


def run_sim(args) -> Path:
    sched = load_or_generate_schedule(args)
    total_trials = _schedule_len(sched)
    if args.max_trials is not None:
        total_trials = min(total_trials, max(0, int(args.max_trials)))

    rows = simulate(sched, args.seed, args.sim_choices, total_trials)
    rows = _truncate_at_max_rewards(rows, args.max_rewards)
    out_path = write_simulation_csv(rows, args.out_dir)

    rewards = sum(1 for r in rows if r["reward_delivered"])
    correct = sum(1 for r in rows if r["is_correct"])
    print(
        f"[INFO] Simulated {len(rows)} trials; correct={correct}; rewards={rewards}; "
        f"schedule_hash={sched.schedule_hash()}; CSV={out_path}"
    )
    return out_path


def run(args):
    import pygame

    sched = load_or_generate_schedule(args)
    schedule_hash = sched.schedule_hash()
    total_trials = _schedule_len(sched)
    if args.max_trials is not None:
        total_trials = min(total_trials, max(0, int(args.max_trials)))

    layout_rng = derive_rng(args.seed, "layout")
    reward_rng = derive_rng(args.seed, "reward")
    iti_rng = derive_rng(args.seed, "iti")

    ttl = None
    csv_f = None

    try:
        session = ttr.init_two_choice_session(
            window_title="Probabilistic Reversal Learning",
            fullscreen=args.fullscreen,
            window_w=args.window_w,
            window_h=args.window_h,
            kiosk=args.kiosk,
            touch_only=args.touch_only,
        )
        args.fullscreen = session.fullscreen
        screen = session.screen
        clock = session.clock
        font = session.font
        sw, sh = session.sw, session.sh
        FINGERDOWN = session.FINGERDOWN
        FINGERUP = session.FINGERUP

        stim_dir = Path(args.stim_dir)
        if not stim_dir.exists():
            raise RuntimeError(f"stimulus directory not found: {stim_dir}")
        stim_pairs = find_stim_pairs(stim_dir)
        if not stim_pairs:
            raise RuntimeError(f"{stim_dir} does not contain stim_XX_r.png / stim_XX_nr.png pairs")

        if args.stim_px is not None:
            stim_w = stim_h = max(1, int(args.stim_px))
        else:
            stim_w = max(1, int(args.stim_w))
            stim_h = max(1, int(args.stim_h))

        if args.plate_px is not None:
            plate_w = plate_h = max(stim_w, stim_h, int(args.plate_px))
        elif args.plate_w is not None and args.plate_h is not None:
            plate_w = max(stim_w, int(args.plate_w))
            plate_h = max(stim_h, int(args.plate_h))
        else:
            plate_w, plate_h = stim_w, stim_h

        edge_margin = max(0, int(args.edge_margin_px))
        rect_specs, center_offset = ttr.compute_two_choice_rects(
            sw,
            sh,
            stim_w,
            stim_h,
            plate_w,
            plate_h,
            int(args.center_offset_px),
            edge_margin,
            sth = args.sth,
            
        )
        if center_offset < int(args.center_offset_px):
            print(f"[WARN] center-offset clamped to {center_offset}px", file=sys.stderr)

        def pygame_rect(rect: ttr.RectSpec):
            return pygame.Rect(rect.x, rect.y, rect.w, rect.h)

        def compute_rects():
            return (
                pygame_rect(rect_specs.left),
                pygame_rect(rect_specs.right),
                pygame_rect(rect_specs.left_plate),
                pygame_rect(rect_specs.right_plate),
            )

        for sp in stim_pairs:
            r_img = pygame.image.load(str(sp.r_path)).convert_alpha()
            nr_img = pygame.image.load(str(sp.nr_path)).convert_alpha()
            if r_img.get_width() != stim_w or r_img.get_height() != stim_h:
                r_img = pygame.transform.smoothscale(r_img, (stim_w, stim_h))
            if nr_img.get_width() != stim_w or nr_img.get_height() != stim_h:
                nr_img = pygame.transform.smoothscale(nr_img, (stim_w, stim_h))
            sp.r_surf = r_img
            sp.nr_surf = nr_img

        base_min = max(0, int(args.iti_min_ms))
        base_max = max(base_min, int(args.iti_max_ms))
        iti_ranges = ttr.build_iti_ranges(
            base_min=base_min,
            base_max=base_max,
            rewarded_min_ms=args.iti_rewarded_min_ms,
            rewarded_max_ms=args.iti_rewarded_max_ms,
            unrewarded_min_ms=args.iti_unrewarded_min_ms,
            unrewarded_max_ms=args.iti_unrewarded_max_ms,
            outside_min_ms=args.iti_outside_min_ms,
            outside_max_ms=args.iti_outside_max_ms,
        )

        def sample_iti(kind: str) -> int:
            return ttr.sample_iti(kind, iti_ranges, iti_rng)

        wait_release_timeout = max(0, int(args.wait_release_timeout_ms)) / 1000.0
        min_release_after_iti_touch_s = max(0, int(args.min_release_ms_after_iti_touch)) / 1000.0
        max_outside_before_fail = max(1, int(args.max_outside_before_fail))
        hit_margin_px = max(0, int(args.hit_margin_px))

        STATE_SHOW, STATE_ITI, STATE_WAIT_RELEASE = 0, 1, 2
        state = STATE_SHOW
        mouse_down = False
        active_fingers = set()
        outside_touches_in_trial = 0

        touch_during_iti = False
        require_release_dwell = False
        release_clear_start_t = None
        wait_release_enter_t = None

        if not args.dry_run_ttl and not args.serial_port:
            raise RuntimeError("--serial-port is required unless --dry-run-ttl is used")
        ttl = ArduinoTTLSender(args.serial_port, args.serial_baud, dry_run=args.dry_run_ttl)

        try:
            beep = make_beep_sound(args.beep_freq, args.beep_ms, args.beep_volume)
        except Exception as e:
            beep = None
            print(f"[WARN] beep disabled: {e}", file=sys.stderr)

        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        start_dt = datetime.now()
        start_iso = start_dt.isoformat(timespec="milliseconds")
        out_path = out_dir / f"prl_log_{start_dt.strftime('%Y%m%d_%H%M%S')}.csv"

        csv_f = out_path.open("w", newline="", encoding="utf-8")
        csv_w = csv.DictWriter(csv_f, fieldnames=CSV_FIELDNAMES)
        csv_w.writeheader()
        write_count = 0

        t0 = time.perf_counter()
        choices = 0
        correct_choices = 0
        incorrect_choices = 0
        reward_count = 0
        outside_failures = 0
        schedule_trial_index = 0

        correction_mode_enabled = bool(args.correction_mode)
        correction_active = False
        correction_left_is_r = None
        current_trial_is_correction = False

        left_rect, right_rect, left_plate_rect, right_plate_rect = compute_rects()
        left_is_r = True
        left_surf = None
        right_surf = None
        current_context = None
        

        def pair_for_block(block_index: int):
            if args.stim_per_block == "fixed":
                return stim_pairs[0]
            return stim_pairs[block_index % len(stim_pairs)]

        def append_log(event_name, x, y, iti_ms, extra=None):
            nonlocal write_count
            nowp = time.perf_counter()
            rel = nowp - t0
            iso = datetime.now().isoformat(timespec="milliseconds")

            row = _empty_csv_row()
            row.update({
                "start_iso": start_iso,
                "iso": iso,
                "rel_s": f"{rel:.6f}",
                "state": STATE_NAMES[state],
                "x": x,
                "y": y,
                "left_x": left_rect.x,
                "left_y": left_rect.y,
                "left_w": left_rect.w,
                "left_h": left_rect.h,
                "right_x": right_rect.x,
                "right_y": right_rect.y,
                "right_w": right_rect.w,
                "right_h": right_rect.h,
                "left_plate_x": left_plate_rect.x,
                "left_plate_y": left_plate_rect.y,
                "left_plate_w": left_plate_rect.w,
                "left_plate_h": left_plate_rect.h,
                "right_plate_x": right_plate_rect.x,
                "right_plate_y": right_plate_rect.y,
                "right_plate_w": right_plate_rect.w,
                "right_plate_h": right_plate_rect.h,
                "hit_margin_px": hit_margin_px,
                "event": event_name,
                "iti_ms": iti_ms,
                "outside_in_trial": outside_touches_in_trial,
                "max_outside_before_fail": max_outside_before_fail,
                "correction_mode": 1 if correction_mode_enabled else 0,
                "is_correction_trial": 1 if current_trial_is_correction else 0,
                "seed": args.seed,
                "schedule_hash": schedule_hash,
            })

            if current_context is not None:
                info = current_context["info"]
                cur_pair = current_context["pair"]
                high_label = info["high_label"]
                target_image = cur_pair.r_path.name if high_label == "r" else cur_pair.nr_path.name
                non_target_image = cur_pair.nr_path.name if high_label == "r" else cur_pair.r_path.name
                row.update({
                    "stim_set": cur_pair.label,
                    "left_label": current_context["left_label"],
                    "right_label": current_context["right_label"],
                    "left_image": current_context["left_image"],
                    "right_image": current_context["right_image"],
                    "target_image": target_image,
                    "non_target_image": non_target_image,
                    "trial_index_global": current_context["global_trial"],
                    "trial_index_in_set": info["trial_in_block"],
                    "block_index": info["block_index"],
                    "trial_in_block": info["trial_in_block"],
                    "scheduled_reversal_trial": info["scheduled_reversal_trial"],
                    "is_post_reversal": info["is_post_reversal"],
                    "high_label": high_label,
                    "p_high": info["p_high"],
                    "p_low": info["p_low"],
                })

            if extra is not None:
                row.update(extra)

            csv_w.writerow(_complete_csv_row(row))
            write_count += 1
            if write_count % 64 == 0:
                csv_f.flush()

        def draw(stim_on: bool):
            screen.fill(args.bg_rgb)
            if stim_on:
                pygame.draw.rect(screen, args.plate_rgb, left_plate_rect)
                pygame.draw.rect(screen, args.plate_rgb, right_plate_rect)
                if left_surf is not None:
                    screen.blit(left_surf, left_rect)
                if right_surf is not None:
                    screen.blit(right_surf, right_rect)
                if args.show_box:
                    pygame.draw.rect(screen, (120, 120, 120), left_plate_rect, 2)
                    pygame.draw.rect(screen, (120, 120, 120), right_plate_rect, 2)
                    pygame.draw.rect(screen, (200, 200, 200), left_rect, 1)
                    pygame.draw.rect(screen, (200, 200, 200), right_rect, 1)

            if args.info:
                high_label = ""
                block_index = ""
                trial_in_block = ""
                if current_context is not None:
                    info = current_context["info"]
                    high_label = info["high_label"]
                    block_index = info["block_index"]
                    trial_in_block = info["trial_in_block"]
                txt1 = (
                    f"State={STATE_NAMES[state]}  "
                    f"Trial={schedule_trial_index}/{total_trials}  "
                    f"Block={block_index}  InBlock={trial_in_block}  "
                    f"High={high_label}  "
                    f"Choices={choices}  Correct={correct_choices}  Incorrect={incorrect_choices}  "
                    f"Rewards={reward_count}  Outside={outside_touches_in_trial}/{max_outside_before_fail}  "
                    f"Corr={'ON' if current_trial_is_correction else 'OFF'}  "
                    f"HIT=plate(+margin {hit_margin_px}px)"
                )
                screen.blit(font.render(txt1, True, (220, 220, 220)), (20, 20))
            pygame.display.flip()

        def place_new_trial():
            
            nonlocal left_is_r, left_surf, right_surf
            nonlocal left_rect, right_rect, left_plate_rect, right_plate_rect
            nonlocal current_context, current_trial_is_correction

            if schedule_trial_index >= total_trials:
                return False

            info = dict(sched.lookup(schedule_trial_index))
            
            reverse_high = (
            args.reverse_high_with_block
            and (info["block_index"] % 2 == 1)
            )

            if reverse_high:
                info["high_label"] = (
                "nr" if info["high_label"] == "r" else "r"
            )
            
            cur_pair = pair_for_block(info["block_index"])
            current_trial_is_correction = correction_mode_enabled and correction_active

            if current_trial_is_correction and correction_left_is_r is not None:
                left_is_r = bool(correction_left_is_r)
            else:
                left_is_r = bool(layout_rng.getrandbits(1))

            left_surf = cur_pair.r_surf if left_is_r else cur_pair.nr_surf
            right_surf = cur_pair.nr_surf if left_is_r else cur_pair.r_surf
            left_rect, right_rect, left_plate_rect, right_plate_rect = compute_rects()

            current_context = {
                "global_trial": schedule_trial_index,
                "info": info,
                "pair": cur_pair,
                "reverse_high": reverse_high,
                "left_label": "r" if left_is_r else "nr",
                "right_label": "nr" if left_is_r else "r",
                "left_image": cur_pair.r_path.name if left_is_r else cur_pair.nr_path.name,
                "right_image": cur_pair.nr_path.name if left_is_r else cur_pair.r_path.name,
            }

            append_log("TRIAL_PLACED", -1, -1, 0)
            return True

        def advance_after_trial(was_correct: bool):
            nonlocal schedule_trial_index
            counts = True
            if correction_mode_enabled and (not was_correct) and (not args.correction_counts_toward_schedule):
                counts = False
            if counts:
                schedule_trial_index += 1

        def stop_limits_reached() -> bool:
            if schedule_trial_index >= total_trials:
                return True
            if args.max_rewards is not None and reward_count >= max(0, int(args.max_rewards)):
                return True
            if args.max_session_min is not None:
                elapsed_min = (time.perf_counter() - t0) / 60.0
                if elapsed_min >= float(args.max_session_min):
                    return True
            return False

        if not place_new_trial():
            print("[INFO] No trials to run")
            return
        draw(stim_on=True)

        running = True
        iti_end_time = 0.0
        stop_file = Path("STOP")

        while running:
            if stop_file.exists():
                print("[INFO] STOP file detected. Exiting...")
                running = False
                break

            if stop_limits_reached():
                running = False
                break

            for ev in pygame.event.get([pygame.QUIT, pygame.KEYDOWN, pygame.KEYUP]):
                if ev.type == pygame.QUIT:
                    running = False
                    break
                if ev.type in (pygame.KEYDOWN, pygame.KEYUP):
                    if ev.key in (pygame.K_ESCAPE, pygame.K_q):
                        running = False
                        break
            if not running:
                break

            pygame.event.pump()
            keys = pygame.key.get_pressed()
            if keys[pygame.K_ESCAPE] or keys[pygame.K_q]:
                running = False
                break

            want = [pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP]
            if FINGERDOWN is not None:
                want.append(FINGERDOWN)
            if FINGERUP is not None:
                want.append(FINGERUP)

            for ev in pygame.event.get(want):
                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    mouse_down = True
                elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                    mouse_down = False
                elif FINGERDOWN is not None and ev.type == FINGERDOWN:
                    active_fingers.add(ev.finger_id)
                elif FINGERUP is not None and ev.type == FINGERUP:
                    active_fingers.discard(ev.finger_id)

                is_down = (ev.type == pygame.MOUSEBUTTONDOWN) or (FINGERDOWN is not None and ev.type == FINGERDOWN)

                if state == STATE_SHOW:
                    if is_down:
                        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button != 1:
                            continue
                        x, y = get_xy(ev, sw, sh)

                        left_hit = left_plate_rect.inflate(2 * hit_margin_px, 2 * hit_margin_px).collidepoint((x, y))
                        right_hit = right_plate_rect.inflate(2 * hit_margin_px, 2 * hit_margin_px).collidepoint((x, y))

                        if left_hit or right_hit:
                            touched_side = "left" if left_hit else "right"
                            if touched_side == "left":
                                hit_area = "left_core" if left_plate_rect.collidepoint((x, y)) else "left_margin"
                                chosen_label = "r" if left_is_r else "nr"
                            else:
                                hit_area = "right_core" if right_plate_rect.collidepoint((x, y)) else "right_margin"
                                chosen_label = "nr" if left_is_r else "r"

                            result = resolve_trial(
                                sched,
                                current_context["global_trial"],
                                chosen_label,
                                reward_rng,
                                reverse_high=current_context["reverse_high"],
                            )
                            reward_won = bool(result["reward_won"])
                            reward_delivered = 0
                            ttl_ok = True

                            if reward_won:
                                screen.fill((0,0,0))
                                pygame.display.flip()
                                ttl_ok, _beep_ok = deliver_reward(ttl, beep, pulsecount=args.pulsecount)
                                reward_delivered = 1 if ttl_ok else 0

                            iti_kind = "rewarded" if reward_won else "unrewarded"
                            iti_ms = sample_iti(iti_kind)
                            event_name = f"TOUCH_{chosen_label.upper()}_{iti_kind.upper()}"
                            if reward_won and not ttl_ok:
                                event_name += "_TTL_FAIL"

                            choices += 1
                            if result["is_correct"]:
                                correct_choices += 1
                                if correction_mode_enabled and correction_active:
                                    correction_active = False
                                    correction_left_is_r = None
                            else:
                                incorrect_choices += 1
                                if correction_mode_enabled:
                                    correction_active = True
                                    correction_left_is_r = left_is_r

                            if reward_delivered:
                                reward_count += 1

                            extra = dict(result)
                            extra.update({
                                "hit_area": hit_area,
                                "iti_kind": iti_kind,
                                "trial_outcome": "correct" if result["is_correct"] else "incorrect",
                                "reward_delivered": reward_delivered,
                            })
                            append_log(event_name, x, y, iti_ms, extra=extra)

                            advance_after_trial(bool(result["is_correct"]))

                            state = STATE_ITI
                            touch_during_iti = mouse_down or bool(active_fingers)
                            iti_end_time = time.perf_counter() + iti_ms / 1000.0
                            draw(stim_on=False)

                        else:
                            outside_touches_in_trial += 1
                            append_log("TOUCH_OUTSIDE", x, y, 0, extra={"hit_area": "outside"})
                            if outside_touches_in_trial >= max_outside_before_fail:
                                outside_failures += 1
                                if correction_mode_enabled:
                                    correction_active = True
                                    correction_left_is_r = left_is_r

                                iti_ms = sample_iti("outside")
                                append_log(
                                    "FAIL_OUTSIDE_LIMIT",
                                    x,
                                    y,
                                    iti_ms,
                                    extra={
                                        "hit_area": "outside",
                                        "iti_kind": "outside",
                                        "trial_outcome": "outside",
                                        "fail_reason": "outside_limit",
                                        "is_correct": 0,
                                        "reward_won": 0,
                                        "reward_delivered": 0,
                                    },
                                )

                                advance_after_trial(False)

                                state = STATE_ITI
                                touch_during_iti = mouse_down or bool(active_fingers)
                                iti_end_time = time.perf_counter() + iti_ms / 1000.0
                                draw(stim_on=False)

                elif state == STATE_ITI:
                    if is_down:
                        if ev.type == pygame.MOUSEBUTTONDOWN and ev.button != 1:
                            continue
                        touch_during_iti = True
                        x, y = get_xy(ev, sw, sh)
                        if left_plate_rect.inflate(2 * hit_margin_px, 2 * hit_margin_px).collidepoint((x, y)):
                            hit_area = "left_core" if left_plate_rect.collidepoint((x, y)) else "left_margin"
                            append_log("TOUCH_ITI_LEFT", x, y, 0, extra={"hit_area": hit_area})
                        elif right_plate_rect.inflate(2 * hit_margin_px, 2 * hit_margin_px).collidepoint((x, y)):
                            hit_area = "right_core" if right_plate_rect.collidepoint((x, y)) else "right_margin"
                            append_log("TOUCH_ITI_RIGHT", x, y, 0, extra={"hit_area": hit_area})
                        else:
                            append_log("TOUCH_ITI_OUTSIDE", x, y, 0, extra={"hit_area": "outside"})
                        draw(stim_on=False)

                elif state == STATE_WAIT_RELEASE:
                    pass

            if not running:
                break

            now = time.perf_counter()

            if state == STATE_ITI:
                if now >= iti_end_time:
                    state = STATE_WAIT_RELEASE
                    wait_release_enter_t = now
                    release_clear_start_t = None
                    require_release_dwell = touch_during_iti and (min_release_after_iti_touch_s > 0)
                    if require_release_dwell:
                        append_log("RELEASE_DWELL_WILL_REQUIRE", -1, -1, 0)

            if state == STATE_WAIT_RELEASE:
                no_touch_now = (not mouse_down and not active_fingers)

                if require_release_dwell:
                    if no_touch_now:
                        if release_clear_start_t is None:
                            release_clear_start_t = now
                            append_log("RELEASE_DWELL_START", -1, -1, 0)
                        else:
                            elapsed = now - release_clear_start_t
                            if elapsed >= min_release_after_iti_touch_s:
                                append_log("RELEASE_DWELL_OK", -1, -1, 0)
                                state = STATE_SHOW
                                require_release_dwell = False
                                touch_during_iti = False
                                outside_touches_in_trial = 0
                                if stop_limits_reached() or not place_new_trial():
                                    running = False
                                else:
                                    draw(stim_on=True)
                    else:
                        if release_clear_start_t is not None:
                            append_log("RELEASE_DWELL_RESET", -1, -1, 0)
                        release_clear_start_t = None
                else:
                    if no_touch_now:
                        state = STATE_SHOW
                        touch_during_iti = False
                        outside_touches_in_trial = 0
                        if stop_limits_reached() or not place_new_trial():
                            running = False
                        else:
                            draw(stim_on=True)

                if wait_release_enter_t is not None and (now - wait_release_enter_t) >= wait_release_timeout:
                    if mouse_down or active_fingers:
                        active_fingers.clear()
                        mouse_down = False
                        if require_release_dwell and release_clear_start_t is None:
                            release_clear_start_t = now
                            append_log("RELEASE_DWELL_START_FORCED", -1, -1, 0)
                        elif not require_release_dwell:
                            state = STATE_SHOW
                            touch_during_iti = False
                            outside_touches_in_trial = 0
                            if stop_limits_reached() or not place_new_trial():
                                running = False
                            else:
                                draw(stim_on=True)

            clock.tick(240)

        if csv_f is not None:
            csv_f.flush()
        print(
            f"[INFO] Saved CSV: {out_path}; choices={choices}; correct={correct_choices}; "
            f"incorrect={incorrect_choices}; outside_failures={outside_failures}; rewards={reward_count}"
        )

    finally:
        try:
            pygame.quit()
        except Exception:
            pass
        if ttl is not None:
            ttl.close()
        if csv_f is not None:
            try:
                csv_f.close()
            except Exception:
                pass


def parse_args(argv: Optional[List[str]] = None):
    p = argparse.ArgumentParser(description="Trial-count-based probabilistic reversal learning task")

    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--schedule-json", type=str, default=None)
    p.add_argument("--save-schedule-json", type=str, default=None)
    p.add_argument("--n-blocks", type=int, default=6)
    p.add_argument("--block-len-trials", type=int, default=80)
    p.add_argument("--reversal-min-trial", type=int, default=30)
    p.add_argument("--reversal-max-trial", type=int, default=50)
    p.add_argument("--schedule-set", choices=["80-20", "70-30", "60-40", "mixed"], default="80-20")
    p.add_argument("--initial-high-label", choices=["r", "nr", "random"], default="r")

    p.add_argument("--fullscreen", action="store_true")
    p.add_argument("--window-w", type=int, default=1280)
    p.add_argument("--window-h", type=int, default=720)
    p.add_argument("--kiosk", action="store_true", help="fullscreen, hidden cursor, input grab")
    p.add_argument("--touch-only", action="store_true", help="block mouse input and accept touch input only")

    p.add_argument("--stim-dir", type=str, default="stim", help="directory containing stim_XX_r.png and stim_XX_nr.png")
    p.add_argument("--stim-px", type=int, default=None)
    p.add_argument("--stim-w", type=int, default=None)
    p.add_argument("--stim-h", type=int, default=None)
    p.add_argument("--stim-per-block", choices=["cycle", "fixed"], default="cycle")

    p.add_argument("--plate-px", type=int, default=None)
    p.add_argument("--plate-w", type=int, default=None)
    p.add_argument("--plate-h", type=int, default=None)
    p.add_argument("--plate-rgb", type=int, nargs=3, default=(150, 150, 150))
    p.add_argument("--center-offset-px", type=int, default=300)
    p.add_argument("--edge-margin-px", type=int, default=16)
    p.add_argument("--bg-rgb", type=int, nargs=3, default=(0, 0, 0))

    p.add_argument("--serial-port", type=str, default=None)
    p.add_argument("--serial-baud", type=int, default=115200)
    p.add_argument("--dry-run-ttl", action="store_true")

    p.add_argument("--iti-min-ms", type=int, default=1000)
    p.add_argument("--iti-max-ms", type=int, default=1000)
    p.add_argument("--iti-rewarded-min-ms", type=int, default=None)
    p.add_argument("--iti-rewarded-max-ms", type=int, default=None)
    p.add_argument("--iti-unrewarded-min-ms", type=int, default=None)
    p.add_argument("--iti-unrewarded-max-ms", type=int, default=None)
    p.add_argument("--iti-outside-min-ms", type=int, default=None)
    p.add_argument("--iti-outside-max-ms", type=int, default=None)

    p.add_argument("--beep-freq", type=int, default=1000)
    p.add_argument("--beep-ms", type=int, default=100)
    p.add_argument("--beep-volume", type=float, default=0.6)

    p.add_argument("--wait-release-timeout-ms", type=int, default=2000)
    p.add_argument("--min-release-ms-after-iti-touch", type=int, default=2000)
    p.add_argument("--max-outside-before-fail", type=int, default=5)
    p.add_argument("--hit-margin-px", type=int, default=0)

    # In PRL, correction repeats errors and EXPOSES the hidden label.
    p.add_argument("--correction-mode", action="store_true", default=False)
    p.add_argument("--correction-counts-toward-schedule", action="store_true", default=False)

    p.add_argument("--sim", action="store_true")
    p.add_argument("--sim-choices", choices=["high", "low", "random", "alternate"], default="random")

    p.add_argument("--max-trials", type=int, default=None)
    p.add_argument("--max-rewards", type=int, default=None)
    p.add_argument("--max-session-min", type=float, default=None)

    p.add_argument("--out-dir", type=str, default="logs")
    p.add_argument("--show-box", action="store_true")
    p.add_argument("--info", action="store_true")
    p.add_argument("--pulsecount", type=int, default=1)
    p.add_argument("--sth", type=float,default=0)
    
    p.add_argument("--reverse-high-with-block", action="store_true", default=False, help="Reverse which image is HIGH whenever a new block starts.")



    return p.parse_args(argv)


def main() -> None:
    args = parse_args()

    if not args.sim and args.stim_px is None:
        if args.stim_w is None and args.stim_h is None:
            args.stim_px = 240
        elif args.stim_w is None or args.stim_h is None:
            print("[ERROR] specify --stim-px, or both --stim-w and --stim-h", file=sys.stderr)
            sys.exit(1)

    if (args.plate_w is None) != (args.plate_h is None):
        print("[ERROR] specify both --plate-w and --plate-h, or neither", file=sys.stderr)
        sys.exit(1)

    if args.sim:
        run_sim(args)
    else:
        run(args)


if __name__ == "__main__":
    main()
