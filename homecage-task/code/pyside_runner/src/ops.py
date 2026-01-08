
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

# 転送設定（初期値）
transfer_cfg = {
    "host": "hc-task02.local",
    "port": 22,
    "username": "user",
    "password": "user",
    "ras_path": "./logs",  # Pi側のログフォルダ
    "win_path": "C:/Users/user/Desktop/logs/280",  # Windows側の保存先
}

def set_transfer_config(
    host=None, port=None, username=None, password=None,
    ras_path=None, win_path=None
):
    """UIから渡された転送設定を反映（Noneは無視）。"""
    if host is not None: transfer_cfg["host"] = host
    if port is not None: transfer_cfg["port"] = int(port)
    if username is not None: transfer_cfg["username"] = username
    if password is not None: transfer_cfg["password"] = password
    if ras_path is not None: transfer_cfg["ras_path"] = ras_path
    if win_path is not None: transfer_cfg["win_path"] = win_path

# 転送完了通知（Event）
transfer_done_evt = threading.Event()

def rec_standby():
    global gst_command, video_command

    dt = datetime.now()
    datetime_str = dt.strftime("%Y-%m-%d")
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
    """Pi→Windows 転送。終了時は transfer_done_evt を必ず set()。"""
    try:
        pi2win()  # 設定は transfer_cfg を使用
    except Exception as e:
        print(f"[transfer_start error] {e}", file=sys.stderr)
    finally:
        transfer_done_evt.set()

def touch_disable():
    """
    転送中の操作無効画面。Sキーで sd_mode をON。
    ESC または転送完了で終了。終了後に file_move() を実行。
    """
    global sd_mode

    pygame.init()
    info = pygame.display.Info()
    screen = pygame.display.set_mode((info.current_w, info.current_h), pygame.FULLSCREEN)
    pygame.display.set_caption("転送中 - 操作無効")

    screen.fill((0, 0, 0))
    font = pygame.font.SysFont(None, 60)
    text = font.render("データ転送中です。操作は無効です。", True, (255, 255, 255))
    text_rect = text.get_rect(center=(info.current_w // 2, info.current_h // 2))
    screen.blit(text, text_rect)
    pygame.display.flip()

    transfer_done_evt.clear()
    t = threading.Thread(target=transfer_start, daemon=True)
    t.start()

    running = True
    clock = pygame.time.Clock()

    while running:
        for event in pygame.event.get():
            if event.type == pygame.QUIT:
                running = False

            elif event.type == pygame.KEYDOWN:
                if event.key == pygame.K_ESCAPE:
                    running = False
                elif event.key == pygame.K_s:
                    sd_mode = True
                    screen.fill((0, 0, 0))
                    msg = font.render("sd_mode", True, (255, 255, 255))
                    rect = msg.get_rect(center=(info.current_w // 2, info.current_h // 2))
                    screen.blit(msg, rect)
                    pygame.display.update()

            elif event.type == pygame.KEYUP:
                if event.key == pygame.K_ESCAPE:
                    running = False

        # 取りこぼし保険
        if pygame.key.get_pressed()[pygame.K_ESCAPE]:
            running = False

        # 転送完了で終了
        if transfer_done_evt.is_set():
            running = False

        clock.tick(30)

    pygame.quit()

    # 転送終了後のファイル移動
    try:
        file_move()  # ras_path に応じた元フォルダから backup へ移動
    except Exception as e:
        print(f"[file_move error] {e}", file=sys.stderr)

def shut_down():
    try:
        subprocess.run(["sudo", "shutdown", "-h", "now"], check=True)
    except Exception as e:
        print(f"[shutdown error] {e}", file=sys.stderr)

# ---- Pi→Windows 転送本体 ----
def pi2win():
    """transfer_cfg に基づいて Pi→Windows へ SCP で転送。"""
    try:
        import paramiko
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko"])
        import paramiko

    try:
        from scp import SCPClient
    except ImportError:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "scp"])
        from scp import SCPClient

    host = transfer_cfg["host"]
    port = int(transfer_cfg["port"])
    username = transfer_cfg["username"]
    password = transfer_cfg["password"]
    ras_path = transfer_cfg["ras_path"]
    win_path = transfer_cfg["win_path"]

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(host, port=port, username=username, password=password)

    # ras_path がディレクトリの場合は中身を保存先へ。recursive=True でディレクトリごと転送可能。
    with SCPClient(ssh.get_transport()) as scp:
        scp.put(ras_path, win_path, recursive=True)

    ssh.close()

# ---- 転送後のファイル移動（バックアップへ） ----
def file_move():
    """
    ras_path 内のファイルを ras_path と同階層の '<フォルダ名>_backup' へ移動。
    例：/home/.../logs -> /home/.../logs_backup
    """
    import os
    import shutil

    src_dir = Path(transfer_cfg["ras_path"]).resolve()
    dst_dir = src_dir.with_name(src_dir.name + "_backup")

    dst_dir.mkdir(parents=True, exist_ok=True)

    # src_dir 直下のファイル・フォルダをすべて移動
    for name in os.listdir(src_dir):
        src = src_dir / name
        dst = dst_dir / name
        try:
            shutil.move(str(src), str(dst))
        except Exception as e:
            print(f"[file_move warn] move failed for {src}: {e}", file=sys.stderr)
