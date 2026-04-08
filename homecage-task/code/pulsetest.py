# touch_rect_v4_outside_fail.py
import math, random, array
import keyboard

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


def on_press_a(event):
    print("pressed a")

# =========================
# Main
# =========================
def run():
    ttl = ArduinoTTLSender(port="COM4")
    print("enterを押すとパルスを出力")
    while True:
        keyboard.wait('enter')
        ttl.pulse()

    ttl.close()

if __name__ == "__main__":
    run()
