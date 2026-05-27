import os
import cv2
import time
import socket
import shutil
import threading
import subprocess
import requests
from datetime import datetime
import numpy as np
from typing import List, Dict

# Try loading optional psutil for accurate metrics, or mock gracefully
try:
    import psutil
except ImportError:
    psutil = None

# CLIENT CONFIGURATION (Can be expanded with dotenv)
SERVER_URL = "http://192.168.1.52:8000"
DEVICE_ID = "PI001"
CAPTURE_MODE = "both"  # "image", "video", or "both"
CAPTURE_INTERVAL = 5.0  # Captures a static frame every 5 seconds in 'both' mode
VIDEO_CHUNK_DURATION = 60.0  # 1-minute chunks for video mode

CACHE_DIR = "local_cache"
PENDING_DIR = os.path.join(CACHE_DIR, "pending")
UPLOADING_DIR = os.path.join(CACHE_DIR, "uploading")
FAILED_DIR = os.path.join(CACHE_DIR, "failed")
UPLOADED_DIR = os.path.join(CACHE_DIR, "uploaded")

# Ensure queue folders exist
for folder in [PENDING_DIR, UPLOADING_DIR, FAILED_DIR, UPLOADED_DIR]:
    os.makedirs(folder, exist_ok=True)

# In-memory logging buffer to batch upload logs to server console
log_queue: List[Dict] = []
log_lock = threading.Lock()

