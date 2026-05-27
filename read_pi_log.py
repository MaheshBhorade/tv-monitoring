import paramiko

def read_pi_curl():
    host = "100.85.114.118"
    user = "indi"
    password = "iNdI#@R-71!0"
    
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(host, username=user, password=password, timeout=10)
        print("Connected to Pi!")
        
        # 1. Test curl directly to port 8000 over Tailscale
        print("\n=== CURL TEST FROM PI TO LAPTOP PORT 8000 ===")
        stdin, stdout, stderr = ssh.exec_command("curl -m 5 -v http://100.78.128.49:8000/api/devices")
        print("STDOUT:")
        print(stdout.read().decode('utf-8', errors='ignore'))
        print("STDERR:")
        print(stderr.read().decode('utf-8', errors='ignore'))
        
        # 2. Check Pi's Tailscale Peer Status
        print("\n=== PI TAILSCALE PEER STATUS ===")
        stdin, stdout, stderr = ssh.exec_command("tailscale status")
        print(stdout.read().decode('utf-8', errors='ignore'))
        
    except Exception as e:
        print(f"Error checking status: {e}")
    finally:
        ssh.close()

if __name__ == "__main__":
    read_pi_curl()
