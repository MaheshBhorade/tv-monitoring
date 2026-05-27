from fastapi import FastAPI, UploadFile, File, Form, Depends, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from datetime import datetime, timedelta
import os
import shutil
from typing import List, Optional
from pydantic import BaseModel

# Import local database modules
from database import init_db, get_db, Device, Upload, EdgeLog

# Initialize database tables
init_db()

app = FastAPI(title="TV Content Monitoring & Control Console")

# Enable CORS for local dashboards / external clients if needed
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = "storage"
IMAGE_DIR = os.path.join(BASE_DIR, "images")
VIDEO_DIR = os.path.join(BASE_DIR, "videos")

os.makedirs(IMAGE_DIR, exist_ok=True)
os.makedirs(VIDEO_DIR, exist_ok=True)

# Pydantic Schemas for validation
class HeartbeatPayload(BaseModel):
    device_id: str
    ip_address: Optional[str] = None
    capture_mode: Optional[str] = None
    disk_free_gb: Optional[float] = 0.0
    cpu_usage: Optional[float] = 0.0
    cpu_temp: Optional[float] = 0.0
    ram_usage: Optional[float] = 0.0

class LogEntry(BaseModel):
    level: str  # INFO, WARNING, ERROR, CRITICAL
    message: str

class DeviceLogsPayload(BaseModel):
    device_id: str
    logs: List[LogEntry]

# Helper to calculate storage directory size
def get_storage_stats():
    total_size = 0
    images_count = 0
    videos_count = 0
    
    if os.path.exists(IMAGE_DIR):
        for root, dirs, files in os.walk(IMAGE_DIR):
            for f in files:
                images_count += 1
                fp = os.path.join(root, f)
                if not os.path.islink(fp):
                    total_size += os.path.getsize(fp)
                    
    if os.path.exists(VIDEO_DIR):
        for root, dirs, files in os.walk(VIDEO_DIR):
            for f in files:
                videos_count += 1
                fp = os.path.join(root, f)
                if not os.path.islink(fp):
                    total_size += os.path.getsize(fp)
                    
    return total_size, images_count, videos_count

def format_size(size_bytes):
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


# ROUTES

@app.get("/")
async def root():
    # Redirect base URL to the rich control dashboard
    return RedirectResponse(url="/dashboard")


# LEGACY COMPATIBLE & ENHANCED UPLOAD ENDPOINTS

@app.post("/upload/image")
async def upload_image(
    file: UploadFile = File(...),
    device_id: str = Form(...),
    db: Session = Depends(get_db)
):
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    device_folder = os.path.join(IMAGE_DIR, device_id)
    os.makedirs(device_folder, exist_ok=True)

    filename = f"{timestamp_str}_{file.filename}"
    filepath = os.path.join(device_folder, filename)

    # Save physical file
    content = await file.read()
    file_size_kb = len(content) / 1024.0
    
    with open(filepath, "wb") as buffer:
        buffer.write(content)

    # Database updates
    # 1. Update/Upsert Device record
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        device = Device(device_id=device_id, capture_mode="image")
        db.add(device)
    device.status = "online"
    device.last_seen = datetime.utcnow()
    
    # 2. Add Upload Record
    upload = Upload(
        device_id=device_id,
        filename=filename,
        file_type="image",
        file_path=os.path.join("images", device_id, filename).replace("\\", "/"),
        file_size_kb=file_size_kb,
        timestamp=datetime.utcnow()
    )
    db.add(upload)
    
    # 3. Save a log entry
    edge_log = EdgeLog(
        device_id=device_id,
        level="INFO",
        message=f"Uploaded image frame: {filename} ({file_size_kb:.1f} KB)",
        timestamp=datetime.utcnow()
    )
    db.add(edge_log)
    
    db.commit()

    return {
        "status": "success",
        "type": "image",
        "saved_to": filepath.replace("\\", "/"),
        "size_kb": file_size_kb
    }


