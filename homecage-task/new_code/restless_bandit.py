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
from schedules import BanditWalk, validate_bandit_walk
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
    "seed", "walk_hash", "n_trials",
    "trial_index", "p_left", "p_right", "chosen_side", "p_chosen",
    "chose_higher_p", "reward_draw", "reward_won", "reward_delivered",
    "step_prob", "step_size", "p_floor", "p_ceil", "balance_tol",
    "double_low_thresh", "double_low_max_run", "boundary_mode", "balance_metric",
]


class StimSet:
    def __init__(self, idx_num: int, r_path: Path):
        self.idx_num = idx_num
        self.r_path = r_path
        self.r_surf = None

def find_stim_sets(stim_dir: Path) -> List[StimSet]:
    rx_r = re.compile(r"^stim_(\d+)_r\.png$", re.IGNORECASE)
    sets = []
    for p in stim_dir.glob("*.png"):
        m = rx_r.match(p.name)
        if m:
            sets.append(StimSet(int(m.group(1)), p))
    return sorted(sets, key=lambda s: s.idx_num)


def load_or_generate_walk(args):
    if args.walk_json:
        walk = BanditWalk.from_json(args.walk_json)
    else:
        walk = BanditWalk.generate(
            seed=args.seed,
            n_trials=args.n_trials,
            step_prob=args.step_prob_frac,
            step_size=args.step_size_frac,
            p_init_left=args.p_init_left_frac,
            p_init_right=args.p_init_right_frac,
            p_floor=args.p_floor_frac,
            p_ceil=args.p_ceil_frac,
            balance_tol=args.balance_tol_frac,
            double_low_thresh=args.double_low_thresh_frac,
            double_low_max_run=args.double_low_max_run,
            boundary_mode=args.boundary_mode,
            max_attempts=args.max_walk_generation_attempts,
        )

    validate_bandit_walk(walk)

    if args.save_walk_json:
        walk.to_json(args.save_walk_json)

    return walk


def resolve_trial(walk, trial: int, chosen_side: str, reward_rng) -> Dict:
    if chosen_side not in ("left", "right"):
        raise ValueError("chosen_side must be 'left' or 'right'")

    p_left, p_right = walk.p_at(trial)
    p_chosen = p_left if chosen_side == "left" else p_right

    if p_left == p_right:
        chose_higher_p = ""
    else:
        higher_side = "left" if p_left > p_right else "right"
        chose_higher_p = 1 if chosen_side == higher_side else 0

    u, won = task_common.sample_reward(reward_rng, p_chosen)

    return {
        "trial_index": trial,
        "p_left": p_left,
        "p_right": p_right,
        "chosen_side": chosen_side,
        "p_chosen": p_chosen,
        "chose_higher_p": chose_higher_p,
        "reward_draw": u,
        "reward_won": 1 if won else 0,
    }


def _walk_params_row(walk) -> Dict:
    meta = walk.meta if walk.meta is not None else {}
    return {
        "step_prob": walk.step_prob,
        "step_size": walk.step_size,
        "p_floor": walk.p_floor,
        "p_ceil": walk.p_ceil,
        "balance_tol": walk.balance_tol,
        "double_low_thresh": walk.double_low_thresh,
        "double_low_max_run": walk.double_low_max_run,
        "boundary_mode": walk.boundary_mode,
        "balance_metric": meta.get("balance_metric", ""),
    }


