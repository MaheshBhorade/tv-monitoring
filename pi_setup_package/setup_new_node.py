import os
import sys
import paramiko
import json
import time

def deploy_new_pi():
    print("==================================================")
    print("🚀 AUTOMATED TV MONITORING EDGE NODE DEPLOYER")
    print("==================================================")
    
    # 1. Prompt user for target Pi connection credentials
    host = input("🔌 Enter the IP address of the new Pi (e.g. 100.85.114.118): ").strip()
    if not host:
        print("❌ IP address is required!")
        return
        
    user = input("👤 Enter SSH username (default: 'indi'): ").strip() or "indi"
    password = input("🔑 Enter SSH password (default: 'iNdI#@R-71!0'): ").strip() or "iNdI#@R-71!0"
    
    # 2. Prompt for node metadata config
    device_id = input("🏷️ Enter a unique Device ID (e.g. PI_OFFICE_02): ").strip()
    if not device_id:
        print("❌ Device ID is required!")
        return
        
    location = input("📍 Enter Device Location (e.g. Office Corridor 1): ").strip()
    if not location:
        print("❌ Location is required!")
        return
        
    # Standard server IP (Your laptop's permanent Tailscale IP)
    laptop_tailscale_ip = "100.78.128.49"
    server_url = f"http://{laptop_tailscale_ip}:8000"
    
    print("\n📦 Generating remote directories and configs...")
    
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        # Connect to the target Pi
        ssh.connect(host, username=user, password=password, timeout=12)
        print(f"✅ Connected to target Pi at {host} successfully!")
        
        # 3. Create required directories
        print("📁 Creating installation directory /opt/apm/TF_Lite_img_processing/...")
        ssh.exec_command("sudo mkdir -p /opt/apm/TF_Lite_img_processing/local_cache")
        ssh.exec_command("sudo chmod -R 777 /opt/apm")
        time.sleep(1)
        
        # 4. Open SFTP client to transfer files
        sftp = ssh.open_sftp()
        
        # Upload active pi_capture_uploader.py
        local_dir = os.path.dirname(os.path.abspath(__file__))
        local_uploader = os.path.join(local_dir, "pi_capture_uploader.py")
        remote_uploader = "/opt/apm/TF_Lite_img_processing/pi_capture_uploader.py"
        
        print("📤 Uploading edge capture core...")
        sftp.put(local_uploader, remote_uploader)
        
        # Generate custom device_config.json locally first
        local_config = os.path.join(local_dir, "device_config.json")
        config_data = {
            "server_url": server_url,
            "device_id": device_id,
            "device_location": location,
            "capture_mode": "both",
            "capture_interval": 5.0,
            "video_duration": 60.0
        }
        with open(local_config, "w") as f:
            json.dump(config_data, f, indent=2)
            
        # Upload custom device_config.json
        remote_config = "/opt/apm/TF_Lite_img_processing/device_config.json"
        print("📤 Uploading personalized node configuration...")
        sftp.put(local_config, remote_config)
        sftp.close()
        
        # Clean up temporary local config file
        if os.path.exists(local_config):
            os.remove(local_config)

        # 5. Create Systemd Autostart Service on the Pi!
        print("⚙️ Registering tv_capture autostart service daemon on the Pi...")
        service_content = f"""[Unit]
Description=TV Monitoring Edge Capture Daemon
After=network.target tailscale.service

[Service]
Type=simple
User={user}
WorkingDirectory=/opt/apm/TF_Lite_img_processing
ExecStart=/usr/bin/python3 -u /opt/apm/TF_Lite_img_processing/pi_capture_uploader.py
Restart=always
RestartSec=5
StandardOutput=syslog
StandardError=syslog
SyslogIdentifier=tv_capture

[Install]
WantedBy=multi-user.target
"""
        # Write the service file remotely
        stdin, stdout, stderr = ssh.exec_command(
            f"echo '{service_content}' | sudo tee /etc/systemd/system/tv_capture.service"
        )
        stdout.read() # Wait for command to finish
        
        # Enable and reload the systemd daemon
        print("🔄 Enabling and starting tv_capture.service...")
        ssh.exec_command("sudo systemctl daemon-reload")
        ssh.exec_command("sudo systemctl enable tv_capture.service")
        ssh.exec_command("sudo systemctl restart tv_capture.service")
        
        # 6. Verify if service successfully launched
        time.sleep(2)
        stdin, stdout, stderr = ssh.exec_command("sudo systemctl is-active tv_capture.service")
        status = stdout.read().decode('utf-8').strip()
        
        print("\n==================================================")
        if status == "active":
            print(f"🎉 SUCCESS! {device_id} DEPLOYED AND RUNNING!")
            print(f"📍 Location: {location}")
            print(f"📡 Target Server: {server_url}")
            print("🚀 The capture engine is now active and will autostart on boot!")
        else:
            print("⚠️ Deployment complete but service is inactive.")
            print("Run 'sudo systemctl status tv_capture.service' on the Pi to check.")
        print("==================================================")
        
    except Exception as e:
        print(f"\n❌ Error deploying to Pi: {e}")
    finally:
        ssh.close()

if __name__ == "__main__":
    deploy_new_pi()