@app.post("/upload/video")
async def upload_video(
    file: UploadFile = File(...),
    device_id: str = Form(...),
    db: Session = Depends(get_db)
):
    timestamp_str = datetime.now().strftime("%Y%m%d_%H%M%S")
    device_folder = os.path.join(VIDEO_DIR, device_id)
    os.makedirs(device_folder, exist_ok=True)

    filename = f"{timestamp_str}_{file.filename}"
    filepath = os.path.join(device_folder, filename)

    # Save physical file
    content = await file.read()
    file_size_kb = len(content) / 1024.0
    
    with open(filepath, "wb") as buffer:
        buffer.write(content)

    # Database updates
    # 1. Update/Upsert Device record
    device = db.query(Device).filter(Device.device_id == device_id).first()
    if not device:
        device = Device(device_id=device_id, capture_mode="video")
        db.add(device)
    device.status = "online"
    device.last_seen = datetime.utcnow()
    
    # 2. Add Upload Record
    upload = Upload(
        device_id=device_id,
        filename=filename,
        file_type="video",
        file_path=os.path.join("videos", device_id, filename).replace("\\", "/"),
        file_size_kb=file_size_kb,
        timestamp=datetime.utcnow()
    )
    db.add(upload)
    
    # 3. Save a log entry
    edge_log = EdgeLog(
        device_id=device_id,
        level="INFO",
        message=f"Uploaded video chunk: {filename} ({file_size_kb / 1024.0:.2f} MB)",
        timestamp=datetime.utcnow()
    )
    db.add(edge_log)
    
    db.commit()

    return {
        "status": "success",
        "type": "video",
        "saved_to": filepath.replace("\\", "/"),
        "size_kb": file_size_kb
    }


# NEW DEVICE STATUS & HEARTBEAT ENDPOINTS

@app.post("/api/device/heartbeat")
async def device_heartbeat(payload: HeartbeatPayload, db: Session = Depends(get_db)):
    device = db.query(Device).filter(Device.device_id == payload.device_id).first()
    if not device:
        device = Device(device_id=payload.device_id)
        db.add(device)
    
    device.ip_address = payload.ip_address or device.ip_address
    device.capture_mode = payload.capture_mode or device.capture_mode
    device.disk_free_gb = payload.disk_free_gb
    device.cpu_usage = payload.cpu_usage
    device.cpu_temp = payload.cpu_temp
    device.ram_usage = payload.ram_usage
    device.status = "online"
    device.last_seen = datetime.utcnow()
    
    db.commit()
    return {"status": "success", "message": "Heartbeat updated successfully"}


@app.post("/api/device/logs")
async def device_logs(payload: DeviceLogsPayload, db: Session = Depends(get_db)):
    # Update device status to online
    device = db.query(Device).filter(Device.device_id == payload.device_id).first()
    if device:
        device.status = "online"
        device.last_seen = datetime.utcnow()
        
    # Append logs
    for log in payload.logs:
        db_log = EdgeLog(
            device_id=payload.device_id,
            level=log.level.upper(),
            message=log.message,
            timestamp=datetime.utcnow()
        )
        db.add(db_log)
        
    db.commit()
    return {"status": "success", "message": f"Successfully imported {len(payload.logs)} log items"}


# ANALYTICS & MONITORING API ENDPOINTS

@app.get("/api/devices")
async def get_devices(db: Session = Depends(get_db)):
    devices = db.query(Device).all()
    out = []
    # Dynamic status calculation (offline if no heartbeat for 15s)
    threshold = datetime.utcnow() - timedelta(seconds=15)
    for dev in devices:
        status = "online"
        if dev.last_seen < threshold:
            status = "offline"
            if dev.status != "offline":
                dev.status = "offline"
                db.commit()
        out.append({
            "device_id": dev.device_id,
            "ip_address": dev.ip_address or "Unknown",
            "capture_mode": dev.capture_mode or "Unknown",
            "status": status,
            "disk_free_gb": round(dev.disk_free_gb, 1),
            "cpu_usage": round(dev.cpu_usage, 1),
            "cpu_temp": round(dev.cpu_temp, 1),
            "ram_usage": round(dev.ram_usage, 1),
            "last_seen_seconds_ago": int((datetime.utcnow() - dev.last_seen).total_seconds())
        })
    return out


@app.get("/api/uploads")
async def get_uploads(limit: int = 40, db: Session = Depends(get_db)):
    uploads = db.query(Upload).order_by(Upload.timestamp.desc()).limit(limit).all()
    return [
        {
            "id": u.id,
            "device_id": u.device_id,
            "filename": u.filename,
            "file_type": u.file_type,
            "file_path": u.file_path,
            "file_size_kb": round(u.file_size_kb, 1),
            "timestamp": u.timestamp.strftime("%Y-%m-%d %H:%M:%S")
        } for u in uploads
    ]


