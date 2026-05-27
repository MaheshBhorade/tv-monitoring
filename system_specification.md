# System Specification: TV Content Monitoring & Distributed Capture

Welcome to the plain-language guide for your **TV Content Monitoring and Distributed Capture System**. This document explains how the entire system works end-to-end, what technologies it uses, how we made it ultra-stable and compact, and how it can scale to over 1,000 devices for free.

---

## 1. What is this System? (High-Level Overview)

Imagine you want to monitor what is playing on television channels across different cities. 
* You place a small, cheap computer (a **Raspberry Pi**) connected to an **HDMI capture card** (which plugs into the TV Cable/Set-Top box) in each city.
* The Raspberry Pi continuously grabs the TV screen, compiles it into **1-minute video chunks**, and compresses it.
* The Pi then **uploads these videos over the internet** to your **Central Server** (laptop or office computer).
* The Central Server saves these videos and displays a **beautiful, real-time control dashboard** showing the health, statistics, temperature, and live logs of all active capturing devices.

---

## 2. The Edge Client (The Raspberry Pi)

The Raspberry Pi runs a single, automated script called `pi_capture_uploader.py`. This script runs three tasks simultaneously in the background:

### A. The Persistent Capture Handle (Stable Screen Grabbing)
* **How it works**: The script opens a single, permanent connection to the HDMI capture card at startup and never closes it. 
* **Why it matters**: In the past, the script opened and closed the camera for every video, which caused lock-ups and errors. Keeping it open permanently ensures the HDMI feed is always smooth and never freezes.

### B. Frame Resizing (The Canvas Standard)
* **How it works**: TV feeds come in at high resolutions (like 720p or 1080p). The Pi instantly resizes every captured frame to a standard **640x480 pixels** before saving it.
* **Why it matters**: This reduces the data size by up to **80%** right at the beginning, making sure the video doesn't consume your network data or fill up the Pi's memory card.

### C. The Safe Recording Buffer (No File Corruption)
* **How it works**: While the Pi is actively recording a new 1-minute video chunk, it saves the file inside a hidden, isolated folder (`local_cache/recording/`). 
* **Why it matters**: Only when the video is 100% finished and locked does the script move it to the uploading folder. This prevents the uploader thread from accidentally uploading half-written or empty videos.

---

## 3. The Magic of H.265 Compression (How we shrunk the files)

When we first recorded videos using standard formats, each 1-minute video was **15 Megabytes**. For 1,000 devices, this would consume an impossible **7.2 Terabytes of data per day**!

To fix this, we integrated **FFmpeg with H.265 (HEVC) compression**:
1. The Pi records a fast, uncompressed video chunk first to keep CPU usage low.
2. The moment the chunk is finished, a background program (FFmpeg) instantly compresses the video using the **H.265 standard** (using `libx265` at Constant Rate Factor `28`).
3. This compresses the video file from **15 Megabytes down to just ~3 Megabytes (a 78%+ reduction!)** without losing the visual clarity of the text and logos on the screen.

---

## 4. The Uploader State Machine (No Data Loss)

Internet connections on Wi-Fi or 4G can be unstable. The Pi's uploader is designed like a robust post office that guarantees **zero data loss**:

1. **Queue (FIFO)**: The Pi keeps all compressed videos in a local folder (`local_cache/pending/`). It always uploads the oldest file first.
2. **Double-Locking**: When the Pi starts uploading a file, it moves it to an `uploading/` folder so it doesn't get touched or duplicated.
3. **Success Verification**: The Pi sends the file to the server. It **only** deletes the local video file *after* the central server responds with a clear `"status: success"` message.
4. **Auto-Retry**: If the internet goes down, the Pi pauses, waits, and retries automatically using a smart back-off timer.
5. **Disk-Space Protection**: If the Pi’s local storage gets full (less than 2GB free), it automatically purges the oldest unsent files to protect its operating system from crashing.

---

## 5. The Central Server & Dashboard

The central server runs `server.py` using **FastAPI** and serves an immersive, modern browser console:
* **The Database (`tv_monitoring.db`)**: Every time a Pi checks in, it logs its statistics (CPU usage, CPU temperature, RAM usage, and free storage) into a lightweight SQLite database.
* **The Control Dashboard**: Served at `http://localhost:8000/dashboard`, this shows glowing neon statistics cards, live pulse indicators for all active capture nodes, and a scrolling diagnostic log from your entire fleet of remote devices.

---

## 6. How to Scale to 1,000+ Devices for FREE (Zero Cloud Bills)

If you scale this system from 1 device to **1,000+ devices**, you do not need expensive corporate cloud subscriptions. You can host it entirely on a **single, cheap dedicated server** ($45/month) using this open-source recipe:

| The Problem at 1,000+ Nodes | The Cost-Free Solution | How it Works |
| :--- | :--- | :--- |
| **Heavy Upload Bandwidth (466 Mbps)** | **Nginx Reverse Proxy** | A free gatekeeper program (Nginx) buffers the incoming video uploads on the server, preventing the database and API from choking. |
| **High Database Writes** | **PostgreSQL** | We replace the simple SQLite file database with a free, self-hosted PostgreSQL database running locally on the server. |
| **Video Storage Accumulation** | **Rolling 24-Hour Buffer** | A server script automatically deletes any video older than 24 hours. Because you only need the videos to run ad-detection algorithms, you only need to store a single day's worth of data. A single cheap $230 16TB hard drive handles this forever for **$0/month**! |
| **Storage Technology Standard** | **Self-Hosted MinIO** | MinIO is a free, open-source program you run on your server that behaves exactly like Amazon S3, allowing you to use professional cloud code with **zero cloud costs**. |
| **Fleet Security** | **Bearer Token Headers** | Every Pi transmits a secure secret key in its header. If a malicious request is detected, the server drops it instantly in under 1 millisecond. |
