import subprocess
import sys

try:
    import paramiko
except ImportError:
    print("paramikoが見つかりません。インストールを開始します")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "paramiko"])
    import paramiko
try:
    from scp import SCPClient
except ImportError:
    print("SCPClientが見つかりません。インストールを開始します")
    subprocess.check_call([sys.executable, "-m", "pip", "install", "scp"])
    from scp import SCPClient


host = "hc-task01.local" #ホスト名 or IP
port = 22
username = "user" #接続先のユーザー名
password = "user" #接続先のパスワード
ras_path="/home/user/Desktop/homecage-task/logs" #logファイルのパス
win_path="C:/Users/user/Desktop" #保存先のパス

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(host,port=port,username=username,password=password)
with SCPClient(ssh.get_transport()) as scp:
    scp.put(ras_path , win_path , recursive=True)
    
ssh.close()