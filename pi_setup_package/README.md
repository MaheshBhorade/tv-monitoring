# 🍓 Automated Raspberry Pi Node Setup Package

This package allows you to instantly configure, deploy, and register new Raspberry Pi TV monitoring edge nodes to your private secure Tailnet in 30 seconds.

---

## 📂 Package Contents
* **`setup_new_node.py`**: The master Python automation script to deploy, configure, and register the node.
* **`pi_capture_uploader.py`**: The high-performance HDMI/audio hardware capture uploader script.

---

## ⚡ Deployment Instructions (30 Seconds)

Ensure your laptop is connected to your **Tailscale VPN** and can ping the target Pi (locally or via Tailscale).

1. **Open your terminal/PowerShell** on your laptop.
2. Navigate into this setup folder:
   ```powershell
   cd "d:\AI ARC\pi_setup_package"
   ```
3. Run the installer:
   ```powershell
   python setup_new_node.py
   ```
4. **Enter the credentials and info as prompted**:
   * **🔌 Pi IP**: (e.g. `100.85.114.118` or local IP `192.168.1.106`)
   * **👤 SSH User**: (defaults to `indi` if you press Enter)
   * **🔑 SSH Pass**: (defaults to `iNdI#@R-71!0` if you press Enter)
   * **🏷️ unique Device ID**: (e.g. `PI_RETAIL_02`)
   * **📍 Location**: (e.g. `Mumbai Hub Entrance`)

---

## 🛡️ Under the Hood (What the Script Automates):
1. **Creates Directory Structures**: Sets up `/opt/apm/TF_Lite_img_processing/` with full read/write permissions.
2. **Syncs Code & Personal Configs**: Transfers the uploader core and dynamically compiles the `device_config.json` pre-linked to your laptop's permanent Tailnet IP `100.78.128.49`.
3. **Creates a System Daemon Service**: Generates `/etc/systemd/system/tv_capture.service` so that the capture script runs silently in the background and **autostarts automatically whenever the Pi boots up!**
4. **Instantly Starts Streaming**: Triggers the systemd daemon to immediately connect and broadcast to your dashboard.
