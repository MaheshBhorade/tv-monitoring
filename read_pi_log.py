import paramiko

def test_public_dns():
    host = "192.168.1.105"
    user = "indi"
    password = "iNdI#@R-71!0"
    
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(host, username=user, password=password, timeout=10)
        print("Connected to Pi!")
        
        # Test DNS resolution bypassing local Tailscale/router DNS by asking Google DNS (8.8.8.8) directly
        print("\nQuerying Google Public DNS (8.8.8.8) directly for your tunnel...")
        stdin, stdout, stderr = ssh.exec_command("nslookup male-classical-documents-individual.trycloudflare.com 8.8.8.8")
        print(stdout.read().decode('utf-8', errors='ignore'))
        print(stderr.read().decode('utf-8', errors='ignore'))
        
    except Exception as e:
        print(f"Error executing test: {e}")
    finally:
        ssh.close()

if __name__ == "__main__":
    test_public_dns()
