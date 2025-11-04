import pygame
import subprocess
import threading
import sys

def run_scp():
    # SCPコマンドを実行（例：ファイル転送）
    subprocess.run(["python3", "pi2win.py"])

    # 転送終了後にPygameを終了
    pygame.quit()
    sys.exit()

# Pygame初期化
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

# SCP転送を別スレッドで実行
threading.Thread(target=run_scp).start()

# イベントループ（ESCキー以外は無視）
while True:
    for event in pygame.event.get():
        if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
            pygame.quit()
            sys.exit()
        elif event.type in [pygame.MOUSEBUTTONDOWN, pygame.KEYDOWN]:
            pass  # 無視

    pygame.time.wait(100)
