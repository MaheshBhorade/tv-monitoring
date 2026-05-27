# 🔒 Securing Your IoT Fleet with Tailnet (Tailscale)

This document provides step-by-step instructions for establishing a private, encrypted **Tailnet overlay network** to link 1,000+ geographical capture devices directly to your central laptop console without exposing any ports to the public internet.

---

## 🏗️ How it Works

Tailscale creates a secure, peer-to-peer WireGuard virtual private network (VPN).
* **The Pi** is already configured as a node in the Tailnet.
* **Your Laptop** will join the same Tailnet.
* Once both are connected, they are assigned permanent **`100.x.x.x`** static IPs. The Pi can stream data directly to your laptop over this private encrypted connection, even if the Pi is on the office network and your laptop is on an iPhone hotspot!

```mermaid
graph LR
    subgraph Tailnet Private VPN (100.x.x.x)
        Pi[Raspberry Pi - Office WiFi]
        Laptop[Laptop Console - iPhone Hotspot]
    end
    
    Pi -- "Direct Peer-to-Peer Stream (Port 8000)" --> Laptop
```

---

## 🛠️ Step-by-Step Integration Plan

### 💻 Step 1: Install Tailscale on Your Windows Laptop
1. Download the free, official installer from: **`https://tailscale.com/download/windows`**
2. Run the installer and sign in with the **same Tailscale/Google account** that your Raspberry Pi is logged into.
3. Once logged in, open your command prompt on your laptop and run:
   ```cmd
   tailscale ip -4
   ```
4. Copy your laptop's permanent static **Tailscale IP address** (it will look like `100.x.x.x`, e.g. `100.98.45.12`).

---

### 📡 Step 2: Configure Your Pi to Stream via Tailnet
Now that your laptop has a permanent Tailnet IP, let's update your Pi's configuration file:

📁 **`/opt/apm/TF_Lite_img_processing/device_config.json`**
```json
{
  "server_url": "http://YOUR_LAPTOP_TAILSCALE_IP:8000",
  "device_id": "PI_OFFICE_01",
  "device_location": "Office Testing Room",
  "capture_mode": "both",
  "capture_interval": 5.0,
  "video_duration": 60.0
}
```
*(Replace `YOUR_LAPTOP_TAILSCALE_IP` with the `100.x.x.x` IP address you copied in Step 1!)*

---

### 🚀 Step 3: Run the System Locally & Private!

1. **Start the server on your Laptop**:
   ```powershell
   uvicorn server:app --host 0.0.0.0 --port 8000 --reload
   ```
2. **Start the capture script on the Pi**:
   ```bash
   python3 /opt/apm/TF_Lite_img_processing/pi_capture_uploader.py
   ```
3. **Open the Dashboard privately**:
   Go to `http://YOUR_LAPTOP_TAILSCALE_IP:8000/dashboard` in your browser!

---

### 🛡️ Core Security Perks
* **Zero Port Exposure**: You do not have to expose port `8000` to the public internet anymore.
* **Firewall Bypass**: Works naturally across restricted office networks, mobile hotspots, and double NATs.
* **100% Free**: Tailscale is free for up to 3 users and 100 devices on their personal tier!
