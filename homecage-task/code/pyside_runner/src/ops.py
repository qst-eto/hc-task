import pygame
import subprocess
import threading
import sys
import signal
from datetime import datetime

def rec_standby():
    from datetime import datetime 
    global gst_command, video_command

    dt=datetime.now()
    datetime_str=dt.strftime("%Y-%m-%d")
    pass_name="location=/home/user/Desktop/homecage-task/logs/"+datetime_str+"_video.mp4"
    
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
        "gst-launch-1.0", "v4l2src", "device=/dev/video0", "!",
        "videoconvert", "!",
        "x264enc", "tune=zerolatency", "bitrate=500", "speed-preset=superfast", "!",
        "rtph264pay" "!"
        "udpsink", "host=hc-task02.local", "port=5000"
    ]

def rec_start():
    global recording
    recording = subprocess.Popen(gst_command)
    
def video_start():
    global recording
    recording = subprocess.Popen(video_command)

def rec_end():
    global recording
    recording.send_signal(signal.SIGINT)
    recording.wait()

def transfer_start():
    global transfer_done,sd_mode

    subprocess.run(["python", "./code/pi2win.py"])
    import time
    transfer_done = True  # 転送完了を通知
    
def touch_disable():

    global sd_mode

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
    threading.Thread(target=transfer_start, daemon=True).start()

# イベントループ
    running = True
    while running:
        for event in pygame.event.get():

            if event.type == pygame.KEYDOWN and event.key == pygame.K_s: #Sキーを入力するとSDmodeをオンにする
                sd_mode=True
                screen.fill((0, 0, 0))
                font = pygame.font.SysFont(None, 60)
                text = font.render("sd_mode", True, (255, 255, 255))
                text_rect = text.get_rect(center=(info.current_w // 2, info.current_h // 2))
                screen.blit(text, text_rect)
                pygame.display.update()
		
            if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                running = False  # ESCで終了
            elif event.type in [pygame.MOUSEBUTTONDOWN, pygame.KEYDOWN]:
                pass  # 無視

    # 転送完了チェック
        if transfer_done:
            running = False

        pygame.time.wait(100)

    pygame.quit()

    subprocess.run(["python", "./code/file_move.py"])

def shut_down():
    subprocess.run(["sudo", "shutdown", "-h", "now"])





