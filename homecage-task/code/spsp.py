# touch_2stim_discrimination_both_r.py
# -*- coding: utf-8 -*-
import argparse, csv, sys, time, math, random, array, re
from collections import deque
from datetime import datetime
from pathlib import Path
from typing import Optional, List

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
        # Arduino 側で "PULSE\n" を受けて 5V TTL を出す実装を想定
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
# 刺激セットの検出＆読み込み
# =========================
class StimSet:
    """
    1 セット（番号ラベルと r/nr パス、Surface を保持）
    nr は不要（None 可）。描画は常に r を左右に提示する。
    """
    def __init__(self, idx_num: int, r_path: Optional[Path], nr_path: Optional[Path]):
        self.idx_num = idx_num
        self.r_path: Optional[Path] = r_path
        self.nr_path: Optional[Path] = nr_path
        self.r_surf: Optional[pygame.Surface] = None
        self.nr_surf: Optional[pygame.Surface] = None  # 未使用だが互換のため保持

    @property
    def label(self):
        return f"stim_{self.idx_num:02d}"


def find_stim_sets(stim_dir: Path) -> List[StimSet]:
    """
    以下の優先順で列挙
    1) stim_XX_r.png / stim_XX_nr.png のペアがある番号のみ
    2) ペアが全く無い場合、stim_XX_r.png のみを持つ番号すべて
    3) 何も無ければ空
    """
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

    idxs_pair = sorted(set(r_map.keys()) & set(nr_map.keys()))
    if idxs_pair:
        return [StimSet(i, r_map[i], nr_map[i]) for i in idxs_pair]

    idxs_r_only = sorted(r_map.keys())
    if idxs_r_only:
        return [StimSet(i, r_map[i], None) for i in idxs_r_only]

    return []