def simulate(walk, seed: int, sim_choices: str, n_trials: int) -> List[Dict]:
    if sim_choices not in ("higher", "lower", "left", "right", "random"):
        raise ValueError("sim_choices must be higher, lower, left, right, or random")

    reward_rng = derive_rng(seed, "reward")
    sim_rng = derive_rng(seed, "sim")
    walk_hash = walk.walk_hash()
    walk_params = _walk_params_row(walk)

    rows = []
    for t in range(n_trials):
        p_left, p_right = walk.p_at(t)
        if sim_choices == "left":
            side = "left"
        elif sim_choices == "right":
            side = "right"
        elif sim_choices == "higher":
            side = "left" if p_left >= p_right else "right"
        elif sim_choices == "lower":
            side = "left" if p_left <= p_right else "right"
        else:
            side = "left" if sim_rng.random() < 0.5 else "right"

        r = resolve_trial(walk, t, side, reward_rng)
        r["start_iso"] = ""
        r["iso"] = ""
        r["rel_s"] = ""
        r["seed"] = seed
        r["walk_hash"] = walk_hash
        r["n_trials"] = n_trials
        r["reward_delivered"] = 1 if r["reward_won"] else 0
        r["iti_kind"] = "rewarded" if r["reward_won"] else "unrewarded"
        r["state"] = "SIM"
        r["event"] = "SIM_CHOICE"
        r["trial_outcome"] = "choice"
        r.update(walk_params)
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
        filename = f"restless_bandit_sim_log_{stamp}.csv"
    return write_rows_csv(rows, out_dir_path / filename)


def _bounded_range(min_ms: Optional[int], max_ms: Optional[int], base_min: int, base_max: int) -> Tuple[int, int]:
    return ttr.bounded_range(min_ms, max_ms, base_min, base_max)


def _truncate_at_max_rewards(rows: List[Dict], max_rewards: Optional[int]) -> List[Dict]:
    return ttr.truncate_at_max_rewards(rows, max_rewards)


def run_sim(args) -> Path:
    walk = load_or_generate_walk(args)
    total_trials = int(walk.n_trials)
    if args.max_trials is not None:
        total_trials = min(total_trials, max(0, int(args.max_trials)))

    rows = simulate(walk, args.seed, args.sim_choices, total_trials)
    rows = _truncate_at_max_rewards(rows, args.max_rewards)
    out_path = write_simulation_csv(rows, args.out_dir)

    rewards = sum(1 for r in rows if r["reward_delivered"])
    print(
        f"[INFO] Simulated {len(rows)} trials; rewards={rewards}; "
        f"walk_hash={walk.walk_hash()}; CSV={out_path}"
    )
    return out_path


