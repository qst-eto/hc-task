import pygame
import subprocess
import threading
import sys
import signal
from datetime import datetime

dt=datetime.now()
datetime_str=dt.strftime("%Y-%m-%d")
pass_name="location=/home/user/Desktop/homecage-task/logs/"+datetime_str+"_video.mp4"


# フラグ
transfer_done = False

#第一引数に実行スクリプトを入力

#録画開始-----------------------
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

recording = subprocess.Popen(gst_command)

#------------------------------

args=sys.argv[1:]

script_name = args[0]
print(script_name)

script_args = args[1:]

subprocess.run(['python', script_name] + script_args)


#実験スクリプト終了-----------------


recording.send_signal(signal.SIGINT)
recording.wait()


#OC script----------------------

def run_scp():
    global transfer_done
    subprocess.run(["python", "./code/pi2win.py"])
    import time
    time.sleep(5)  # ダミー転送時間
    transfer_done = True  # 転送完了を通知

# --- Pygame 初期化 ---
pygame.init()
info = pygame.display.Info()
screen = pygame.display.set_mode((info.current_w, info.current_h), pygame.FULLSCREEN)
pygame.display.set_caption("転送中 - 操作無効")

# 背景とテキスト
screen.fill((0, 0, 0))
font = pygame.font.SysFont(None, 60)
text = font.render("データ転送中です。操作は無効です。", True, (255, 255, 255))
text_rect = text.get_rect(center=(info.current_w // 2, info.current_h // 2))
screen.blit(text, text_rect)
pygame.display.flip()

# 別スレッドでSCP転送実行
threading.Thread(target=run_scp, daemon=True).start()

# イベントループ
running = True
while running:
    for event in pygame.event.get():
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            running = False  # ESCで終了
        elif event.type in [pygame.MOUSEBUTTONDOWN, pygame.KEYDOWN]:
            pass  # 無視

    # 転送完了チェック
    if transfer_done:
        running = False

    pygame.time.wait(100)

pygame.quit()

subprocess.run(["sudo", "shutdown", "-h", "now"])
