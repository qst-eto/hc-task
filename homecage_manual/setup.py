import subprocess
import sys
arg=sys.argv

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

host = arg[1] #ホスト名
port = 22
username = arg[2]
password = arg[3]
local_script="setup.sh"
remote_script="/tmp/setup.sh"

remote_path="/home/user/Desktop/" 
local_path=".\\homecage-task" 

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(host, port=port, username=username, password=password)

with SCPClient(ssh.get_transport()) as scp:
    scp.put(local_path , remote_path , recursive=True)

sftp = ssh.open_sftp()
sftp.put(local_script, remote_script)
sftp.chmod(remote_script, 0o775)

sftp.close()

stdin, stdout, stderr = ssh.exec_command("stdbuf -oL bash /tmp/setup.sh")

for line in iter(stdout.readline, ""):
    print(line.strip())
errors = stderr.read().decode()
if errors:
    print(errors)
    
ssh.close()