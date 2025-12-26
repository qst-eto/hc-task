# touch_rect_v5_random_fixed.py
import argparse, csv, sys, time, math, random, array
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
            raise RuntimeError("pyserial が未インストールです。`pip install pyserial`")
        try:
            self.ser = serial.Serial(port=port, baudrate=baud, timeout=0, write_timeout=0.2)
            time.sleep(0.05)
        except Exception as e:
            raise RuntimeError(f"シリアルポートを開けませんでした: {e}")

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
# Rect placement (random, fixed-size)
# =========================
def _place_square_random(sw: int, sh: int, side: int, fullscreen: bool, allow_auto_fullscreen: bool) -> pygame.Rect:
    """
    一辺 side の正方形をランダム配置する。
    - 左右は 0..(sw-side) の範囲でランダム
    - 上下はマージン m を取り、m = min(side/2, (sh - side)/2)
    - auto_fullscreen 条件成立時は全面矩形
    - はみ出し防止のため side を sw, sh にクランプ
    """
    side = max(1, int(side))
    short = min(sw, sh)

    if allow_auto_fullscreen and fullscreen and side >= short:
        return pygame.Rect(0, 0, sw, sh)

    side = min(side, sw, sh)

    x_min, x_max = 0, sw - side
    x = random.randint(x_min, x_max) if x_max >= x_min else 0

    desired_m = side // 2
    max_feasible_m = max(0, (sh - side) // 2)
    m = min(desired_m, max_feasible_m)

    y_min, y_max = m, sh - side - m
    y = random.randint(y_min, y_max) if y_max >= y_min else max(0, (sh - side) // 2)

    return pygame.Rect(x, y, side, side)


# =========================
# Main
# =========================
def run(args):
    pygame.init()
    # --- サウンドは環境によって失敗しうるため try でガード ---
    try:
        pygame.mixer.init(frequency=44100, size=-16, channels=1)
    except Exception as e:
        print(f"[WARN] mixer init failed: {e}", file=sys.stderr)

    # 画面消灯やスクリーンセーバでフォーカスを失わないように（対応環境のみ）
    try:
        pygame.display.set_allow_screensaver(False)
    except Exception:
        pass

    # ---- Pygame イベント種の存在を取得（環境依存対策）----
    FINGERDOWN   = getattr(pygame, "FINGERDOWN", None)
    FINGERUP     = getattr(pygame, "FINGERUP", None)
    FINGERMOTION = getattr(pygame, "FINGERMOTION", None)
    MOUSEWHEEL   = getattr(pygame, "MOUSEWHEEL", None)

    # ---- イベント衛生処理：使わないイベントはブロックしてキュー膨張を防ぐ ----
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
        pygame.display.set_caption("Touch Rectangle Training (Fixed Size, Random Position)")
        clock = pygame.time.Clock()
        font = pygame.font.SysFont(None, 28)
        sw, sh = screen.get_size()

        # ---- 固定サイズを一度だけ決定（以後不変） ----
        short = min(sw, sh)
        clamp_px = max(1, int(args.min_side_px)) if (args.min_side_px is not None) else 1

        # 誤綴り互換: sqaure_custom -> square_custom
        rect_mode = args.rect_mode if args.rect_mode != "sqaure_custom" else "square_custom"

        if rect_mode == "square_custom":
            if args.square_px is None:
                raise ValueError("--rect-mode square_custom では --square-px が必要です")
            fixed_side = max(clamp_px, int(args.square_px))
        else:
            # auto / square: 画面短辺 × initial_size_frac を固定サイズとする
            fixed_side = max(clamp_px, int(short * args.initial_size_frac))

        allow_auto_fs = args.auto_fullscreen_rect

        def cur_rect():
            # 固定サイズで毎試行ランダム配置
            return _place_square_random(sw, sh, fixed_side, args.fullscreen, allow_auto_fs)

        # ---- ITI 等の各種パラメータ ----
        base_min = max(0, int(args.iti_min_ms))
        base_max = max(base_min, int(args.iti_max_ms))
        iti_correct_min = int(args.iti_correct_min_ms) if args.iti_correct_min_ms is not None else base_min
        iti_correct_max = int(args.iti_correct_max_ms) if args.iti_correct_max_ms is not None else base_max
        iti_error_min   = int(args.iti_error_min_ms)   if args.iti_error_min_ms   is not None else base_min
        iti_error_max   = int(args.iti_error_max_ms)   if args.iti_error_max_ms   is not None else base_max

        iti_correct_min = max(0, iti_correct_min)
        iti_correct_max = max(iti_correct_min, iti_correct_max)
        iti_error_min   = max(0, iti_error_min)
        iti_error_max   = max(iti_error_min, iti_error_max)

        def sample_iti(kind: str) -> int:
            if kind == "correct":
                return random.randint(iti_correct_min, iti_correct_max)
            else:
                return random.randint(iti_error_min, iti_error_max)

        wait_release_timeout = max(0, int(args.wait_release_timeout_ms)) / 1000.0
        min_release_after_iti_touch_s = max(0, int(args.min_release_ms_after_iti_touch)) / 1000.0
        max_outside_before_fail = max(1, int(args.max_outside_before_fail))

        # ---- ヒット判定用マージン（px）----
        hit_margin_px = max(0, int(args.hit_margin_px))

        # ---- State ----
        STATE_SHOW, STATE_ITI, STATE_WAIT_RELEASE = 0, 1, 2
        state = STATE_SHOW
        mouse_down = False
        active_fingers = set()
        outside_touches_in_trial = 0

        touch_during_iti = False
        require_release_dwell = False
        release_clear_start_t = None
        wait_release_enter_t = None

        ttl = ArduinoTTLSender(args.serial_port, args.serial_baud)

        try:
            beep = make_beep_sound(args.beep_freq, args.beep_ms, args.beep_volume)
        except Exception as e:
            beep = None
            print(f"[WARN] beep disabled: {e}", file=sys.stderr)

        # ---- CSV：逐次書き出し（長時間運用向け）----
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        start_dt = datetime.now()
        start_iso = start_dt.isoformat(timespec="milliseconds")
        out_path = out_dir / f"touch_rect_log_{start_dt.strftime('%Y%m%d_%H%M%S')}.csv"

        fieldnames = [
            "start_iso","iso","rel_s","state",
            "x","y",                            # 実タッチ座標（非タッチ系は -1）
            "rect_x","rect_y","rect_w","rect_h",# 提示矩形の位置とサイズ
            "hit_margin_px","hit_area",         # マージン情報と当たり種別（core/margin/outside）
            "iti_ms","event",
            "outside_in_trial","max_outside_before_fail",
            "trial_outcome","iti_kind",
            "release_dwell_required_ms","release_dwell_elapsed_ms"
        ]
        csv_f = out_path.open("w", newline="", encoding="utf-8")
        csv_w = csv.DictWriter(csv_f, fieldnames=fieldnames)
        csv_w.writeheader()
        write_count = 0

        # t0 はログの相対時間計測用
        t0 = time.perf_counter()
        successes = 0
        failures = 0

        # append_log: すべての行に現在の矩形位置/サイズ・マージンを入れる
        def append_log(event_name, x, y, iti_ms, extra=None):
            nonlocal write_count
            nowp = time.perf_counter()
            rel = nowp - t0
            iso = datetime.now().isoformat(timespec="milliseconds")
            row = {
                "start_iso": start_iso,
                "iso": iso,
                "rel_s": f"{rel:.6f}",
                "state": ["SHOW", "ITI", "WAIT_RELEASE"][state],
                "x": x, "y": y,
                "rect_x": rect.x, "rect_y": rect.y, "rect_w": rect.w, "rect_h": rect.h,
                "hit_margin_px": hit_margin_px,
                "hit_area": "",  # 必要時に extra で上書き
                "iti_ms": iti_ms,
                "event": event_name,
                "outside_in_trial": outside_touches_in_trial,
                "max_outside_before_fail": max_outside_before_fail,
                "trial_outcome": "",
                "iti_kind": "",
                "release_dwell_required_ms": "",
                "release_dwell_elapsed_ms": ""
            }
            if extra is not None:
                row.update(extra)
            csv_w.writerow(row)
            write_count += 1
            # I/O flush を適度に（途中停止でもできるだけ残す）
            if write_count % 64 == 0:
                csv_f.flush()

        # 描画
        def draw(stim_on: bool):
            screen.fill(args.bg_rgb)
            if stim_on:
                pygame.draw.rect(screen, args.rect_rgb, rect)
                if args.show_box:
                    pygame.draw.rect(screen, (120, 120, 120), rect, 2)
            if args.info:
                txt1 = (f"State={['SHOW','ITI','WAIT_RELEASE'][state]}  "
                        f"Rect {rect.w}x{rect.h}@({rect.x},{rect.y})  "
                        f"margin={hit_margin_px}px  successes={successes}  failures={failures}  "
                        f"outside={outside_touches_in_trial}/{max_outside_before_fail}")
                screen.blit(font.render(txt1, True, (220, 220, 220)), (20, 20))
            pygame.display.flip()

        # 最初の矩形を提示してログ
        rect = cur_rect()
        append_log("RECT_PLACED", -1, -1, 0)
        draw(stim_on=True)

        running = True
        iti_end_time = 0.0
        stop_file = Path("STOP")

        # ------- Main loop -------
        while running:
            # 非常停止ファイル
            if stop_file.exists():
                print("[INFO] STOP file detected. Exiting...")
                running = False
                break

            # ---- 1) 終了系イベントを最優先で処理（巨大キューでも即反応）----
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

            # 念のためのフォールバック：キー状態のポーリング（イベント詰まり対策）
            pygame.event.pump()
            keys = pygame.key.get_pressed()
            if keys[pygame.K_ESCAPE] or keys[pygame.K_q]:
                running = False
                break

            # ---- 2) 必要な入力イベントだけ取得 ----
            want = [pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP]
            if FINGERDOWN is not None: want.append(FINGERDOWN)
            if FINGERUP   is not None: want.append(FINGERUP)

            for ev in pygame.event.get(want):
                # maintain contact sets
                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    mouse_down = True
                elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                    mouse_down = False
                elif FINGERDOWN is not None and ev.type == FINGERDOWN:
                    active_fingers.add(ev.finger_id)
                elif FINGERUP is not None and ev.type == FINGERUP:
                    active_fingers.discard(ev.finger_id)

                # 位置取得ヘルパ
                def _get_xy(e):
                    if e.type == pygame.MOUSEBUTTONDOWN:
                        if e.button != 1:
                            return None
                        return e.pos
                    elif FINGERDOWN is not None and e.type == FINGERDOWN:
                        return (int(e.x * sw), int(e.y * sh))
                    return None

                # ---- State machine ----
                if state == STATE_SHOW:
                    if (ev.type == pygame.MOUSEBUTTONDOWN) or (FINGERDOWN is not None and ev.type == FINGERDOWN):
                        xy = _get_xy(ev)
                        if xy is None:
                            continue
                        x, y = xy

                        # マージンを含めた当たり領域
                        hit_rect = rect.inflate(2*hit_margin_px, 2*hit_margin_px)
                        is_hit = hit_rect.collidepoint((x, y))
                        hit_area = "outside"
                        if is_hit:
                            hit_area = "core" if rect.collidepoint((x, y)) else "margin"

                        if is_hit:
                            # 成功（矩形本体 or マージン）
                            ok = True
                            try:
                                ttl.pulse()
                            except Exception as e:
                                print(f"[ERROR] TTL 失敗: {e}", file=sys.stderr)
                                ok = False
                            try:
                                if beep is not None:
                                    beep.play()
                            except Exception:
                                pass

                            iti_ms = sample_iti("correct")
                            append_log("TOUCH_TTL" if ok else "TOUCH_TTL_FAIL", x, y, iti_ms,
                                       extra={"hit_area": hit_area,
                                              "trial_outcome": "success",
                                              "iti_kind": "correct"})
                            if ok:
                                successes += 1

                            state = STATE_ITI
                            touch_during_iti = mouse_down or bool(active_fingers)
                            iti_end_time = time.perf_counter() + iti_ms / 1000.0
                            draw(stim_on=False)
                        else:
                            # 矩形外タッチ
                            outside_touches_in_trial += 1
                            append_log("TOUCH_OUTSIDE", x, y, 0, extra={"hit_area": "outside"})
                            if outside_touches_in_trial >= max_outside_before_fail:
                                failures += 1
                                iti_ms = sample_iti("error")
                                append_log("FAIL_OUTSIDE_LIMIT", x, y, iti_ms,
                                           extra={"hit_area": "outside",
                                                  "trial_outcome": "error",
                                                  "iti_kind": "error"})
                                state = STATE_ITI
                                touch_during_iti = mouse_down or bool(active_fingers)
                                iti_end_time = time.perf_counter() + iti_ms / 1000.0
                                draw(stim_on=False)

                elif state == STATE_ITI:
                    # ITI 中のタッチも記録
                    if (ev.type == pygame.MOUSEBUTTONDOWN) or (FINGERDOWN is not None and ev.type == FINGERDOWN):
                        touch_during_iti = True
                        xy = _get_xy(ev)
                        if xy is None:
                            continue
                        x, y = xy
                        hit_rect = rect.inflate(2*hit_margin_px, 2*hit_margin_px)
                        if hit_rect.collidepoint((x, y)):
                            hit_area = "core" if rect.collidepoint((x, y)) else "margin"
                            append_log("TOUCH_ITI_INSIDE", x, y, 0, extra={"hit_area": hit_area})
                        else:
                            append_log("TOUCH_ITI_OUTSIDE", x, y, 0, extra={"hit_area": "outside"})
                        draw(stim_on=False)

                elif state == STATE_WAIT_RELEASE:
                    # 離し判定は下の独立遷移で処理
                    pass

            if not running:
                break

            # ---- 3) イベントに依存しない状態遷移 ----
            now = time.perf_counter()

            if state == STATE_ITI:
                # ITI終了 → 離し待ちへ
                if now >= iti_end_time:
                    state = STATE_WAIT_RELEASE
                    wait_release_enter_t = now
                    release_clear_start_t = None
                    require_release_dwell = touch_during_iti and (min_release_after_iti_touch_s > 0)
                    if require_release_dwell:
                        append_log("RELEASE_DWELL_WILL_REQUIRE", -1, -1, 0,
                                   extra={"release_dwell_required_ms": int(min_release_after_iti_touch_s * 1000)})

            if state == STATE_WAIT_RELEASE:
                no_touch_now = (not mouse_down and not active_fingers)

                if require_release_dwell:
                    if no_touch_now:
                        if release_clear_start_t is None:
                            release_clear_start_t = now
                            append_log("RELEASE_DWELL_START", -1, -1, 0,
                                       extra={"release_dwell_required_ms": int(min_release_after_iti_touch_s * 1000)})
                        else:
                            elapsed = now - release_clear_start_t
                            if elapsed >= min_release_after_iti_touch_s:
                                append_log("RELEASE_DWELL_OK", -1, -1, 0,
                                           extra={"release_dwell_elapsed_ms": int(elapsed * 1000)})
                                state = STATE_SHOW
                                require_release_dwell = False
                                touch_during_iti = False
                                outside_touches_in_trial = 0
                                rect = cur_rect()  # 次試行のために新しいランダム位置を生成
                                append_log("RECT_PLACED", -1, -1, 0)
                                draw(stim_on=True)
                    else:
                        if release_clear_start_t is not None:
                            append_log("RELEASE_DWELL_RESET", -1, -1, 0,
                                       extra={"release_dwell_elapsed_ms": int((now - release_clear_start_t) * 1000)})
                        release_clear_start_t = None
                else:
                    if no_touch_now:
                        state = STATE_SHOW
                        touch_during_iti = False
                        outside_touches_in_trial = 0
                        rect = cur_rect()
                        append_log("RECT_PLACED", -1, -1, 0)
                        draw(stim_on=True)

                # タイムアウトで強制開放
                if wait_release_enter_t is not None and (now - wait_release_enter_t) >= wait_release_timeout:
                    if mouse_down or active_fingers:
                        active_fingers.clear()
                        mouse_down = False
                        if require_release_dwell and release_clear_start_t is None:
                            release_clear_start_t = now
                            append_log("RELEASE_DWELL_START_FORCED", -1, -1, 0,
                                       extra={"release_dwell_required_ms": int(min_release_after_iti_touch_s * 1000)})
                        elif not require_release_dwell:
                            state = STATE_SHOW
                            touch_during_iti = False
                            outside_touches_in_trial = 0
                            rect = cur_rect()
                            append_log("RECT_PLACED", -1, -1, 0)
                            draw(stim_on=True)

            clock.tick(240)

        # ループ終了
        if csv_f is not None:
            csv_f.flush()
        print(f"[INFO] Saved CSV: {out_path}")

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


def parse_args():
    p = argparse.ArgumentParser(description="Touchscreen rectangle training (fixed-size, random position, outside-fail rule)")
    # 画面
    p.add_argument("--fullscreen", action="store_true")
    p.add_argument("--window-w", type=int, default=1280)
    p.add_argument("--window-h", type=int, default=720)
    p.add_argument("--kiosk", action="store_true", help="フルスクリーン・カーソル非表示・入力グラブ")
    # 入力
    p.add_argument("--touch-only", action="store_true", help="タッチのみ許可（MOUSE系ブロック）")
    # 矩形（固定サイズ）
    p.add_argument("--rect-mode", choices=["auto","square","square_custom"], default="square_custom",
                   help="固定サイズは起動時に一度だけ決定。square_custom推奨（--square-px でpx指定）")
    p.add_argument("--square-px", type=int, default=240, help="--rect-mode square_custom の固定一辺(px)")
    p.add_argument("--initial-size-frac", type=float, default=0.3,
                   help="auto/square 用。画面短辺×この値で固定サイズ（起動時に決まって以後不変）")
    p.add_argument("--min-side-px", type=int, default=None, help="矩形の一辺の最小px（これ以下にならない）")
    p.add_argument("--auto-fullscreen-rect", action="store_true",
                   help="fixed_side>=short かつ fullscreen のときに矩形を全面化（この場合はランダム配置なし）")
    # 色
    p.add_argument("--rect-rgb", type=int, nargs=3, default=(0,160,255))
    p.add_argument("--bg-rgb", type=int, nargs=3, default=(0,0,0))
    # TTL
    p.add_argument("--serial-port", type=str, required=True)
    p.add_argument("--serial-baud", type=int, default=115200)
    # ITI（従来/分離）
    p.add_argument("--iti-min-ms", type=int, default=1000)
    p.add_argument("--iti-max-ms", type=int, default=1000)
    p.add_argument("--iti-correct-min-ms", type=int, default=None, help="未指定なら --iti-min-ms を使用")
    p.add_argument("--iti-correct-max-ms", type=int, default=None, help="未指定なら --iti-max-ms を使用")
    p.add_argument("--iti-error-min-ms",   type=int, default=None, help="未指定なら --iti-min-ms を使用")
    p.add_argument("--iti-error-max-ms",   type=int, default=None, help="未指定なら --iti-max-ms を使用")
    # ビープ
    p.add_argument("--beep-freq", type=int, default=1000)
    p.add_argument("--beep-ms", type=int, default=100)
    p.add_argument("--beep-volume", type=float, default=0.6)
    # 離し待ちフェイルセーフ
    p.add_argument("--wait-release-timeout-ms", type=int, default=2000,
                   help="WAIT_RELEASE でこの時間を超えたら強制的に次試行へ（取りこぼし対策）")
    # ITI中にタッチがあった場合に要求する連続解放時間
    p.add_argument("--min-release-ms-after-iti-touch", type=int, default=2000,
                   help="ITI中にタッチがあった場合、次の試行に進む前に必要な【連続】解放時間[ms]（0なら無効）")
    # 矩形外上限
    p.add_argument("--max-outside-before-fail", type=int, default=5,
                   help="SHOW状態での矩形外タッチ許容回数（到達で失敗→ITI）")
    # マージン（px）
    p.add_argument("--hit-margin-px", type=int, default=0,
                   help="矩形の外側に当たり判定マージン（px）。この範囲内のタッチも correct とする")
    # ログ/表示
    p.add_argument("--out-dir", type=str, default="logs")
    p.add_argument("--show-box", action="store_true")
    p.add_argument("--info", action="store_true")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    run(args)
