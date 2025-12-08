import argparse, csv, sys, time, math, random, array
from datetime import datetime
from pathlib import Path
import pygame

try:
    import serial
except ImportError:
    serial = None

# ============ Arduino TTL ============
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
        self.ser.write(b"PULSE\n"); self.ser.flush()
    def close(self):
        try: self.ser.close()
        except Exception: pass

# ============ Beep ============
def make_beep_sound(freq=1000, duration_ms=100, volume=0.6, sample_rate=44100):
    n = int(sample_rate * duration_ms / 1000)
    buf = array.array("h"); amp = int(32767 * max(0.0, min(volume, 1.0)))
    for i in range(n):
        t = i / sample_rate
        buf.append(int(amp * math.sin(2*math.pi*freq*t)))
    return pygame.mixer.Sound(buffer=buf.tobytes())

# ============ Helpers ============
def clamp(v, lo, hi): return max(lo, min(hi, v))

def square_side_pixels(sw, sh, square_px, square_frac):
    if square_px is not None:
        return max(1, int(square_px))
    if square_frac is not None:
        return max(1, int(min(sw, sh) * float(square_frac)))
    return 400  # default px

def margin_pixels(sw, sh, margin_px, margin_frac):
    if margin_px is not None:
        m = int(margin_px)
    elif margin_frac is not None:
        m = int(min(sw, sh) * float(margin_frac))
    else:
        m = 0
    # マイナスや過大は後段で自然に処理するが最低0に
    return max(0, m)

def make_random_square_with_margin(sw, sh, side, margin):
    """
    マージンを四辺に同じだけ適用し、その内側領域に正方形をランダム配置。
    収まらない場合は side を縮めて収まる最大サイズに調整。
    """
    # 使用可能な幅・高さ
    usable_w = max(0, sw - 2 * margin)
    usable_h = max(0, sh - 2 * margin)
    if usable_w <= 0 or usable_h <= 0:
        # 画面よりマージンが大きい場合は中央に1px配置
        side_eff = 1
        left = sw // 2
        top = sh // 2
        return pygame.Rect(left, top, side_eff, side_eff)

    # side を内側領域に収まるよう調整
    side_eff = clamp(side, 1, min(usable_w, usable_h))

    max_left = margin + (usable_w - side_eff)
    max_top  = margin + (usable_h - side_eff)
    left = margin if max_left <= margin else random.randint(margin, max_left)
    top  = margin if max_top  <= margin else random.randint(margin, max_top)

    return pygame.Rect(left, top, side_eff, side_eff)

