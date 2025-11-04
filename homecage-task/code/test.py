import sys
import subprocess

#第一引数に実行スクリプトを入力

#録画開始-----------------------
gst_command = [
    "gst-launch-1.0", "--eos-on-shutdown",
    "v4l2src", "device=/dev/video0", "!", "tee", "name=t",
    "t.", "!", "queue", "!", "videoconvert", "!", "x264enc",
    "tune=zerolatency", "bitrate=500", "speed-preset=superfast",
    "!", "rtph264pay", "!", "udpsink", "host=192.168.1.100", "port=5000",
    "t.", "!", "queue", "!", "videoconvert", "!", "x264enc",
    "bitrate=1000", "speed-preset=ultrafast",
    "!", "mp4mux", "faststart=true",
    "!", "filesink", "location=recorded_video.mp4", "sync=true"
]

recording = subprocess.Popen(gst_command)

#------------------------------

args=sys.argv[1:]

script_name = args[0]
print(script_name)

script_args = args[1:]

subprocess.run(['python', script_name] + script_args)


#実験スクリプト終了-----------------

recording.terminate()
recording.wait()

subprocess.run(["python", "log_copy.py"])
subprocess.run(["sudo", "shutdown", "-h", "now"])