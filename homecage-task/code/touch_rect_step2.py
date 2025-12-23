# touch_rect_v4_outside_fail.py
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
# Rect layout
# =========================
def compute_rect(sw, sh, mode, size_frac, square_px, fullscreen, min_side_px, allow_auto_fullscreen):
    short = min(sw, sh)
    clamp_px = max(1, int(min_side_px)) if (min_side_px is not None) else 1

    if mode == "auto":
        side = max(clamp_px, int(short * size_frac))
        # 全面化は opt-in
        if allow_auto_fullscreen and fullscreen and side >= short:
            return pygame.Rect(0, 0, sw, sh)
        x = (sw - side) // 2
        y = (sh - side) // 2
        return pygame.Rect(x, y, side, side)

    if mode == "square_custom":
        if square_px is None:
            raise ValueError("--square-px が必要です")
        side = max(clamp_px, int(square_px))
        x = (sw - side) // 2
        y = (sh - side) // 2
        return pygame.Rect(x, y, side, side)

    # 'square'
    side = max(clamp_px, int(short * size_frac))
    x = (sw - side) // 2
    y = (sh - side) // 2
    return pygame.Rect(x, y, side, side)

# =========================
# Main
# =========================
def run(args):
    pygame.init()
    pygame.mixer.init(frequency=44100, size=-16, channels=1)

    # Kiosk / input policy
    if args.kiosk:
        args.fullscreen = True
        pygame.mouse.set_visible(False)
        pygame.event.set_grab(True)
    if args.touch_only:
        # タッチのみ許可：マウス系をブロック
        pygame.event.set_blocked(pygame.MOUSEBUTTONDOWN)
        pygame.event.set_blocked(pygame.MOUSEBUTTONUP)
        pygame.event.set_blocked(pygame.MOUSEMOTION)

    ttl = None
    try:
        flags = pygame.FULLSCREEN if args.fullscreen else pygame.NOFRAME
        screen = pygame.display.set_mode((0, 0) if args.fullscreen else (args.window_w, args.window_h), flags)
        pygame.display.set_caption("Touch Rectangle Training")
        clock = pygame.time.Clock()
        font = pygame.font.SysFont(None, 28)
        sw, sh = screen.get_size()

        # Params
        size_frac = args.initial_size_frac
        min_frac = args.min_size_frac
        shrink_every = args.shrink_every
        shrink_factor = args.shrink_factor
        mode = args.rect_mode
        square_px = args.square_px
        min_side_px = args.min_side_px
        allow_auto_fs = args.auto_fullscreen_rect

        iti_min = max(0, int(args.iti_min_ms))
        iti_max = max(iti_min, int(args.iti_max_ms))
        wait_release_timeout = max(0, int(args.wait_release_timeout_ms)) / 1000.0

        # New: 矩形外許容回数
        max_outside_before_fail = max(1, int(args.max_outside_before_fail))

        # State
        STATE_SHOW, STATE_ITI, STATE_WAIT_RELEASE = 0, 1, 2
        state = STATE_SHOW
        mouse_down = False
        active_fingers = set()
        outside_touches_in_trial = 0  # New: 試行内カウンタ

        #ttl = ArduinoTTLSender(args.serial_port, args.serial_baud)
        beep = make_beep_sound(args.beep_freq, args.beep_ms, args.beep_volume)

        logs = []
        t0 = time.perf_counter()
        start_iso = datetime.now().isoformat(timespec="milliseconds")
        successes = 0
        failures = 0  # 任意（統計用）

        def cur_rect():
            return compute_rect(sw, sh, mode, size_frac, square_px, args.fullscreen, min_side_px, allow_auto_fs)
        rect = cur_rect()

        if args.rect_mode == "sqaure_custom" and args.square_px is not None:
            side = int(args.square_px)
            rect = pygame.Rect((sw - side)//2, (sh - side)//2, side, side)

        def draw(stim_on: bool):
            screen.fill(args.bg_rgb)
            if stim_on:
                pygame.draw.rect(screen, args.rect_rgb, rect)
                if args.show_box:
                    pygame.draw.rect(screen, (120, 120, 120), rect, 2)
            if args.info:
                txt1 = f"State={['SHOW','ITI','WAIT_RELEASE'][state]}  Rect {rect.w}x{rect.h}  successes={successes}  failures={failures}  outside={outside_touches_in_trial}/{max_outside_before_fail}"
                screen.blit(pygame.font.SysFont(None, 28).render(txt1, True, (220, 220, 220)), (20, 20))
            pygame.display.flip()

        def append_log(event_name, x, y, iti_ms, extra=None):
            nowp = time.perf_counter()
            rel = nowp - t0
            iso = datetime.now().isoformat(timespec="milliseconds")
            row = {
                "start_iso": start_iso,
                "iso": iso,
                "rel_s": f"{rel:.6f}",
                "state": ["SHOW", "ITI", "WAIT_RELEASE"][state],
                "x": x, "y": y,
                "rect_w": rect.w, "rect_h": rect.h,
                "iti_ms": iti_ms,
                "event": event_name
            }
            if extra is not None:
                row.update(extra)
            logs.append(row)

        draw(stim_on=True)

        running = True
        iti_end_time = 0.0
        wait_release_enter_t = None  # for timeout

        while running:
            # ---- Poll events ----
            for ev in pygame.event.get():
                if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE:
                    running = False
                    break
                if ev.type == pygame.QUIT:
                    running = False
                    break

                # maintain contact sets
                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    mouse_down = True
                elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                    mouse_down = False
                elif ev.type == pygame.FINGERDOWN:
                    active_fingers.add(ev.finger_id)
                elif ev.type == pygame.FINGERUP:
                    active_fingers.discard(ev.finger_id)

                # 位置取得ヘルパ
                def _get_xy(e):
                    if e.type == pygame.MOUSEBUTTONDOWN:
                        if e.button != 1:
                            return None
                        return e.pos
                    elif e.type == pygame.FINGERDOWN:
                        return (int(e.x * sw), int(e.y * sh))
                    return None

                # ---- State machine ----
                if state == STATE_SHOW:
                    # 刺激表示中：矩形内→成功（TTL/ビープ/ITI）
                    #             矩形外→カウント、上限到達で失敗/ITI
                    if ev.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
                        xy = _get_xy(ev)
                        if xy is None:
                            continue
                        x, y = xy

                        if rect.collidepoint((x, y)):
                            # 成功（矩形内）→ TTL/ビープ、ITIへ
                            ok = True
                            #try:
                            #    ttl.pulse()
                            #except Exception as e:
                            #    print(f"[ERROR] TTL 失敗: {e}", file=sys.stderr)
                            #    ok = False
                            try:
                                beep.play()
                            except Exception:
                                pass

                            iti_ms = random.randint(iti_min, iti_max)
                            append_log("TOUCH_TTL" if ok else "TOUCH_TTL_FAIL", x, y, iti_ms,
                                       extra={"outside_in_trial": outside_touches_in_trial})
                            # shrink & 次試行の準備
                            if ok:
                                successes += 1
                                if shrink_every > 0 and (successes % shrink_every == 0):
                                    size_frac = max(min_frac, size_frac * shrink_factor)
                                    rect = cur_rect()
                                    if args.rect_mode == "sqaure_custom" and args.square_px is not None:
                                        side = int(args.square_px)
                                        rect = pygame.Rect((sw - side)//2, (sh - side)//2, side, side)

                            # ITIへ
                            state = STATE_ITI
                            iti_end_time = time.perf_counter() + iti_ms / 1000.0
                            draw(stim_on=False)
                        else:
                            # 矩形外タッチ：カウントして閾値判定
                            outside_touches_in_trial += 1
                            append_log("TOUCH_OUTSIDE", x, y, 0,
                                       extra={"outside_in_trial": outside_touches_in_trial,
                                              "max_outside_before_fail": max_outside_before_fail})
                            # 上限到達 → 失敗試行としてITIへ
                            if outside_touches_in_trial >= max_outside_before_fail:
                                failures += 1
                                iti_ms = random.randint(iti_min, iti_max)
                                append_log("FAIL_OUTSIDE_LIMIT", x, y, iti_ms,
                                           extra={"outside_in_trial": outside_touches_in_trial})
                                state = STATE_ITI
                                iti_end_time = time.perf_counter() + iti_ms / 1000.0
                                draw(stim_on=False)

                elif state == STATE_ITI:
                    # ITI 中のタッチも記録（状態は維持、TTL/ビープなし）
                    if ev.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
                        xy = _get_xy(ev)
                        if xy is None:
                            continue
                        x, y = xy
                        if rect.collidepoint((x, y)):
                            append_log("TOUCH_ITI_INSIDE", x, y, 0)
                        else:
                            append_log("TOUCH_ITI_OUTSIDE", x, y, 0)
                        draw(stim_on=False)

                elif state == STATE_WAIT_RELEASE:
                    # ここでは離し判定のみ
                    pass

            if not running:
                break

            # ---- State transitions independent of events ----
            if state == STATE_ITI:
                # ITI終了 → 離し待ちへ
                if time.perf_counter() >= iti_end_time:
                    state = STATE_WAIT_RELEASE
                    wait_release_enter_t = time.perf_counter()
                    # ブランクのまま

            if state == STATE_WAIT_RELEASE:
                # すべての接触が離されたら次試行へ
                if not mouse_down and not active_fingers:
                    state = STATE_SHOW
                    # 次試行：外れタッチ数をリセット
                    outside_touches_in_trial = 0
                    rect = cur_rect()
                    if args.rect_mode == "sqaure_custom" and args.square_px is not None:
                        side = int(args.square_px)
                        rect = pygame.Rect((sw - side)//2, (sh - side)//2, side, side)
                    draw(stim_on=True)
                else:
                    # タイムアウトで強制開放
                    if wait_release_enter_t is not None and (time.perf_counter() - wait_release_enter_t) >= wait_release_timeout:
                        active_fingers.clear()
                        mouse_down = False
                        state = STATE_SHOW
                        outside_touches_in_trial = 0
                        rect = cur_rect()
                        if args.rect_mode == "sqaure_custom" and args.square_px is not None:
                            side = int(args.square_px)
                            rect = pygame.Rect((sw - side)//2, (sh - side)//2, side, side)
                        draw(stim_on=True)

            clock.tick(240)

        # ---- Save CSV ----
        out_dir = Path(args.out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"touch_rect_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        with out_path.open("w", newline="", encoding="utf-8") as f:
            fieldnames = ["start_iso","iso","rel_s","state","x","y","rect_w","rect_h","iti_ms","event","outside_in_trial","max_outside_before_fail"]
            w = csv.DictWriter(f, fieldnames=fieldnames)
            w.writeheader()
            w.writerows(logs)
        print(f"[INFO] Saved CSV: {out_path}")

    finally:
        try:
            pygame.quit()
        except Exception:
            pass
        if ttl is not None:
            ttl.close()

def parse_args():
    p = argparse.ArgumentParser(description="Touchscreen rectangle training (FSM: SHOW→ITI→WAIT_RELEASE, outside-fail rule)")
    # 画面
    p.add_argument("--fullscreen", action="store_true")
    p.add_argument("--window-w", type=int, default=1280)
    p.add_argument("--window-h", type=int, default=720)
    p.add_argument("--kiosk", action="store_true", help="フルスクリーン・カーソル非表示・入力グラブ")
    # 入力
    p.add_argument("--touch-only", action="store_true", help="タッチのみ許可（MOUSE系ブロック）")
    # 矩形
    p.add_argument("--rect-mode", choices=["auto","square","square_custom"], default="auto")
    p.add_argument("--square-px", type=int, default=None)
    p.add_argument("--initial-size-frac", type=float, default=1.0)
    p.add_argument("--min-size-frac", type=float, default=0.10)
    p.add_argument("--shrink-every", type=int, default=10)
    p.add_argument("--shrink-factor", type=float, default=0.8)
    p.add_argument("--min-side-px", type=int, default=None, help="矩形の一辺の最小px（これ以下にならない）")
    p.add_argument("--auto-fullscreen-rect", action="store_true",
                   help="autoモードで full-screen & side>=short のときに矩形を全面化する（デフォルトは無効）")
    # 色
    p.add_argument("--rect-rgb", type=int, nargs=3, default=(0,160,255))
    p.add_argument("--bg-rgb", type=int, nargs=3, default=(0,0,0))
    # TTL
    p.add_argument("--serial-port", type=str, required=True)
    p.add_argument("--serial-baud", type=int, default=115200)
    # ITI / ビープ
    p.add_argument("--iti-min-ms", type=int, default=1000)
    p.add_argument("--iti-max-ms", type=int, default=1000)
    p.add_argument("--beep-freq", type=int, default=1000)
    p.add_argument("--beep-ms", type=int, default=100)
    p.add_argument("--beep-volume", type=float, default=0.6)
    # 離し待ちフェイルセーフ
    p.add_argument("--wait-release-timeout-ms", type=int, default=2000,
                   help="WAIT_RELEASE でこの時間を超えたら強制的に次試行へ（取りこぼし対策）")
    # New: 矩形外上限
    p.add_argument("--max-outside-before-fail", type=int, default=5,
                   help="SHOW状態での矩形外タッチ許容回数（到達で失敗→ITI）")
    # ログ/表示
    p.add_argument("--out-dir", type=str, default="logs")
    p.add_argument("--show-box", action="store_true")
    p.add_argument("--info", action="store_true")
    return p.parse_args()

if __name__ == "__main__":
    args = parse_args()
    run(args)
