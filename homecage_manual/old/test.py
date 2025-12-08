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


host = "pi4.local" #ホスト名
port = 22
username = "user"
password = "user"
remote_path="/home/user/Desktop/" 
local_path=".\\homecage-task" 

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(host,port=port,username=username,password=password)
with SCPClient(ssh.get_transport()) as scp:
    scp.put(local_path , remote_path , recursive=True)
    
ssh.close()