# =========================
# メイン
# =========================
def run(args):
    pygame.init()
    # --- サウンドは環境により初期化失敗しうる ---
    try:
        pygame.mixer.init(frequency=44100, size=-16, channels=1)
    except Exception as e:
        print(f"[WARN] mixer init failed: {e}", file=sys.stderr)

    # 省電力/スクリーンセーバ回避（対応環境のみ）
    try:
        pygame.display.set_allow_screensaver(False)
    except Exception:
        pass

    # ---- Pygame イベント種の存在を取得（環境依存対策）----
    FINGERDOWN   = getattr(pygame, "FINGERDOWN", None)
    FINGERUP     = getattr(pygame, "FINGERUP", None)
    FINGERMOTION = getattr(pygame, "FINGERMOTION", None)
    MOUSEWHEEL   = getattr(pygame, "MOUSEWHEEL", None)

    # ---- イベント衛生：使わないイベントをブロック ----
    to_block = [pygame.MOUSEMOTION]
    if FINGERMOTION is not None: to_block.append(FINGERMOTION)
    if MOUSEWHEEL   is not None: to_block.append(MOUSEWHEEL)
    pygame.event.set_blocked(to_block)

    # Kiosk / 入力ポリシー
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
        pygame.display.set_caption("Two-Stimulus Task (Both R, Plate-based Hit, Outside-only Error)")
        clock = pygame.time.Clock()
        font = pygame.font.SysFont(None, 28)
        sw, sh = screen.get_size()

        # ---- 刺激セットの取得 ----
        stim_sets: List[StimSet] = []
        if args.no_images:
            # 画像なし：ダミーセットを生成（プレートのみ）
            for i in range(1, args.dummy_sets + 1):
                stim_sets.append(StimSet(i, r_path=None, nr_path=None))
        else:
            if not args.stim_dir:
                raise RuntimeError("--stim-dir を指定するか、--no-images を使用してください。")
            stim_dir = Path(args.stim_dir)
            if not stim_dir.exists():
                raise RuntimeError(f"刺激ディレクトリが見つかりません: {stim_dir}")
            stim_sets = find_stim_sets(stim_dir)
            if not stim_sets:
                print(f"[WARN] {stim_dir} に画像が見つからないため画像なしモードに自動切替えします。", file=sys.stderr)
                args.no_images = True
                for i in range(1, args.dummy_sets + 1):
                    stim_sets.append(StimSet(i, r_path=None, nr_path=None))

        # ---- 刺激サイズ（画像サイズ）----
        if args.stim_px is not None:
            stim_w = stim_h = max(1, int(args.stim_px))
        else:
            stim_w = max(1, int(args.stim_w))
            stim_h = max(1, int(args.stim_h))

        # ---- プレート（背景グレー矩形）のサイズ ----
        # 既定は画像サイズと同一。指定があれば上書き。常に画像サイズ以上にクランプ。
        if args.plate_px is not None:
            plate_w = plate_h = max(stim_w, stim_h, int(args.plate_px))
        elif args.plate_w is not None and args.plate_h is not None:
            plate_w = max(stim_w, int(args.plate_w))
            plate_h = max(stim_h, int(args.plate_h))
        else:
            plate_w, plate_h = stim_w, stim_h  # デフォルト＝画像サイズと同じ

        # ---- 左右配置（中心から等距離） ----
        edge_margin = max(0, int(args.edge_margin_px))
        # クランプはプレート基準（画面端にはみ出さないように）
        max_offset = max(0, (sw // 2) - (plate_w // 2) - edge_margin)
        center_offset = min(max_offset, max(0, int(args.center_offset_px)))
        if center_offset < int(args.center_offset_px):
            print(f"[WARN] center-offset を {center_offset}px にクランプ（画面外防止；プレートサイズ基準）", file=sys.stderr)

        cy = sh // 2

        def compute_rects():
            """
            戻り値:
              left_img_rect, right_img_rect, left_plate_rect, right_plate_rect
            いずれも中心は同一点（ディスプレイ中心±offset, y中心）。
            """
            left_cx  = (sw // 2) - center_offset
            right_cx = (sw // 2) + center_offset

            left_img_rect  = pygame.Rect(left_cx - stim_w // 2,  cy - stim_h // 2,  stim_w,  stim_h)
            right_img_rect = pygame.Rect(right_cx - stim_w // 2, cy - stim_h // 2, stim_w,  stim_h)

            left_plate_rect  = pygame.Rect(left_cx - plate_w // 2,  cy - plate_h // 2,  plate_w,  plate_h)
            right_plate_rect = pygame.Rect(right_cx - plate_w // 2, cy - plate_h // 2, plate_w,  plate_h)

            return left_img_rect, right_img_rect, left_plate_rect, right_plate_rect

        # ---- 画像ロード＆スケーリング（画像なしモードではスキップ）----
        if not args.no_images:
            for ss in stim_sets:
                if ss.r_path is not None:
                    r_img = pygame.image.load(str(ss.r_path)).convert_alpha()
                    if r_img.get_width() != stim_w or r_img.get_height() != stim_h:
                        r_img = pygame.transform.smoothscale(r_img, (stim_w, stim_h))
                    ss.r_surf = r_img
                # nr は未使用だが、互換のため必要なら読み込む（コメントアウト可）
                if ss.nr_path is not None:
                    try:
                        nr_img = pygame.image.load(str(ss.nr_path)).convert_alpha()
                        if nr_img.get_width() != stim_w or nr_img.get_height() != stim_h:
                            nr_img = pygame.transform.smoothscale(nr_img, (stim_w, stim_h))
                        ss.nr_surf = nr_img
                    except Exception:
                        ss.nr_surf = None

        # ---- ITI 等パラメータ ----
        base_min = max(0, int(args.iti_min_ms))
        base_max = max(base_min, int(args.iti_max_ms))
        iti_correct_min = int(args.iti_correct_min_ms) if args.iti_correct_min_ms is not None else base_min
        iti_correct_max = int(args.iti_correct_max_ms) if args.iti_correct_max_ms is not None else base_max
        iti_error_min   = int(args.iti_error_min_ms)   if args.iti_error_min_ms   is not None else base_min
        iti_error_max   = int(args.iti_error_max_ms)   if args.iti_error_max_ms   is not None else base_max

        iti_correct_min = max(0, iti_correct_min); iti_correct_max = max(iti_correct_min, iti_correct_max)
        iti_error_min   = max(0, iti_error_min);   iti_error_max   = max(iti_error_min, iti_error_max)

        def sample_iti(kind: str) -> int:
            if kind == "correct":
                return random.randint(iti_correct_min, iti_correct_max)
            else:
                return random.randint(iti_error_min, iti_error_max)

        wait_release_timeout = max(0, int(args.wait_release_timeout_ms)) / 1000.0
        min_release_after_iti_touch_s = max(0, int(args.min_release_ms_after_iti_touch)) / 1000.0
        max_outside_before_fail = max(1, int(args.max_outside_before_fail))
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

        # ---- TTL / ビープ ----
        ttl = ArduinoTTLSender(args.serial_port, args.serial_baud)
        try:
            beep = make_beep_sound(args.beep_freq, args.beep_ms, args.beep_volume)
        except Exception as e:
            beep = None
            print(f"[WARN] beep disabled: {e}", file=sys.stderr)

        # ---- CSV：逐次書き出し ----
        out_dir = Path(args.out_dir); out_dir.mkdir(parents=True, exist_ok=True)
        start_dt = datetime.now()
        start_iso = start_dt.isoformat(timespec="milliseconds")
        out_path = out_dir / f"touch_2stim_log_{start_dt.strftime('%Y%m%d_%H%M%S')}.csv"

        fieldnames = [
            "start_iso","iso","rel_s","state",
            "x","y",
            # 画像（描画）矩形
            "left_x","left_y","left_w","left_h",
            "right_x","right_y","right_w","right_h",
            # プレート（判定用・描画用）矩形
            "left_plate_x","left_plate_y","left_plate_w","left_plate_h",
            "right_plate_x","right_plate_y","right_plate_w","right_plate_h",
            "hit_margin_px","hit_area",           # left_core/right_core/left_margin/right_margin/outside （※plate基準）
            "event",
            "iti_ms","iti_kind",
            "outside_in_trial","max_outside_before_fail",
            "trial_outcome","fail_reason",
            "stim_set","left_label","right_label",
            "left_image","right_image","target_image","non_target_image",
            "trial_index_global","trial_index_in_set",
            "sliding_n","sliding_correct","sliding_acc",
            "correction_mode","is_correction_trial"
        ]
        csv_f = out_path.open("w", newline="", encoding="utf-8")
        csv_w = csv.DictWriter(csv_f, fieldnames=fieldnames)
        csv_w.writeheader()
        write_count = 0

        # ---- 計時・カウンタ ----
        t0 = time.perf_counter()
        successes = 0
        failures = 0
        trial_index_global = 0
        trial_index_in_set = 0

        # ---- セット・正答率管理 ----
        current_set_idx = 0  # 0-based
        sliding_n = max(1, int(args.sliding_n))
        acc_threshold = float(args.acc_threshold)
        window = deque(maxlen=sliding_n)
        sliding_correct = 0  # window 内 1 の個数（高速化）

        # ---- コレクショントライアル管理 ----
        correction_mode_enabled = bool(args.correction_mode)
        correction_active = False         # 次試行がコレクションかどうか
        correction_left_is_r = None       # （互換ダミー）両 r のため実質未使用
        current_trial_is_correction = False  # ログ用

        # ---- 位置とマッピング ----
        left_rect, right_rect, left_plate_rect, right_plate_rect = compute_rects()  # 画像矩形/プレート矩形
        left_is_r = True  # 両方 r のため常に True
        left_surf = None
        right_surf = None

        # append_log: 現状の配置・刺激情報を含めて行追加
        def append_log(event_name, x, y, iti_ms, extra=None):
            nonlocal write_count
            nowp = time.perf_counter()
            rel = nowp - t0
            iso = datetime.now().isoformat(timespec="milliseconds")
            cur_set = stim_sets[current_set_idx]
            left_img_name  = cur_set.r_path.name if cur_set.r_path is not None else ""
            right_img_name = cur_set.r_path.name if cur_set.r_path is not None else ""
            target_img     = cur_set.r_path.name if cur_set.r_path is not None else ""
            row = {
                "start_iso": start_iso,
                "iso": iso,
                "rel_s": f"{rel:.6f}",
                "state": ["SHOW", "ITI", "WAIT_RELEASE"][state],
                "x": x, "y": y,
                # 画像矩形（描画情報）
                "left_x": left_rect.x, "left_y": left_rect.y, "left_w": left_rect.w, "left_h": left_rect.h,
                "right_x": right_rect.x, "right_y": right_rect.y, "right_w": right_rect.w, "right_h": right_rect.h,
                # プレート矩形（判定＆描画）
                "left_plate_x": left_plate_rect.x, "left_plate_y": left_plate_rect.y, "left_plate_w": left_plate_rect.w, "left_plate_h": left_plate_rect.h,
                "right_plate_x": right_plate_rect.x, "right_plate_y": right_plate_rect.y, "right_plate_w": right_plate_rect.w, "right_plate_h": right_plate_rect.h,
                "hit_margin_px": hit_margin_px,
                "hit_area": "",
                "event": event_name,
                "iti_ms": iti_ms,
                "iti_kind": "",
                "outside_in_trial": outside_touches_in_trial,
                "max_outside_before_fail": max_outside_before_fail,
                "trial_outcome": "",
                "fail_reason": "",
                "stim_set": cur_set.label,
                "left_label": "r",
                "right_label": "r",
                "left_image": left_img_name,
                "right_image": right_img_name,
                "target_image": target_img,
                "non_target_image": "",  # 両 r のため空
                "trial_index_global": trial_index_global,
                "trial_index_in_set": trial_index_in_set,
                "sliding_n": sliding_n,
                "sliding_correct": sliding_correct,
                "sliding_acc": (sliding_correct / len(window)) if len(window) > 0 else 0.0,
                "correction_mode": 1 if correction_mode_enabled else 0,
                "is_correction_trial": 1 if current_trial_is_correction else 0,
            }
            if extra is not None:
                row.update(extra)
            csv_w.writerow(row)
            write_count += 1
            if write_count % 64 == 0:
                csv_f.flush()

        # 描画
        def draw(stim_on: bool):
            screen.fill(args.bg_rgb)
            if stim_on:
                # 先にプレート（背景グレー）を塗る
                pygame.draw.rect(screen, args.plate_rgb, left_plate_rect)
                pygame.draw.rect(screen, args.plate_rgb, right_plate_rect)
                # 次に画像を重ねる（no-images の場合は blit しない）
                if (not args.no_images) and (left_surf is not None):
                    screen.blit(left_surf, left_rect)
                if (not args.no_images) and (right_surf is not None):
                    screen.blit(right_surf, right_rect)
                # デバッグ用枠線
                if args.show_box:
                    # プレート枠（濃い）
                    pygame.draw.rect(screen, (120, 120, 120), left_plate_rect, 2)
                    pygame.draw.rect(screen, (120, 120, 120), right_plate_rect, 2)
                    # 画像枠（薄い）
                    pygame.draw.rect(screen, (200, 200, 200), left_rect, 1)
                    pygame.draw.rect(screen, (200, 200, 200), right_rect, 1)
            if args.info:
                cur_set = stim_sets[current_set_idx]
                acc = (sliding_correct / len(window)) if len(window) > 0 else 0.0
                txt1 = (f"State={['SHOW','ITI','WAIT_RELEASE'][state]}  "
                        f"Set={cur_set.label}  "
                        f"Trials(g/s)={trial_index_global}/{trial_index_in_set}  "
                        f"succ={successes}  fail={failures}  "
                        f"outside={outside_touches_in_trial}/{max_outside_before_fail}  "
                        f"win{sliding_n} acc={acc*100:.1f}%  "
                        f"corr={'ON' if current_trial_is_correction else 'OFF'}  "
                        f"HIT=plate(+margin {hit_margin_px}px)")
                screen.blit(font.render(txt1, True, (220, 220, 220)), (20, 20))
            pygame.display.flip()

        # ---- 新規試行の配置（両 r 表示）----
        def place_new_trial():
            nonlocal left_is_r, left_surf, right_surf
            nonlocal left_rect, right_rect, left_plate_rect, right_plate_rect
            nonlocal current_trial_is_correction

            cur_set = stim_sets[current_set_idx]
            current_trial_is_correction = args.correction_mode and correction_active

            # 両プレートとも報酬刺激（r）を提示
            left_is_r  = True  # ログ互換用フラグ（常に True）
            left_surf  = cur_set.r_surf if (not args.no_images) else None
            right_surf = cur_set.r_surf if (not args.no_images) else None

            # 矩形群を再計算（画面リサイズ等の変化にも対応）
            left_rect, right_rect, left_plate_rect, right_plate_rect = compute_rects()

            append_log("TRIAL_PLACED", -1, -1, 0)

        # ---- 正答率窓を更新し、必要ならセット昇格 ----
        def update_window_and_maybe_advance(was_correct: bool, trial_is_correction: bool, allow_advance: bool):
            nonlocal current_set_idx, trial_index_in_set, window, sliding_correct

            # コレクショントライアルを正答率から除外するオプション
            consider_for_acc = True
            if args.exclude_correction_from_acc and trial_is_correction:
                consider_for_acc = False

            if consider_for_acc:
                if len(window) == window.maxlen:
                    old = window[0]
                    if old == 1:
                        sliding_correct -= 1
                window.append(1 if was_correct else 0)
                if was_correct: sliding_correct += 1

            # セット昇格（許可されたときのみ）
            if allow_advance and len(window) == sliding_n:
                acc = sliding_correct / sliding_n
                if acc > acc_threshold and (current_set_idx + 1) < len(stim_sets):
                    current_set_idx += 1
                    trial_index_in_set = 0
                    window.clear()
                    sliding_correct = 0
                    print(f"[INFO] Advance to {stim_sets[current_set_idx].label} (acc={acc:.3f} > {acc_threshold:.3f})")

        # 初回配置
        place_new_trial()
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

            # ---- 1) 終了系イベントを最優先処理 ----
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

            # 念のためフォールバック
            pygame.event.pump()
            keys = pygame.key.get_pressed()
            if keys[pygame.K_ESCAPE] or keys[pygame.K_q]:
                running = False
                break

            # ---- 2) 必要な入力イベントのみ取得 ----
            want = [pygame.MOUSEBUTTONDOWN, pygame.MOUSEBUTTONUP]
            if FINGERDOWN is not None: want.append(FINGERDOWN)
            if FINGERUP   is not None: want.append(FINGERUP)

            for ev in pygame.event.get(want):
                # contact sets
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

                        # 当たり領域（マージン込み）※ ★プレート矩形基準★
                        left_hit  = left_plate_rect.inflate(2*hit_margin_px, 2*hit_margin_px).collidepoint((x, y))
                        right_hit = right_plate_rect.inflate(2*hit_margin_px, 2*hit_margin_px).collidepoint((x, y))

                        if left_hit or right_hit:
                            touched_side = "left" if left_hit else "right"
                            if touched_side == "left":
                                hit_area = "left_core" if left_plate_rect.collidepoint((x, y)) else "left_margin"
                            else:
                                hit_area = "right_core" if right_plate_rect.collidepoint((x, y)) else "right_margin"

                            # ==== 成功（どちらのプレートでも正解）====
                            ok = True
                            try:
                                ttl.pulse()  # 5V TTL
                            except Exception as e:
                                print(f"[ERROR] TTL 失敗: {e}", file=sys.stderr)
                                ok = False
                            try:
                                if beep is not None:
                                    beep.play()
                            except Exception:
                                pass

                            iti_ms = sample_iti("correct")
                            append_log("TOUCH_R_CORRECT" if ok else "TOUCH_R_CORRECT_TTL_FAIL", x, y, iti_ms,
                                       extra={"hit_area": hit_area,
                                              "trial_outcome": "success",
                                              "iti_kind": "correct"})
                            if ok:
                                successes += 1
                            trial_is_correction = current_trial_is_correction  # 現試行の属性を退避
                            # コレクション解除（成功で解除）
                            if correction_mode_enabled and correction_active:
                                correction_active = False
                                correction_left_is_r = None

                            trial_index_global += 1
                            trial_index_in_set += 1
                            # 成功時は昇格判定を許可
                            update_window_and_maybe_advance(True, trial_is_correction, allow_advance=True)

                            state = STATE_ITI
                            touch_during_iti = mouse_down or bool(active_fingers)
                            iti_end_time = time.perf_counter() + iti_ms / 1000.0
                            draw(stim_on=False)

                        else:
                            # ==== プレート外タッチ ====
                            outside_touches_in_trial += 1
                            append_log("TOUCH_OUTSIDE", x, y, 0, extra={"hit_area": "outside"})
                            if outside_touches_in_trial >= max_outside_before_fail:
                                failures += 1
                                iti_ms = sample_iti("error")
                                append_log("FAIL_OUTSIDE_LIMIT", x, y, iti_ms,
                                           extra={"hit_area": "outside",
                                                  "trial_outcome": "error",
                                                  "fail_reason": "outside_limit",
                                                  "iti_kind": "error"})
                                trial_is_correction = current_trial_is_correction
                                if correction_mode_enabled:
                                    correction_active = True
                                    correction_left_is_r = left_is_r  # ダミー

                                trial_index_global += 1
                                trial_index_in_set += 1
                                update_window_and_maybe_advance(False, trial_is_correction,
                                                                allow_advance=(not correction_mode_enabled))

                                state = STATE_ITI
                                touch_during_iti = mouse_down or bool(active_fingers)
                                iti_end_time = time.perf_counter() + iti_ms / 1000.0
                                draw(stim_on=False)

                elif state == STATE_ITI:
                    # ITI 中のタッチも記録（★プレート基準★）
                    if (ev.type == pygame.MOUSEBUTTONDOWN) or (FINGERDOWN is not None and ev.type == FINGERDOWN):
                        touch_during_iti = True
                        xy = _get_xy(ev)
                        if xy is None:
                            continue
                        x, y = xy
                        if left_plate_rect.inflate(2*hit_margin_px, 2*hit_margin_px).collidepoint((x, y)):
                            hit_area = "left_core" if left_plate_rect.collidepoint((x, y)) else "left_margin"
                            append_log("TOUCH_ITI_LEFT", x, y, 0, extra={"hit_area": hit_area})
                        elif right_plate_rect.inflate(2*hit_margin_px, 2*hit_margin_px).collidepoint((x, y)):
                            hit_area = "right_core" if right_plate_rect.collidepoint((x, y)) else "right_margin"
                            append_log("TOUCH_ITI_RIGHT", x, y, 0, extra={"hit_area": hit_area})
                        else:
                            append_log("TOUCH_ITI_OUTSIDE", x, y, 0, extra={"hit_area": "outside"})
                        draw(stim_on=False)

                elif state == STATE_WAIT_RELEASE:
                    # 離し判定は下の独立遷移で処理
                    pass

            if not running:
                break

            # ---- 3) イベント非依存の状態遷移 ----
            now = time.perf_counter()

            if state == STATE_ITI:
                # ITI終了 → 離し待ちへ
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
                                place_new_trial()
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
                        place_new_trial()
                        draw(stim_on=True)

                # タイムアウトで強制開放
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
                            place_new_trial()
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
    p = argparse.ArgumentParser(
        description="Two-stimulus task (both R shown, plate-hit = correct, outside-only error, supports no-image mode)")
    # 画面
    p.add_argument("--fullscreen", action="store_true")
    p.add_argument("--window-w", type=int, default=1280)
    p.add_argument("--window-h", type=int, default=720)
    p.add_argument("--kiosk", action="store_true", help="フルスクリーン・カーソル非表示・入力グラブ")
    # 入力
    p.add_argument("--touch-only", action="store_true", help="タッチのみ許可（MOUSE系ブロック）")
    # 画像の有無
    p.add_argument("--no-images", action="store_true", help="画像なしモード（プレートのみ表示）")
    p.add_argument("--dummy-sets", type=int, default=1, help="画像なしモードでのダミーセット数")
    # 刺激（画像を使う場合）
    p.add_argument("--stim-dir", type=str, required=False, help="stim_XX_r.png と（任意で）stim_XX_nr.png が入ったフォルダ")
    # 刺激サイズ（どちらかを使用：--stim-px で正方形 / --stim-w --stim-h で任意）
    p.add_argument("--stim-px", type=int, default=240, help="刺激表示の一辺(px)。指定時は正方形。")
    p.add_argument("--stim-w", type=int, default=None, help="刺激幅(px)。--stim-px 未指定のとき有効")
    p.add_argument("--stim-h", type=int, default=None, help="刺激高(px)。--stim-px 未指定のとき有効")
    # プレート（背景グレー）サイズと色
    p.add_argument("--plate-px", type=int, default=None, help="プレート（背景グレー）の一辺(px)。指定時は正方形。")
    p.add_argument("--plate-w", type=int, default=None, help="プレート幅(px)。--plate-px 未指定時に有効")
    p.add_argument("--plate-h", type=int, default=None, help="プレート高(px)。--plate-px 未指定時に有効")
    p.add_argument("--plate-rgb", type=int, nargs=3, default=(96,96,96), help="プレート色 (R G B)")
    # 配置（中心から等距離）
    p.add_argument("--center-offset-px", type=int, default=300, help="ディスプレイ中心から左右画像中心までの水平距離(px)")
    p.add_argument("--edge-margin-px", type=int, default=16, help="画面端との最小マージン(px)")
    # 背景色
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
    # ITI中にタッチがあった場合に必要な連続解放時間
    p.add_argument("--min-release-ms-after-iti-touch", type=int, default=2000,
                   help="ITI中タッチがあった場合，次試行前に必要な【連続】解放時間[ms]（0=要求なし）")
    # outside 上限
    p.add_argument("--max-outside-before-fail", type=int, default=5,
                   help="SHOW状態でのプレート外タッチ許容回数（到達で失敗→ITI）")
    # 当たり判定のマージン（px）※ ★プレート基準★
    p.add_argument("--hit-margin-px", type=int, default=0,
                   help="プレートの外側に当たり判定マージン（px）。この範囲内のタッチも inside とする")
    # 学習ステップ：n 試行窓と閾値
    p.add_argument("--sliding-n", type=int, default=20, help="正答率判定の試行窓 n")
    p.add_argument("--acc-threshold", type=float, default=0.8, help="昇格閾値（0.0-1.0）。'超えたら'昇格")
    # コレクショントライアル
    p.add_argument("--correction-mode", action="store_true",
                   help="失敗したら成功まで同じ左右配置を繰り返す（両 r のため配置固定の意味は薄いが、ログ/昇格制御のため保持）")
    p.add_argument("--exclude-correction-from-acc", action="store_true",
                   help="正答率（昇格判定）からコレクショントライアルを除外する（任意）")
    # ログ/表示
    p.add_argument("--out-dir", type=str, default="logs")
    p.add_argument("--show-box", action="store_true")
    p.add_argument("--info", action="store_true")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    # --stim-px 未指定時は --stim-w/h 必須（画像なしでも plate の基準として使用）
    if args.stim_px is None:
        if (args.stim_w is None) or (args.stim_h is None):
            print("[ERROR] --stim-px もしくは（--stim-w と --stim-h）の指定が必要です", file=sys.stderr)
            sys.exit(1)
    run(args)
