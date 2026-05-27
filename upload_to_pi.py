import paramiko
import os
import json

def upload():
    host = "192.168.1.105"
    user = "indi"
    password = "iNdI#@R-71!0"
    
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(host, username=user, password=password, timeout=10)
        print("Connected to Raspberry Pi successfully!")
        
        # Open SFTP client
        sftp = ssh.open_sftp()
        
        # 1. Upload updated capture code
        local_uploader = r"d:\AI ARC\pi_capture_uploader.py"
        remote_uploader = "/opt/apm/TF_Lite_img_processing/pi_capture_uploader.py"
        print(f"Syncing edge capture code to: {remote_uploader}...")
        sftp.put(local_uploader, remote_uploader)
        
        # 2. Generate local device_config.json on Windows first
        local_config = r"d:\AI ARC\device_config.json"
        config_data = {
            "server_url": "https://male-classical-documents-individual.trycloudflare.com",
            "device_id": "PI_OFFICE_01",
            "device_location": "Office Testing Room",
            "capture_mode": "both",
            "capture_interval": 5.0,
            "video_duration": 60.0
        }
        with open(local_config, "w") as f:
            json.dump(config_data, f, indent=2)
            
        # 3. Upload device_config.json to the Pi
        remote_config = "/opt/apm/TF_Lite_img_processing/device_config.json"
        print(f"Creating remote config file at: {remote_config}...")
        sftp.put(local_config, remote_config)
        
        print("SUCCESS: Successfully synchronized all files on the Pi!")
        sftp.close()
        
    except Exception as e:
        print(f"ERROR syncing files: {e}")
    finally:
        ssh.close()

if __name__ == "__main__":
    upload()