@app.get("/api/logs")
async def get_logs(limit: int = 50, db: Session = Depends(get_db)):
    logs = db.query(EdgeLog).order_by(EdgeLog.timestamp.desc()).limit(limit).all()
    return [
        {
            "id": l.id,
            "device_id": l.device_id,
            "level": l.level,
            "message": l.message,
            "timestamp": l.timestamp.strftime("%H:%M:%S")
        } for l in logs
    ]


@app.get("/api/stats")
async def get_stats(db: Session = Depends(get_db)):
    size_bytes, images_count, videos_count = get_storage_stats()
    
    # Active devices calculation (within last 30s)
    active_threshold = datetime.utcnow() - timedelta(seconds=30)
    active_devices = db.query(Device).filter(Device.last_seen >= active_threshold).count()
    total_devices = db.query(Device).count()
    
    # Logs summary
    error_count = db.query(EdgeLog).filter(
        EdgeLog.level.in_(["ERROR", "CRITICAL"]),
        EdgeLog.timestamp >= (datetime.utcnow() - timedelta(hours=1))
    ).count()

    return {
        "storage_size_raw": size_bytes,
        "storage_size_formatted": format_size(size_bytes),
        "images_count": images_count,
        "videos_count": videos_count,
        "active_devices": active_devices,
        "total_devices": total_devices,
        "error_count_last_hour": error_count,
        "uptime_server": "Active"
    }


# PREMIUM DASHBOARD PAGE SERVED VIA FASTAPI

