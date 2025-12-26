
# ops.py
import pygame
import subprocess
import threading
import sys
import signal
from datetime import datetime
from pathlib import Path

# ----- 共有状態（明示初期化）-----
recording = None
sd_mode = False

# 転送完了通知（Event推奨）
transfer_done_evt = threading.Event()

def rec_standby():
    global gst_command, video_command

    dt = datetime.now()
    datetime_str = dt.strftime("%Y-%m-%d")
    # GStreamerのfilesinkは "filesink", "location=...", "sync=true" でOK
    pass_name = f"location=/home/user/Desktop/homecage-task/logs/{datetime_str}_video.mp4"

    gst_command = [
        "gst-launch-1.0", "--eos-on-shutdown",
        "v4l2src", "device=/dev/video0", "!", "tee", "name=t",
        "t.", "!", "queue", "!", "videoconvert", "!", "x264enc",
        "tune=zerolatency", "bitrate=500", "speed-preset=superfast",
        "!", "rtph264pay", "!", "udpsink", "host=hc-task02.local", "port=5000",
        "t.", "!", "queue", "!", "videoconvert", "!", "x264enc",
        "bitrate=1000", "speed-preset=ultrafast",
        "!", "mp4mux", "faststart=true",
        "!", "filesink", pass_name, "sync=true"
    ]

    video_command = [
        "gst-launch-1.0",
        "v4l2src", "device=/dev/video0", "!",
        "videoconvert", "!",
        "x264enc", "tune=zerolatency", "bitrate=500", "speed-preset=superfast", "!",
        "rtph264pay", "!",
        "udpsink", "host=hc-task02.local", "port=5000",
    ]

def rec_start():
    global recording
    # 例外時も安全に扱う
    try:
        recording = subprocess.Popen(gst_command)
    except Exception as e:
        print(f"[rec_start error] {e}", file=sys.stderr)
        recording = None

def video_start():
    global recording
    try:
        recording = subprocess.Popen(video_command)
    except Exception as e:
        print(f"[video_start error] {e}", file=sys.stderr)
        recording = None

def rec_end():
    global recording
    if recording is None:
        print("[rec_end] recording is None (already stopped?)")
        return
    try:
        recording.send_signal(signal.SIGINT)
        recording.wait(timeout=10)
    except Exception as e:
        print(f"[rec_end error] {e}", file=sys.stderr)
    finally:
        recording = None

# ---- 転送（別スレッドで実行） ----
def transfer_start():
    """
    Windowsへのコピー → （任意）終了後の移動。
    終了時は transfer_done_evt を必ず set() する。
    """
    try:
        # 必要なら Python実行環境を明示（sys.executable）
        py = sys.executable
        code_dir = Path("C:/Users/EtoHayato/Desktop/git_repository/hc-task/homecage-task/code").resolve()
        # 例: Pi→Win コピー
        subprocess.run([py, str(code_dir / "pi2win.py")], check=True)
    except subprocess.CalledProcessError as e:
        print(f"[transfer_start error] {e}", file=sys.stderr)
    except Exception as e:
        print(f"[transfer_start unexpected] {e}", file=sys.stderr)
    finally:
        # 転送完了通知（成功・失敗問わず）
        transfer_done_evt.set()

def touch_disable():
    """
    転送中の操作無効画面。Sキーで sd_mode をオン。
    ESC または転送完了で終了。終了後に file_move.py を実行。
    """
    global sd_mode

    # Pygame 初期化
    pygame.init()
    info = pygame.display.Info()
    screen = pygame.display.set_mode((info.current_w, info.current_h), pygame.FULLSCREEN)
    pygame.display.set_caption("転送中 - 操作無効")

    # 入力グラブ（必要に応じて有効化）:
    # pygame.event.set_grab(True)

    # 背景とテキスト
    screen.fill((0, 0, 0))
    font = pygame.font.SysFont(None, 60)
    text = font.render("データ転送中です。操作は無効です。", True, (255, 255, 255))
    text_rect = text.get_rect(center=(info.current_w // 2, info.current_h // 2))
    screen.blit(text, text_rect)
    pygame.display.flip()

    # 転送状態をリセット
    transfer_done_evt.clear()

    # 別スレッドでSCP転送実行
    t = threading.Thread(target=transfer_start, daemon=True)
    t.start()

    running = True
    clock = pygame.time.Clock()

    while running:
        # イベント処理
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False  # ESCで終了
                elif event.key == pygame.K_s:
                    # Sキーで sd_mode を ON
                    sd_mode = True
                    screen.fill((0, 0, 0))
                    msg = font.render("sd_mode", True, (255, 255, 255))
                    rect = msg.get_rect(center=(info.current_w // 2, info.current_h // 2))
                    screen.blit(msg, rect)
                    pygame.display.update()
                else:
                    # 他のキーは何もしない（無視）
                    pass

            elif event.type == pygame.KEYUP:
                # 一部環境で KEYUP のみ届く場合の保険
                if event.key == pygame.K_ESCAPE:
                    running = False

            elif event.type == pygame.MOUSEBUTTONDOWN:
                # クリックは無視（何もしない）
                pass

        # 取りこぼし保険：ESCが押されっぱなしなら終了
        keys = pygame.key.get_pressed()
        if keys[pygame.K_ESCAPE]:
            running = False

        # 転送完了で自動終了
        if transfer_done_evt.is_set():
            running = False

        clock.tick(30)  # 30FPS程度

    pygame.quit()

    # 転送終了後のファイル移動
    try:
        py = sys.executable
        code_dir = Path("C:/Users/EtoHayato/Desktop/git_repository/hc-task/homecage-task/code").resolve()
        subprocess.run([py, str(code_dir / "file_move.py")], check=True)
    except Exception as e:
        print(f"[file_move error] {e}", file=sys.stderr)

def shut_down():
    try:
        subprocess.run(["sudo", "shutdown", "-h", "now"], check=True)
    except Exception as e:
        print(f"[shutdown error] {e}", file=sys.stderr)