def edge_log(level: str, message: str):
    """Queues a log entry locally and prints it to the console."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] [{level}] {message}")
    
    with log_lock:
        log_queue.append({
            "level": level,
            "message": message
        })

# DYNAMIC Telemetry helpers
def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

def get_disk_free_gb():
    try:
        total, used, free = shutil.disk_usage(".")
        return free / (1024 * 1024 * 1024)
    except Exception:
        return 0.0

def get_cpu_usage():
    if psutil:
        return psutil.cpu_percent()
    return 15.0 + np.random.uniform(-5.0, 5.0)  # Safe mock

def get_cpu_temp():
    # Attempt to read Pi CPU thermal zone
    try:
        if os.path.exists("/sys/class/thermal/thermal_zone0/temp"):
            with open("/sys/class/thermal/thermal_zone0/temp", "r") as f:
                temp_raw = int(f.read().strip())
                return temp_raw / 1000.0
    except Exception:
        pass
    # Windows/Fallback mock
    return 45.0 + np.random.uniform(-3.0, 3.0)

def get_ram_usage():
    if psutil:
        return psutil.virtual_memory().percent
    return 35.0 + np.random.uniform(-5.0, 5.0)  # Safe mock


# HEARTBEAT TELEMETRY THREAD
def heartbeat_worker():
    edge_log("INFO", "Telemetry heartbeat worker thread started.")
    while True:
        try:
            payload = {
                "device_id": DEVICE_ID,
                "ip_address": get_local_ip(),
                "capture_mode": CAPTURE_MODE,
                "disk_free_gb": get_disk_free_gb(),
                "cpu_usage": get_cpu_usage(),
                "cpu_temp": get_cpu_temp(),
                "ram_usage": get_ram_usage()
            }
            
            res = requests.post(f"{SERVER_URL}/api/device/heartbeat", json=payload, timeout=5)
            if res.status_code == 200:
                pass # Heartbeat silent confirmation
            else:
                print(f"[Warning] Heartbeat rejected by server: Status {res.status_code}")
        except Exception as e:
            print(f"[Warning] Failed connecting telemetry heartbeat to server: {e}")
            
        time.sleep(8)  # Telemetry update cadence


# LOCAL LOG STREAMER THREAD
def log_streamer_worker():
    while True:
        time.sleep(5)
        global log_queue
        with log_lock:
            if not log_queue:
                continue
            batch_to_send = list(log_queue)
            log_queue = []
            
        try:
            payload = {
                "device_id": DEVICE_ID,
                "logs": batch_to_send
            }
            res = requests.post(f"{SERVER_URL}/api/device/logs", json=payload, timeout=5)
            if res.status_code != 200:
                # Put logs back on failure
                with log_lock:
                    log_queue = batch_to_send + log_queue
        except Exception:
            # Network down, restore logs locally to retry on next cycle
            with log_lock:
                log_queue = batch_to_send + log_queue


# SAFE OFFLINE STORAGE QUEUE FIFO PURGE
def enforce_disk_limit():
    """If free disk space is less than 2GB, purge oldest pending files to protect the Pi filesystem."""
    free_space = get_disk_free_gb()
    if free_space > 2.0:
        return
        
    edge_log("WARNING", f"Local disk space critical: {free_space:.2f} GB free. Enforcing FIFO purge...")
    
    # Gather files in pending directory
    files = [os.path.join(PENDING_DIR, f) for f in os.listdir(PENDING_DIR)]
    files.sort(key=os.path.getmtime)  # Oldest first
    
    purged_bytes = 0
    for f in files:
        if get_disk_free_gb() > 3.0:
            break
        try:
            size = os.path.getsize(f)
            os.remove(f)
            purged_bytes += size
        except Exception as e:
            edge_log("ERROR", f"Failed purger removing cache file: {e}")
            
    edge_log("WARNING", f"Purger successfully released {purged_bytes / (1024 * 1024):.1f} MB of offline storage.")


# UPLOADER THREAD WITH EXPONENTIAL BACKOFF
def uploader_worker():
    edge_log("INFO", "Queue upload worker thread started.")
    backoff_time = 2.0
    
    while True:
        # Check if there are any files pending in local cache folder
        files = [f for f in os.listdir(PENDING_DIR) if os.path.isfile(os.path.join(PENDING_DIR, f))]
        
        if not files:
            time.sleep(1)
            continue
            
        # Select the oldest file for in-order (FIFO) upload
        files.sort(key=lambda x: os.path.getmtime(os.path.join(PENDING_DIR, x)))
        filename = files[0]
        pending_path = os.path.join(PENDING_DIR, filename)
        uploading_path = os.path.join(UPLOADING_DIR, filename)
        
        # 1. Lock the file by moving it to uploading/ folder
        try:
            shutil.move(pending_path, uploading_path)
        except Exception as e:
            edge_log("ERROR", f"Failed locking file {filename}: {e}")
            time.sleep(1)
            continue
            
        # 2. Perform Multipart HTTP POST Upload
        file_type = "image" if filename.endswith(".webp") else "video"
        endpoint = f"{SERVER_URL}/upload/{file_type}"
        
        uploaded_successfully = False
        retry_count = 0
        max_retries = 3
        
        while retry_count < max_retries and not uploaded_successfully:
            try:
                with open(uploading_path, "rb") as f:
                    files_payload = {"file": (filename, f, "application/octet-stream")}
                    data_payload = {"device_id": DEVICE_ID}
                    
                    res = requests.post(endpoint, files=files_payload, data=data_payload, timeout=15)
                    
                    if res.status_code == 200 and res.json().get("status") == "success":
                        uploaded_successfully = True
                        # Reset backoff on successful upload
                        backoff_time = 2.0
                    else:
                        retry_count += 1
                        edge_log("WARNING", f"Server upload rejected for {filename}: Status {res.status_code}. Retry {retry_count}/{max_retries}")
                        time.sleep(2)
            except Exception as e:
                retry_count += 1
                edge_log("WARNING", f"Network error uploading {filename}: {e}. Retry {retry_count}/{max_retries}")
                time.sleep(2)
                
        # 3. Post-upload File state transitions
        if uploaded_successfully:
            # Shift to uploaded/ for brief logging verification then safe deletion
            uploaded_path = os.path.join(UPLOADED_DIR, filename)
            try:
                shutil.move(uploading_path, uploaded_path)
                os.remove(uploaded_path)  # Delete immediately to save local space
            except Exception as e:
                edge_log("ERROR", f"Failed clearing uploaded file {filename}: {e}")
        else:
            # Max retries exhausted: server offline or corrupt file
            edge_log("ERROR", f"Failed upload pipeline for {filename} after {max_retries} attempts.")
            
            # Check if network is down globally or if it's just server error
            try:
                requests.get(SERVER_URL, timeout=3)
                # Server is online but upload rejected. Move file to failed/ to unblock queue!
                failed_path = os.path.join(FAILED_DIR, filename)
                shutil.move(uploading_path, failed_path)
                edge_log("ERROR", f"Moved corrupted/unsupported file {filename} to failed/ folder.")
            except Exception:
                # Entire network/server is completely offline. Move back to pending/ to queue and wait
                try:
                    shutil.move(uploading_path, pending_path)
                except Exception:
                    pass
                
                # Apply exponential backoff to sleep worker and prevent hammering
                edge_log("WARNING", f"Uploader going to sleep for {backoff_time:.1f}s due to connection blackouts...")
                time.sleep(backoff_time)
                backoff_time = min(backoff_time * 2.0, 60.0)  # Max backoff limit 60s
                
        # Proactively check and enforce local filesystem sizes
        enforce_disk_limit()


def discover_audio_device():
    # Fallback default
    device = "default"
    try:
        if os.path.exists("/proc/asound/cards"):
            with open("/proc/asound/cards", "r") as f:
                lines = f.readlines()
            for line in lines:
                if "Video" in line or "USB-Audio" in line or "C8 USB3.0" in line or "Macrosilicon" in line:
                    parts = line.strip().split()
                    if parts and parts[0].isdigit():
                        card_idx = parts[0]
                        device = f"plughw:{card_idx},0"
                        edge_log("INFO", f"Dynamically discovered active ALSA audio device at: {device}")
                        return device
    except Exception as e:
        edge_log("WARNING", f"Audio device discovery failed: {e}. Falling back to 'default'")
    return device


# CAPTURE PIPELINE MAIN LOOP
def capture_engine_worker():
    edge_log("INFO", f"Capture engine started in [{CAPTURE_MODE.upper()}] mode.")
    
    # Setup video source: dynamically discover active physical camera index
    cap = None
    active_idx = 0
    while True:
        for idx in [0, 1, 2]:
            device_path = f"/dev/video{idx}"
            if os.path.exists(device_path):
                try:
                    cap_test = cv2.VideoCapture(idx)
                    if cap_test.isOpened():
                        ret_test, frame_test = cap_test.read()
                        cap_test.release()
                        if ret_test:
                            edge_log("INFO", f"Discovered active HDMI Capture Card at index {idx} ({device_path})")
                            active_idx = idx
                            cap = cv2.VideoCapture(active_idx)
                            break
                except Exception as e:
                    edge_log("WARNING", f"Error probing {device_path}: {e}")
        
        if cap is not None and cap.isOpened():
            # Force high-definition 720p capture directly from hardware
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
            # Try to grab a frame to verify resolution
            ret_test, frame_test = cap.read()
            if ret_test:
                h_act, w_act = frame_test.shape[:2]
                edge_log("INFO", f"Hardware HDMI capture card initialized successfully at index {active_idx} (Native capture: {w_act}x{h_act})!")
            else:
                edge_log("INFO", f"Hardware HDMI capture card initialized successfully at index {active_idx}!")
            break
        else:
            edge_log("ERROR", "No active physical HDMI capture card detected. Retrying hardware discovery in 5 seconds...")
            time.sleep(5)
        
    frame_counter = 0
    
    if CAPTURE_MODE == "image":
        # IMAGE MODE: WebP quality 80 at 1 FPS
        while True:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"frame_{timestamp}.webp"
            pending_path = os.path.join(PENDING_DIR, filename)
            
            ret, frame = cap.read()
            if not ret:
                edge_log("ERROR", "Failed acquiring frame from HDMI Capture card. Attempting camera reinitialization...")
                cap.release()
                time.sleep(2)
                cap = cv2.VideoCapture(active_idx)
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                continue
                
            frame = cv2.resize(frame, (1280, 720))
            
            # Write to pending folder in WebP format
            cv2.imwrite(pending_path, frame, [int(cv2.IMWRITE_WEBP_QUALITY), 80])
            frame_counter += 1
            
            time.sleep(CAPTURE_INTERVAL)
            
    elif CAPTURE_MODE == "video" or CAPTURE_MODE == "both":
        # VIDEO/BOTH MODE: 1-minute MP4 chunk compiling and optional periodic screenshots
        fps = 25.0  # Smooth 25 FPS target
        total_frames = int(VIDEO_CHUNK_DURATION * fps)
        last_image_time = 0.0
        
        # Safe thread isolated folder for active writing
        temp_recording_dir = os.path.join(CACHE_DIR, "recording")
        os.makedirs(temp_recording_dir, exist_ok=True)
        
        while True:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"chunk_{timestamp}.mp4"
            temp_path = os.path.join(temp_recording_dir, f"raw_video_{timestamp}.mp4")
            audio_temp_path = os.path.join(temp_recording_dir, f"raw_audio_{timestamp}.wav")
            pending_path = os.path.join(PENDING_DIR, filename)
            
            # Setup video encoder using universally compatible mp4v at 720p HD
            fourcc = cv2.VideoWriter_fourcc(*'mp4v')
            out = cv2.VideoWriter(temp_path, fourcc, fps, (1280, 720))
            
            if not out.isOpened():
                # Fallback to XVID
                fourcc = cv2.VideoWriter_fourcc(*'XVID')
                out = cv2.VideoWriter(temp_path, fourcc, fps, (1280, 720))
                
            edge_log("INFO", f"Initiated recording for video chunk: {filename} at 1280x720 25 FPS")
            
            # Start background audio-only capture from hardware-discovered ALSA card for 60 seconds
            audio_device = discover_audio_device()
            audio_cmd = [
                "ffmpeg", "-y",
                "-f", "alsa",
                "-ac", "2",
                "-ar", "48000",
                "-i", audio_device,
                "-t", str(VIDEO_CHUNK_DURATION),
                "-c:a", "pcm_s16le",
                audio_temp_path
            ]
            audio_log_path = os.path.join(temp_recording_dir, f"audio_err_{timestamp}.log")
            try:
                audio_log_file = open(audio_log_path, "w")
                audio_proc = subprocess.Popen(audio_cmd, stdout=subprocess.DEVNULL, stderr=audio_log_file)
            except Exception as e:
                edge_log("WARNING", f"Failed starting background audio capture: {e}")
                audio_proc = None
            
            for _ in range(total_frames):
                start_frame_time = time.time()
                
                ret, frame = cap.read()
                if not ret:
                    edge_log("ERROR", "Failed acquiring frame from HDMI Capture card. Attempting camera reinitialization...")
                    cap.release()
                    time.sleep(2)
                    cap = cv2.VideoCapture(active_idx)
                    cap.set(cv2.CAP_PROP_FRAME_WIDTH, 1280)
                    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 720)
                    frame = np.zeros((720, 1280, 3), dtype=np.uint8)
                else:
                    frame = cv2.resize(frame, (1280, 720))
                    
                out.write(frame)
                frame_counter += 1
                
                # If in 'both' mode, periodically extract and save a WebP screenshot frame asynchronously
                if CAPTURE_MODE == "both":
                    now = time.time()
                    if now - last_image_time >= CAPTURE_INTERVAL:
                        last_image_time = now
                        frame_copy = frame.copy()
                        image_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                        image_filename = f"frame_{image_timestamp}.webp"
                        image_pending_path = os.path.join(PENDING_DIR, image_filename)
                        
                        def save_image_worker(path, img):
                            try:
                                # Save screenshot frame at high-quality 720p HD
                                cv2.imwrite(path, img, [int(cv2.IMWRITE_WEBP_QUALITY), 80])
                            except Exception as e:
                                print(f"Error saving periodic frame: {e}")
                                
                        threading.Thread(target=save_image_worker, args=(image_pending_path, frame_copy), daemon=True).start()
                
                # Regulate capture rate dynamically to hit target FPS (25 FPS -> 40ms per frame)
                elapsed = time.time() - start_frame_time
                delay = max(0.0, (1.0 / fps) - elapsed)
                time.sleep(delay)
                
            out.release()
            
            # Wait for background audio capture process to finish
            if audio_proc:
                try:
                    audio_proc.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    audio_proc.terminate()
                    edge_log("WARNING", "Audio capture process timed out and was forced to terminate.")
                
                try:
                    audio_log_file.close()
                except Exception:
                    pass
            
            # Check if raw audio was successfully captured
            has_audio = os.path.exists(audio_temp_path) and os.path.getsize(audio_temp_path) > 1024
            
            if not has_audio:
                if os.path.exists(audio_log_path):
                    try:
                        with open(audio_log_path, "r") as f:
                            err_log = f.read().strip()
                        if err_log:
                            edge_log("WARNING", f"Audio capture driver diagnostics:\n{err_log}")
                    except Exception:
                        pass
            
            # Queue fully compiled video to pending for uploader consumption
            h264_path = os.path.join(temp_recording_dir, "h264_" + filename)
            
            edge_log("INFO", f"Multiplexing video and audio to highly-compressed 720p H.264: {filename}...")
            start_compress = time.time()
            
            compressed_successfully = False
            
            # STAGE 1: Attempt ultra-fast hardware-accelerated H.264 encoding (Pi 4 VPU block)
            cmd_hw = ["ffmpeg", "-y"]
            cmd_hw.extend(["-i", temp_path])
            if has_audio:
                cmd_hw.extend(["-i", audio_temp_path])
            
            cmd_hw.extend([
                "-c:v", "h264_v4l2m2m",
                "-b:v", "1200k",
                "-pix_fmt", "yuv420p",
                "-vf", "scale=1280:720",
                "-r", "25"
            ])
            
            if has_audio:
                cmd_hw.extend([
                    "-c:a", "aac",
                    "-b:a", "48k",
                    "-ar", "44100",
                    "-map", "0:v:0",
                    "-map", "1:a:0"
                ])
            else:
                edge_log("WARNING", f"Muxing video-only due to audio input failures on {filename} (HW attempt).")
                
            cmd_hw.append(h264_path)
            
            try:
                edge_log("INFO", f"Trying Raspberry Pi hardware-accelerated H.264 encoding for {filename}...")
                subprocess.run(cmd_hw, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                compressed_successfully = True
                edge_log("INFO", "Hardware-accelerated H.264 transcode completed successfully!")
            except Exception as e_hw:
                edge_log("WARNING", f"Hardware H.264 encoder unavailable ({e_hw}). Falling back to multi-core software transcode...")
                
                # STAGE 2: Software libx264 fallback (highly compatible and extremely fast)
                cmd_sw = ["ffmpeg", "-y"]
                cmd_sw.extend(["-i", temp_path])
                if has_audio:
                    cmd_sw.extend(["-i", audio_temp_path])
                
                cmd_sw.extend([
                    "-c:v", "libx264",
                    "-preset", "ultrafast",
                    "-crf", "24",
                    "-pix_fmt", "yuv420p",
                    "-vf", "scale=1280:720",
                    "-r", "25"
                ])
                
                if has_audio:
                    cmd_sw.extend([
                        "-c:a", "aac",
                        "-b:a", "48k",
                        "-ar", "44100",
                        "-map", "0:v:0",
                        "-map", "1:a:0"
                    ])
                else:
                    edge_log("WARNING", f"Muxing video-only due to audio input failures on {filename} (SW fallback).")
                    
                cmd_sw.append(h264_path)
                
                try:
                    subprocess.run(cmd_sw, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)
                    compressed_successfully = True
                except Exception as e_sw:
                    edge_log("WARNING", f"Software H.264 compression failed for {filename}: {e_sw}. Falling back to raw chunk.")
                
            # Clean up raw temp files and logs
            try:
                if os.path.exists(audio_log_path):
                    os.remove(audio_log_path)
            except Exception:
                pass
                
            if compressed_successfully and os.path.exists(h264_path):
                try:
                    # Remove the raw temp files
                    if os.path.exists(temp_path):
                        os.remove(temp_path)
                    if os.path.exists(audio_temp_path):
                        os.remove(audio_temp_path)
                    # Move our new highly compressed H.264 video chunk to the uploader queue!
                    shutil.move(h264_path, pending_path)
                    duration = time.time() - start_compress
                    edge_log("INFO", f"Finished H.264 AV compilation in {duration:.1f}s. Queued: {filename}")
                except Exception as e:
                    edge_log("ERROR", f"Failed queuing compressed chunk {filename}: {e}")
            else:
                try:
                    # Clean up audio file
                    if os.path.exists(audio_temp_path):
                        os.remove(audio_temp_path)
                    # Fallback: Move raw video file to pending so capture data is preserved!
                    shutil.move(temp_path, pending_path)
                    edge_log("INFO", f"Queued uncompressed chunk fallback: {filename}")
                except Exception as e:
                    edge_log("ERROR", f"Failed queuing raw fallback chunk {filename}: {e}")


# APPLICATION MAIN INITIATION
if __name__ == "__main__":
    edge_log("INFO", "==================================================")
    edge_log("INFO", f"Starting TV Monitoring Edge Node: {DEVICE_ID}")
    edge_log("INFO", f"Target Server: {SERVER_URL}")
    edge_log("INFO", "==================================================")
    
    # 1. Startup Log batching thread
    t_logger = threading.Thread(target=log_streamer_worker, daemon=True)
    t_logger.start()
    
    # 2. Startup Telemetry Heartbeat thread
    t_heartbeat = threading.Thread(target=heartbeat_worker, daemon=True)
    t_heartbeat.start()
    
    # 3. Startup Queue Uploader thread
    t_uploader = threading.Thread(target=uploader_worker, daemon=True)
    t_uploader.start()
    
    # 4. Run the main Capture Engine (blocks main thread)
    try:
        capture_engine_worker()
    except KeyboardInterrupt:
        edge_log("INFO", "Capture Engine terminated by operator.")