@app.get("/dashboard", response_class=HTMLResponse)
async def get_dashboard():
    # Return HTML response containing pure Tailwind-like styling, glassmorphism cards, and AJAX logic
    html_content = """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Edge TV Monitoring & Capture Control Console</title>
        <link rel="preconnect" href="https://fonts.googleapis.com">
        <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
        <link href="https://fonts.googleapis.com/css2?family=Outfit:wght@300;400;600;800&family=Inter:wght@300;400;500;600&display=swap" rel="stylesheet">
        <style>
            :root {
                --bg-main: #080C14;
                --bg-card: rgba(18, 25, 41, 0.65);
                --border-card: rgba(255, 255, 255, 0.05);
                --border-card-hover: rgba(59, 130, 246, 0.3);
                --text-primary: #F3F4F6;
                --text-secondary: #9CA3AF;
                --color-blue: #3B82F6;
                --color-emerald: #10B981;
                --color-amber: #F59E0B;
                --color-rose: #F43F5E;
                --font-headers: 'Outfit', sans-serif;
                --font-body: 'Inter', sans-serif;
            }

            * {
                box-sizing: border-box;
                margin: 0;
                padding: 0;
            }

            body {
                background-color: var(--bg-main);
                background-image: 
                    radial-gradient(at 0% 0%, rgba(59, 130, 246, 0.07) 0px, transparent 50%),
                    radial-gradient(at 100% 100%, rgba(16, 185, 129, 0.05) 0px, transparent 50%);
                color: var(--text-primary);
                font-family: var(--font-body);
                min-height: 100vh;
                padding: 24px;
                overflow-x: hidden;
            }

            h1, h2, h3, .brand {
                font-family: var(--font-headers);
            }

            /* Container & Layout */
            .container {
                max-width: 1540px;
                margin: 0 auto;
                display: flex;
                flex-direction: column;
                gap: 24px;
            }

            /* Header Section */
            header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                backdrop-filter: blur(16px);
                background: var(--bg-card);
                border: 1px solid var(--border-card);
                border-radius: 16px;
                padding: 16px 28px;
                box-shadow: 0 4px 30px rgba(0, 0, 0, 0.4);
            }

            .brand-wrapper {
                display: flex;
                align-items: center;
                gap: 12px;
            }

            .brand-logo {
                width: 38px;
                height: 38px;
                background: linear-gradient(135deg, var(--color-blue), var(--color-emerald));
                border-radius: 10px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-weight: 800;
                font-size: 20px;
                color: white;
                box-shadow: 0 0 15px rgba(59, 130, 246, 0.4);
            }

            .brand-title h1 {
                font-size: 20px;
                font-weight: 700;
                letter-spacing: -0.5px;
                background: linear-gradient(to right, #FFFFFF, #E5E7EB);
                -webkit-background-clip: text;
                -webkit-text-fill-color: transparent;
            }

            .brand-title p {
                font-size: 11px;
                color: var(--text-secondary);
                text-transform: uppercase;
                letter-spacing: 1px;
                font-weight: 500;
            }

            .system-status-wrapper {
                display: flex;
                align-items: center;
                gap: 20px;
            }

            .status-pill {
                display: flex;
                align-items: center;
                gap: 8px;
                background: rgba(16, 185, 129, 0.1);
                border: 1px solid rgba(16, 185, 129, 0.2);
                border-radius: 20px;
                padding: 6px 14px;
                font-size: 12px;
                font-weight: 600;
                color: var(--color-emerald);
            }

            .pulse-dot {
                width: 8px;
                height: 8px;
                background-color: var(--color-emerald);
                border-radius: 50%;
                animation: pulse 1.8s infinite;
            }

            @keyframes pulse {
                0% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0.7); }
                70% { box-shadow: 0 0 0 6px rgba(16, 185, 129, 0); }
                100% { box-shadow: 0 0 0 0 rgba(16, 185, 129, 0); }
            }

            /* Stats Counter Row */
            .stats-row {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
                gap: 20px;
            }

            .stat-card {
                backdrop-filter: blur(16px);
                background: var(--bg-card);
                border: 1px solid var(--border-card);
                border-radius: 16px;
                padding: 24px;
                display: flex;
                align-items: center;
                justify-content: space-between;
                box-shadow: 0 4px 30px rgba(0, 0, 0, 0.2);
                transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
            }

            .stat-card:hover {
                transform: translateY(-2px);
                border-color: var(--border-card-hover);
                box-shadow: 0 10px 30px rgba(59, 130, 246, 0.1);
            }

            .stat-info {
                display: flex;
                flex-direction: column;
                gap: 6px;
            }

            .stat-label {
                font-size: 12px;
                font-weight: 600;
                color: var(--text-secondary);
                text-transform: uppercase;
                letter-spacing: 0.8px;
            }

            .stat-value {
                font-size: 28px;
                font-weight: 800;
                letter-spacing: -0.5px;
            }

            .stat-icon {
                font-size: 28px;
                opacity: 0.85;
                width: 50px;
                height: 50px;
                border-radius: 12px;
                display: flex;
                align-items: center;
                justify-content: center;
            }

            .icon-blue { background: rgba(59, 130, 246, 0.1); color: var(--color-blue); }
            .icon-emerald { background: rgba(16, 185, 129, 0.1); color: var(--color-emerald); }
            .icon-amber { background: rgba(245, 158, 11, 0.1); color: var(--color-amber); }
            .icon-rose { background: rgba(244, 63, 94, 0.1); color: var(--color-rose); }

            /* Dashboard Central Grid */
            .main-grid {
                display: grid;
                grid-template-columns: 1.6fr 1.4fr;
                gap: 24px;
            }

            @media(max-width: 1024px) {
                .main-grid {
                    grid-template-columns: 1fr;
                }
            }

            /* Section Card Box */
            .section-box {
                backdrop-filter: blur(16px);
                background: var(--bg-card);
                border: 1px solid var(--border-card);
                border-radius: 16px;
                padding: 24px;
                box-shadow: 0 4px 30px rgba(0, 0, 0, 0.25);
                display: flex;
                flex-direction: column;
                gap: 20px;
            }

            .section-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                border-bottom: 1px solid rgba(255, 255, 255, 0.05);
                padding-bottom: 12px;
            }

            .section-title {
                font-size: 18px;
                font-weight: 700;
                display: flex;
                align-items: center;
                gap: 10px;
            }

            /* Device Grid List */
            .device-grid {
                display: grid;
                grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
                gap: 16px;
            }

            .device-card {
                background: rgba(255, 255, 255, 0.02);
                border: 1px solid rgba(255, 255, 255, 0.04);
                border-radius: 12px;
                padding: 16px;
                display: flex;
                flex-direction: column;
                gap: 14px;
                transition: all 0.25s ease;
            }

            .device-card.offline {
                opacity: 0.65;
            }

            .device-card:hover {
                background: rgba(255, 255, 255, 0.04);
                border-color: rgba(255, 255, 255, 0.1);
            }

            .device-card-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
            }

            .device-meta h4 {
                font-size: 16px;
                font-weight: 700;
            }

            .device-meta p {
                font-size: 11px;
                color: var(--text-secondary);
            }

            .device-status-pill {
                font-size: 10px;
                font-weight: 700;
                text-transform: uppercase;
                padding: 2px 8px;
                border-radius: 20px;
                display: flex;
                align-items: center;
                gap: 5px;
            }

            .dev-online { background: rgba(16, 185, 129, 0.1); color: var(--color-emerald); }
            .dev-offline { background: rgba(244, 63, 94, 0.1); color: var(--color-rose); }

            /* Metrics Progress Bars */
            .device-metrics {
                display: flex;
                flex-direction: column;
                gap: 8px;
            }

            .metric-bar-wrapper {
                display: flex;
                flex-direction: column;
                gap: 4px;
            }

            .metric-bar-header {
                display: flex;
                justify-content: space-between;
                font-size: 11px;
                font-weight: 500;
            }

            .metric-bar-label { color: var(--text-secondary); }
            .metric-bar-value { color: var(--text-primary); font-weight: 600; }

            .metric-bar-track {
                height: 5px;
                background: rgba(255, 255, 255, 0.05);
                border-radius: 4px;
                overflow: hidden;
            }

            .metric-bar-fill {
                height: 100%;
                border-radius: 4px;
                transition: width 0.8s ease-in-out;
            }

            .fill-blue { background: linear-gradient(to right, #60A5FA, var(--color-blue)); }
            .fill-emerald { background: linear-gradient(to right, #34D399, var(--color-emerald)); }
            .fill-amber { background: linear-gradient(to right, #FBBF24, var(--color-amber)); }

            .device-card-footer {
                display: flex;
                justify-content: space-between;
                align-items: center;
                border-top: 1px solid rgba(255, 255, 255, 0.03);
                padding-top: 10px;
                font-size: 11px;
                color: var(--text-secondary);
            }

            .device-mode-badge {
                background: rgba(255, 255, 255, 0.05);
                color: var(--text-primary);
                padding: 2px 6px;
                border-radius: 4px;
                font-weight: 600;
                font-size: 9px;
                text-transform: uppercase;
            }

            /* Upload Feed Gallery */
            .upload-feed {
                display: flex;
                flex-direction: column;
                gap: 12px;
                max-height: 580px;
                overflow-y: auto;
                padding-right: 6px;
            }

            .upload-feed::-webkit-scrollbar {
                width: 6px;
            }

            .upload-feed::-webkit-scrollbar-thumb {
                background: rgba(255, 255, 255, 0.1);
                border-radius: 3px;
            }

            .feed-item {
                background: rgba(255, 255, 255, 0.02);
                border: 1px solid rgba(255, 255, 255, 0.04);
                border-radius: 12px;
                padding: 12px;
                display: flex;
                align-items: center;
                gap: 14px;
                transition: all 0.2s ease;
            }

            .feed-item:hover {
                background: rgba(255, 255, 255, 0.04);
                border-color: rgba(255, 255, 255, 0.08);
            }

            .feed-thumbnail {
                width: 70px;
                height: 48px;
                background: rgba(0,0,0,0.3);
                border-radius: 6px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 18px;
                overflow: hidden;
                border: 1px solid rgba(255,255,255,0.05);
            }

            .feed-thumbnail img {
                width: 100%;
                height: 100%;
                object-fit: cover;
            }

            .feed-details {
                flex-grow: 1;
                display: flex;
                flex-direction: column;
                gap: 3px;
            }

            .feed-title {
                font-size: 13px;
                font-weight: 600;
                color: var(--text-primary);
                word-break: break-all;
            }

            .feed-meta {
                display: flex;
                gap: 12px;
                font-size: 11px;
                color: var(--text-secondary);
            }

            .feed-device {
                background: rgba(59, 130, 246, 0.15);
                color: #93C5FD;
                font-weight: 700;
                padding: 1px 5px;
                border-radius: 3px;
                font-size: 9px;
            }

            /* Log Panel Terminal */
            .terminal-box {
                backdrop-filter: blur(16px);
                background: #040710;
                border: 1px solid rgba(255, 255, 255, 0.04);
                border-radius: 16px;
                padding: 20px;
                box-shadow: 0 4px 30px rgba(0, 0, 0, 0.5);
                display: flex;
                flex-direction: column;
                gap: 12px;
            }

            .terminal-header {
                display: flex;
                justify-content: space-between;
                align-items: center;
                border-bottom: 1px solid rgba(255,255,255,0.03);
                padding-bottom: 10px;
            }

            .terminal-title {
                font-family: var(--font-headers);
                font-size: 15px;
                font-weight: 700;
                letter-spacing: 0.5px;
                color: var(--text-secondary);
                display: flex;
                align-items: center;
                gap: 8px;
            }

            .terminal-body {
                height: 180px;
                overflow-y: auto;
                font-family: 'Courier New', Courier, monospace;
                font-size: 12px;
                display: flex;
                flex-direction: column;
                gap: 6px;
                padding-right: 6px;
            }

            .terminal-body::-webkit-scrollbar {
                width: 6px;
            }

            .terminal-body::-webkit-scrollbar-thumb {
                background: rgba(255, 255, 255, 0.05);
                border-radius: 3px;
            }

            .log-line {
                display: flex;
                gap: 12px;
                line-height: 1.4;
            }

            .log-time { color: #4B5563; flex-shrink: 0; }
            .log-dev { color: #60A5FA; font-weight: bold; flex-shrink: 0; }
            .log-level { font-weight: bold; flex-shrink: 0; width: 65px; }
            
            .lvl-INFO { color: var(--color-emerald); }
            .lvl-WARNING { color: var(--color-amber); }
            .lvl-ERROR { color: var(--color-rose); }
            .lvl-CRITICAL { color: #FFFFFF; background-color: var(--color-rose); padding: 0 4px; border-radius: 2px; }
            
            .log-msg { color: #D1D5DB; word-break: break-word; }

            /* Empty placeholder states */
            .empty-state {
                display: flex;
                flex-direction: column;
                align-items: center;
                justify-content: center;
                padding: 40px;
                text-align: center;
                color: var(--text-secondary);
                gap: 12px;
            }

            .empty-icon {
                font-size: 32px;
                opacity: 0.5;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <!-- Header -->
            <header>
                <div class="brand-wrapper">
                    <div class="brand-logo">📺</div>
                    <div class="brand-title">
                        <h1>TV Monitoring Control Console</h1>
                        <p>Distributed Capture Network</p>
                    </div>
                </div>
                <div class="system-status-wrapper">
                    <div id="systemHealth" class="status-pill">
                        <div class="pulse-dot"></div>
                        <span id="healthLabel">All Nodes Secure</span>
                    </div>
                </div>
            </header>

            <!-- Stats Counters -->
            <div class="stats-row">
                <div class="stat-card">
                    <div class="stat-info">
                        <span class="stat-label">Active Capture Nodes</span>
                        <span id="activeDevicesCount" class="stat-value">0</span>
                    </div>
                    <div class="stat-icon icon-blue">📡</div>
                </div>
                <div class="stat-card">
                    <div class="stat-info">
                        <span class="stat-label">Image Frames Saved</span>
                        <span id="totalImagesCount" class="stat-value">0</span>
                    </div>
                    <div class="stat-icon icon-emerald">📸</div>
                </div>
                <div class="stat-card">
                    <div class="stat-info">
                        <span class="stat-label">Video Chunks Saved</span>
                        <span id="totalVideosCount" class="stat-value">0</span>
                    </div>
                    <div class="stat-icon icon-amber">🎥</div>
                </div>
                <div class="stat-card">
                    <div class="stat-info">
                        <span class="stat-label">Storage Occupied</span>
                        <span id="storageUsedText" class="stat-value">0.00 MB</span>
                    </div>
                    <div class="stat-icon icon-rose">💾</div>
                </div>
            </div>

            <!-- Central Grid -->
            <div class="main-grid">
                <!-- Left: Device Fleet -->
                <div class="section-box">
                    <div class="section-header">
                        <h3 class="section-title">📡 Edge Capture Fleet</h3>
                    </div>
                    <div id="devicesContainer" class="device-grid">
                        <div class="empty-state">
                            <div class="empty-icon">🔌</div>
                            <p>No active capture nodes detected.</p>
                            <span style="font-size: 11px;">Awaiting heartbeat logs from edge clients...</span>
                        </div>
                    </div>
                </div>

                <!-- Right: Media Upload Log -->
                <div class="section-box">
                    <div class="section-header">
                        <h3 class="section-title">📦 Dynamic Upload Feed</h3>
                    </div>
                    <div id="uploadsContainer" class="upload-feed">
                        <div class="empty-state">
                            <div class="empty-icon">📁</div>
                            <p>No content uploads recorded yet.</p>
                        </div>
                    </div>
                </div>
            </div>

            <!-- Bottom: System Log Terminal -->
            <div class="terminal-box">
                <div class="terminal-header">
                    <div class="terminal-title">📟 Consolidated System Diagnostics Log</div>
                </div>
                <div id="logsTerminal" class="terminal-body">
                    <div class="log-line">
                        <span class="log-time">[System Init]</span>
                        <span class="log-msg">Dashboard monitoring successfully listening for clients...</span>
                    </div>
                </div>
            </div>
        </div>

        <script>
            // Async polling function
            async function fetchStats() {
                try {
                    const res = await fetch('/api/stats');
                    if (!res.ok) throw new Error("Network status invalid");
                    const data = await res.json();
                    
                    document.getElementById('activeDevicesCount').textContent = `${data.active_devices}/${data.total_devices}`;
                    document.getElementById('totalImagesCount').textContent = data.images_count;
                    document.getElementById('totalVideosCount').textContent = data.videos_count;
                    document.getElementById('storageUsedText').textContent = data.storage_size_formatted;
                    
                    const healthPill = document.getElementById('systemHealth');
                    const healthLabel = document.getElementById('healthLabel');
                    
                    if (data.error_count_last_hour > 0) {
                        healthPill.style.background = 'rgba(244, 63, 94, 0.1)';
                        healthPill.style.borderColor = 'rgba(244, 63, 94, 0.2)';
                        healthPill.style.color = 'var(--color-rose)';
                        healthLabel.textContent = `${data.error_count_last_hour} Client Warnings`;
                        document.querySelector('.pulse-dot').style.backgroundColor = 'var(--color-rose)';
                    } else if (data.active_devices === 0 && data.total_devices > 0) {
                        healthPill.style.background = 'rgba(245, 158, 11, 0.1)';
                        healthPill.style.borderColor = 'rgba(245, 158, 11, 0.2)';
                        healthPill.style.color = 'var(--color-amber)';
                        healthLabel.textContent = 'All Nodes Offline';
                        document.querySelector('.pulse-dot').style.backgroundColor = 'var(--color-amber)';
                    } else {
                        healthPill.style.background = 'rgba(16, 185, 129, 0.1)';
                        healthPill.style.borderColor = 'rgba(16, 185, 129, 0.2)';
                        healthPill.style.color = 'var(--color-emerald)';
                        healthLabel.textContent = 'Capture Network Secure';
                        document.querySelector('.pulse-dot').style.backgroundColor = 'var(--color-emerald)';
                    }
                } catch(e) {
                    console.error("Failed fetching stats", e);
                }
            }

            async function fetchDevices() {
                try {
                    const res = await fetch('/api/devices');
                    if (!res.ok) throw new Error();
                    const devices = await res.json();
                    
                    const container = document.getElementById('devicesContainer');
                    if (devices.length === 0) {
                        return; // Leave empty state
                    }
                    
                    let html = '';
                    devices.forEach(dev => {
                        const statusClass = dev.status === 'online' ? 'dev-online' : 'dev-offline';
                        const cardStatus = dev.status === 'online' ? '' : 'offline';
                        
                        html += `
                            <div class="device-card ${cardStatus}">
                                <div class="device-card-header">
                                    <div class="device-meta">
                                        <h4>${dev.device_id}</h4>
                                        <p>IP: ${dev.ip_address}</p>
                                    </div>
                                    <span class="device-status-pill ${statusClass}">
                                        <span class="pulse-dot" style="animation: ${dev.status === 'online' ? 'pulse 1.8s infinite' : 'none'}; background-color: ${dev.status === 'online' ? 'var(--color-emerald)' : 'var(--color-rose)'}"></span>
                                        ${dev.status}
                                    </span>
                                </div>
                                <div class="device-metrics">
                                    <!-- CPU Usage -->
                                    <div class="metric-bar-wrapper">
                                        <div class="metric-bar-header">
                                            <span class="metric-bar-label">CPU Usage</span>
                                            <span class="metric-bar-value">${dev.cpu_usage}%</span>
                                        </div>
                                        <div class="metric-bar-track">
                                            <div class="metric-bar-fill fill-blue" style="width: ${dev.cpu_usage}%"></div>
                                        </div>
                                    </div>
                                    <!-- CPU Temp -->
                                    <div class="metric-bar-wrapper">
                                        <div class="metric-bar-header">
                                            <span class="metric-bar-label">CPU Temp</span>
                                            <span class="metric-bar-value">${dev.cpu_temp}°C</span>
                                        </div>
                                        <div class="metric-bar-track">
                                            <div class="metric-bar-fill fill-amber" style="width: ${Math.min(dev.cpu_temp * 1.2, 100)}%"></div>
                                        </div>
                                    </div>
                                    <!-- Free Disk Space -->
                                    <div class="metric-bar-wrapper">
                                        <div class="metric-bar-header">
                                            <span class="metric-bar-label">Free Storage</span>
                                            <span class="metric-bar-value">${dev.disk_free_gb} GB</span>
                                        </div>
                                        <div class="metric-bar-track">
                                            <div class="metric-bar-fill fill-emerald" style="width: ${Math.min(dev.disk_free_gb * 3, 100)}%"></div>
                                        </div>
                                    </div>
                                </div>
                                <div class="device-card-footer">
                                    <span>Last checked: ${dev.last_seen_seconds_ago}s ago</span>
                                    <span class="device-mode-badge">${dev.capture_mode}</span>
                                </div>
                            </div>
                        `;
                    });
                    
                    container.innerHTML = html;
                } catch(e) {
                    console.error("Error loading devices", e);
                }
            }

            async function fetchUploads() {
                try {
                    const res = await fetch('/api/uploads');
                    if (!res.ok) throw new Error();
                    const uploads = await res.json();
                    
                    const container = document.getElementById('uploadsContainer');
                    if (uploads.length === 0) return;
                    
                    let html = '';
                    uploads.forEach(upload => {
                        const icon = upload.file_type === 'image' ? '📸' : '🎥';
                        const sizeStr = upload.file_type === 'image' ? `${upload.file_size_kb} KB` : `${(upload.file_size_kb/1024).toFixed(2)} MB`;
                        
                        html += `
                            <div class="feed-item">
                                <div class="feed-thumbnail">
                                    ${upload.file_type === 'image' ? `<img src="/storage/${upload.file_path}" alt="Capture">` : '🎬'}
                                </div>
                                <div class="feed-details">
                                    <div class="feed-title">${upload.filename}</div>
                                    <div class="feed-meta">
                                        <span class="feed-device">${upload.device_id}</span>
                                        <span>${sizeStr}</span>
                                        <span>${upload.timestamp}</span>
                                    </div>
                                </div>
                            </div>
                        `;
                    });
                    
                    container.innerHTML = html;
                } catch(e) {
                    console.error("Error loading uploads", e);
                }
            }

            async function fetchLogs() {
                try {
                    const res = await fetch('/api/logs');
                    if (!res.ok) throw new Error();
                    const logs = await res.json();
                    
                    const container = document.getElementById('logsTerminal');
                    if (logs.length === 0) return;
                    
                    let html = '';
                    logs.forEach(log => {
                        html += `
                            <div class="log-line">
                                <span class="log-time">[${log.timestamp}]</span>
                                <span class="log-dev">${log.device_id}</span>
                                <span class="log-level lvl-${log.level}">${log.level}</span>
                                <span class="log-msg">${log.message}</span>
                            </div>
                        `;
                    });
                    
                    container.innerHTML = html;
                } catch(e) {
                    console.error("Error loading logs", e);
                }
            }

            // Expose public storage static route (to render captured images directly in upload feeds)
            // FastAPI does this via StaticFiles middleware, but since we are self-contained we can let FastAPI serve storage/ images if needed.
            
            // Loop polls
            function updateAll() {
                fetchStats();
                fetchDevices();
                fetchUploads();
                fetchLogs();
            }

            setInterval(updateAll, 2000);
            updateAll();
        </script>
    </body>
    </html>
    """
    return html_content

# Add simple middleware to serve files from local 'storage' folder in dev environment easily
from fastapi.staticfiles import StaticFiles
app.mount("/storage", StaticFiles(directory="storage"), name="storage")