# ============ Main ============
def run(args):
    pygame.init()
    pygame.mixer.init(frequency=44100, size=-16, channels=1)

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
    try:
        flags = pygame.FULLSCREEN if args.fullscreen else pygame.NOFRAME
        screen = pygame.display.set_mode((0,0) if args.fullscreen else (args.window_w,args.window_h), flags)
        pygame.display.set_caption("Touch Rectangle Training (Random Square with Margin)")
        clock = pygame.time.Clock()
        font = pygame.font.SysFont(None, 28)
        sw, sh = screen.get_size()

        # Params
        iti_min = max(0,int(args.iti_min_ms))
        iti_max = max(iti_min,int(args.iti_max_ms))

        # 正方形サイズ・マージン決定
        side_fixed = square_side_pixels(sw, sh, args.square_px, args.square_frac)
        margin = margin_pixels(sw, sh, args.margin_px, args.margin_frac)

        # FSM
        STATE_SHOW, STATE_ITI, STATE_WAIT_RELEASE = 0, 1, 2
        state = STATE_SHOW
        mouse_down = False
        active_fingers = set()

        ttl = ArduinoTTLSender(args.serial_port, args.serial_baud)
        beep = make_beep_sound(args.beep_freq, args.beep_ms, args.beep_volume)

        logs = []
        t0 = time.perf_counter()
        start_iso = datetime.now().isoformat(timespec="milliseconds")
        successes = 0

        # 初回の正方形（ランダム・マージン考慮）
        rect = make_random_square_with_margin(sw, sh, side_fixed, margin)

        def draw(stim_on: bool):
            screen.fill(args.bg_rgb)
            if stim_on:
                pygame.draw.rect(screen, args.rect_rgb, rect)
                if args.show_box: pygame.draw.rect(screen,(120,120,120),rect,2)
            if args.info:
                txt1 = f"State={['SHOW','ITI','WAIT_RELEASE'][state]}  Rect {rect.w}x{rect.h}@({rect.left},{rect.top})"
                txt2 = f"ITI {iti_min}-{iti_max} ms  size={side_fixed}px  margin={margin}px"
                screen.blit(font.render(txt1, True, (220,220,220)), (20,20))
                screen.blit(font.render(txt2, True, (220,220,220)), (20,50))
            pygame.display.flip()

        draw(stim_on=True)
        running = True
        iti_end_time = 0.0

        while running:
            for ev in pygame.event.get():
                if ev.type == pygame.KEYDOWN and ev.key == pygame.K_ESCAPE: running=False; break
                if ev.type == pygame.QUIT: running=False; break

                # 接触状態を更新
                if ev.type == pygame.MOUSEBUTTONDOWN and ev.button == 1:
                    mouse_down = True
                elif ev.type == pygame.MOUSEBUTTONUP and ev.button == 1:
                    mouse_down = False
                elif ev.type == pygame.FINGERDOWN:
                    active_fingers.add(ev.finger_id)
                elif ev.type == pygame.FINGERUP:
                    active_fingers.discard(ev.finger_id)

                if state == STATE_SHOW:
                    if ev.type in (pygame.MOUSEBUTTONDOWN, pygame.FINGERDOWN):
                        if ev.type == pygame.MOUSEBUTTONDOWN:
                            if ev.button != 1: continue
                            x, y = ev.pos
                        else:
                            x = int(ev.x * sw); y = int(ev.y * sh)
                        if not rect.collidepoint((x,y)):
                            continue

                        # 受理（ワンショット）
                        nowp = time.perf_counter()
                        rel = nowp - t0
                        iso = datetime.now().isoformat(timespec="milliseconds")

                        ok = True
                        try: ttl.pulse()
                        except Exception as e: print(f"[ERROR] TTL 失敗: {e}", file=sys.stderr); ok=False
                        try: beep.play()
                        except Exception: pass

                        iti_ms = random.randint(iti_min, iti_max)
                        logs.append({
                            "start_iso": start_iso, "iso": iso, "rel_s": f"{rel:.6f}",
                            "x": x, "y": y,
                            "rect_w": rect.w, "rect_h": rect.h,
                            "rect_left": rect.left, "rect_top": rect.top,
                            "margin_px": margin,
                            "iti_ms": iti_ms,
                            "event": "TOUCH_TTL" if ok else "TOUCH_TTL_FAIL"
                        })

                        if ok: successes += 1

                        # ITIへ（ブランク）
                        state = STATE_ITI
                        iti_end_time = time.perf_counter() + iti_ms/1000.0
                        draw(stim_on=False)

                # ITI中/WAIT_RELEASE中のダウンは全無視（何もしない）

            if not running: break

            # ITI → WAIT_RELEASE
            if state == STATE_ITI and time.perf_counter() >= iti_end_time:
                state = STATE_WAIT_RELEASE
                # ブランクのまま

            # WAIT_RELEASE → SHOW（全て離されたら次試行：新しいランダム位置をサンプル）
            if state == STATE_WAIT_RELEASE and not mouse_down and not active_fingers:
                rect = make_random_square_with_margin(sw, sh, side_fixed, margin)
                state = STATE_SHOW
                draw(stim_on=True)

            clock.tick(240)

        # CSV 保存
        out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"touch_rect_log_{datetime.now().strftime('%Y%m%d_%H%M%S')}.csv"
        with out_path.open("w", newline="", encoding="utf-8") as f:
            w = csv.DictWriter(
                f,
                fieldnames=[
                    "start_iso","iso","rel_s","x","y",
                    "rect_w","rect_h","rect_left","rect_top",
                    "margin_px","iti_ms","event"
                ]
            )
            w.writeheader(); w.writerows(logs)
        print(f"[INFO] Saved CSV: {out_path}")

    finally:
        try: pygame.quit()
        except Exception: pass
        if ttl is not None: ttl.close()

def parse_args():
    p = argparse.ArgumentParser(description="Touchscreen training: random-position square with edge margin (SHOW→ITI→WAIT_RELEASE)")
    # 画面／入力
    p.add_argument("--fullscreen", action="store_true")
    p.add_argument("--window-w", type=int, default=1280)
    p.add_argument("--window-h", type=int, default=720)
    p.add_argument("--kiosk", action="store_true", help="フルスクリーン・カーソル非表示・入力グラブ")
    p.add_argument("--touch-only", action="store_true", help="タッチのみ許可（MOUSE系ブロック）")
    # 正方形サイズ（いずれか指定。両方未指定なら 400px）
    p.add_argument("--square-px", type=int, default=None, help="正方形の一辺(px)")
    p.add_argument("--square-frac", type=float, default=None, help="画面短辺に対する比率 (0-1)")
    # マージン（四辺等距離）
    p.add_argument("--margin-px", type=int, default=None, help="四辺からの最小マージン(px)")
    p.add_argument("--margin-frac", type=float, default=None, help="短辺比でのマージン (0-1)")
    # 色
    p.add_argument("--rect-rgb", type=int, nargs=3, default=(0,160,255))
    p.add_argument("--bg-rgb", type=int, nargs=3, default=(0,0,0))
    # TTL / ビープ / ITI
    p.add_argument("--serial-port", type=str, required=True)
    p.add_argument("--serial-baud", type=int, default=115200)
    p.add_argument("--beep-freq", type=int, default=1000)
    p.add_argument("--beep-ms", type=int, default=100)
    p.add_argument("--beep-volume", type=float, default=0.6)
    p.add_argument("--iti-min-ms", type=int, default=1000)
    p.add_argument("--iti-max-ms", type=int, default=1000)
    # ログ/表示
    p.add_argument("--out-dir", type=str, default="logs")
    p.add_argument("--show-box", action="store_true")
    p.add_argument("--info", action="store_true")
    return p.parse_args()

if __name__ == "__main__":
    args = parse_args()
    run(args)