def run(args):
    import pygame

    walk = load_or_generate_walk(args)
    walk_hash = walk.walk_hash()
    walk_params = _walk_params_row(walk)
    total_trials = int(walk.n_trials)
    if args.max_trials is not None:
        total_trials = min(total_trials, max(0, int(args.max_trials)))

    reward_rng = derive_rng(args.seed, "reward")
    iti_rng = derive_rng(args.seed, "iti")

    ttl = None
    csv_f = None

    try:
        session = ttr.init_two_choice_session(
            window_title="Restless spatial bandit",
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

        square_w = square_h = max(1, int(args.square_px))

        if args.plate_px is not None:
            plate_w = plate_h = max(square_w, square_h, int(args.plate_px))
        elif args.plate_w is not None and args.plate_h is not None:
            plate_w = max(square_w, int(args.plate_w))
            plate_h = max(square_h, int(args.plate_h))
        else:
            plate_w, plate_h = square_w, square_h

        edge_margin = max(0, int(args.edge_margin_px))
        rect_specs, center_offset = ttr.compute_two_choice_rects(
            sw,
            sh,
            square_w,
            square_h,
            plate_w,
            plate_h,
            int(args.center_offset_px),
            edge_margin,
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

        stim_sets: List[StimSet] = []
        if args.images:
            if not args.stim_dir:
                raise RuntimeError("--stim-dir is required when --images is used")
            stim_dir = Path(args.stim_dir)
            if not stim_dir.exists():
                raise RuntimeError(f"stimulus directory not found: {stim_dir}")
            stim_sets = find_stim_sets(stim_dir)
            if not stim_sets:
                raise RuntimeError(f"{stim_dir} does not contain stim_XX_r.png images")

            for ss in stim_sets:
                img = pygame.image.load(str(ss.r_path)).convert_alpha()
                if img.get_width() != square_w or img.get_height() != square_h:
                    img = pygame.transform.smoothscale(img, (square_w, square_h))
                ss.r_surf = img

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
        out_path = out_dir / f"restless_bandit_log_{start_dt.strftime('%Y%m%d_%H%M%S')}.csv"

        csv_f = out_path.open("w", newline="", encoding="utf-8")
        csv_w = csv.DictWriter(csv_f, fieldnames=CSV_FIELDNAMES)
        csv_w.writeheader()
        write_count = 0

        t0 = time.perf_counter()
        choices = 0
        reward_count = 0
        outside_failures = 0
        trial_index = 0

        left_rect, right_rect, left_plate_rect, right_plate_rect = compute_rects()
        left_surf = None
        right_surf = None
        current_context = None

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
                "seed": args.seed,
                "walk_hash": walk_hash,
                "n_trials": total_trials,
            })
            row.update(walk_params)

            if current_context is not None:
                row.update({
                    "trial_index": current_context["trial_index"],
                    "p_left": current_context["p_left"],
                    "p_right": current_context["p_right"],
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

                if args.images and left_surf is not None:
                    screen.blit(left_surf, left_rect)
                else:
                    pygame.draw.rect(screen, args.square_rgb, left_rect)

                if args.images and right_surf is not None:
                    screen.blit(right_surf, right_rect)
                else:
                    pygame.draw.rect(screen, args.square_rgb, right_rect)

                if args.show_box:
                    pygame.draw.rect(screen, (120, 120, 120), left_plate_rect, 2)
                    pygame.draw.rect(screen, (120, 120, 120), right_plate_rect, 2)
                    pygame.draw.rect(screen, (200, 200, 200), left_rect, 1)
                    pygame.draw.rect(screen, (200, 200, 200), right_rect, 1)

            if args.info:
                p_left = ""
                p_right = ""
                if current_context is not None:
                    p_left = current_context["p_left"]
                    p_right = current_context["p_right"]
                txt1 = (
                    f"State={STATE_NAMES[state]}  "
                    f"Trial={trial_index}/{total_trials}  "
                    f"pL={p_left}  pR={p_right}  "
                    f"Choices={choices}  Rewards={reward_count}  "
                    f"Outside={outside_touches_in_trial}/{max_outside_before_fail}  "
                    f"HIT=plate(+margin {hit_margin_px}px)"
                )
                screen.blit(font.render(txt1, True, (220, 220, 220)), (20, 20))
            pygame.display.flip()

        def place_new_trial():
            nonlocal left_surf, right_surf
            nonlocal left_rect, right_rect, left_plate_rect, right_plate_rect
            nonlocal current_context

            if trial_index >= total_trials:
                return False

            p_left, p_right = walk.p_at(trial_index)
            left_rect, right_rect, left_plate_rect, right_plate_rect = compute_rects()

            # TODO: Future identity-binding can map image identity to reward probabilities.
            # This version keeps probabilities bound to left/right spatial location.
            if args.images and stim_sets:
                stim = stim_sets[trial_index % len(stim_sets)]
                left_surf = stim.r_surf
                right_surf = stim.r_surf
            else:
                left_surf = None
                right_surf = None

            current_context = {
                "trial_index": trial_index,
                "p_left": p_left,
                "p_right": p_right,
            }

            append_log("TRIAL_PLACED", -1, -1, 0)
            return True

        def stop_limits_reached() -> bool:
            if trial_index >= total_trials:
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
                            else:
                                hit_area = "right_core" if right_plate_rect.collidepoint((x, y)) else "right_margin"

                            result = resolve_trial(walk, trial_index, touched_side, reward_rng)
                            reward_won = bool(result["reward_won"])
                            reward_delivered = 0
                            ttl_ok = True

                            if reward_won:
                                ttl_ok, _beep_ok = deliver_reward(ttl, beep)
                                reward_delivered = 1 if ttl_ok else 0

                            iti_kind = "rewarded" if reward_won else "unrewarded"
                            iti_ms = sample_iti(iti_kind)
                            event_name = f"TOUCH_{touched_side.upper()}_{iti_kind.upper()}"
                            if reward_won and not ttl_ok:
                                event_name += "_TTL_FAIL"

                            choices += 1
                            if reward_delivered:
                                reward_count += 1

                            extra = dict(result)
                            extra.update({
                                "hit_area": hit_area,
                                "iti_kind": iti_kind,
                                "trial_outcome": "choice",
                                "reward_delivered": reward_delivered,
                            })
                            append_log(event_name, x, y, iti_ms, extra=extra)

                            trial_index += 1
                            state = STATE_ITI
                            touch_during_iti = mouse_down or bool(active_fingers)
                            iti_end_time = time.perf_counter() + iti_ms / 1000.0
                            draw(stim_on=False)

                        else:
                            outside_touches_in_trial += 1
                            append_log("TOUCH_OUTSIDE", x, y, 0, extra={"hit_area": "outside"})
                            if outside_touches_in_trial >= max_outside_before_fail:
                                outside_failures += 1
                                p_left, p_right = walk.p_at(trial_index)
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
                                        "trial_index": trial_index,
                                        "p_left": p_left,
                                        "p_right": p_right,
                                        "reward_won": 0,
                                        "reward_delivered": 0,
                                    },
                                )

                                trial_index += 1
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
            f"[INFO] Saved CSV: {out_path}; choices={choices}; "
            f"outside_failures={outside_failures}; rewards={reward_count}"
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
    p = argparse.ArgumentParser(description="Restless two-armed spatial bandit task")

    p.add_argument("--seed", type=int, required=True)
    p.add_argument("--walk-json", type=str, default=None)
    p.add_argument("--save-walk-json", type=str, default=None)
    p.add_argument("--n-trials", type=int, default=300)

    p.add_argument("--step-prob-frac", type=float, default=0.10)
    p.add_argument("--step-size-frac", type=float, default=0.10)
    p.add_argument("--p-init-left-frac", type=float, default=0.50)
    p.add_argument("--p-init-right-frac", type=float, default=0.50)
    p.add_argument("--p-floor-frac", type=float, default=0.10)
    p.add_argument("--p-ceil-frac", type=float, default=0.90)
    p.add_argument("--balance-tol-frac", type=float, default=0.02)
    p.add_argument("--double-low-thresh-frac", type=float, default=0.20)
    p.add_argument("--double-low-max-run", type=int, default=29)
    p.add_argument("--boundary-mode", choices=["reject-step", "reflect", "reject-walk"], default="reject-step")
    p.add_argument("--max-walk-generation-attempts", type=int, default=10000)

    p.add_argument("--fullscreen", action="store_true")
    p.add_argument("--window-w", type=int, default=1280)
    p.add_argument("--window-h", type=int, default=720)
    p.add_argument("--kiosk", action="store_true", help="fullscreen, hidden cursor, input grab")
    p.add_argument("--touch-only", action="store_true", help="block mouse input and accept touch input only")

    p.add_argument("--images", action="store_true", default=False)
    p.add_argument("--stim-dir", type=str, default=None)
    p.add_argument("--square-px", type=int, default=240)
    p.add_argument("--square-rgb", type=int, nargs=3, default=(255, 255, 255))

    p.add_argument("--plate-px", type=int, default=None)
    p.add_argument("--plate-w", type=int, default=None)
    p.add_argument("--plate-h", type=int, default=None)
    p.add_argument("--plate-rgb", type=int, nargs=3, default=(96, 96, 96))
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

    p.add_argument("--sim", action="store_true")
    p.add_argument("--sim-choices", choices=["higher", "lower", "left", "right", "random"], default="random")

    p.add_argument("--max-trials", type=int, default=None)
    p.add_argument("--max-rewards", type=int, default=None)
    p.add_argument("--max-session-min", type=float, default=None)

    p.add_argument("--out-dir", type=str, default="logs")
    p.add_argument("--show-box", action="store_true")
    p.add_argument("--info", action="store_true")

    return p.parse_args(argv)


def main() -> None:
    args = parse_args()

    if (args.plate_w is None) != (args.plate_h is None):
        print("[ERROR] specify both --plate-w and --plate-h, or neither", file=sys.stderr)
        sys.exit(1)

    if args.sim:
        run_sim(args)
    else:
        run(args)


if __name__ == "__main__":
    main()
