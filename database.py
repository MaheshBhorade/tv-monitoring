import os
from datetime import datetime
from sqlalchemy import create_engine, Column, String, Integer, Float, DateTime, ForeignKey, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

DB_PATH = os.path.join(os.path.dirname(__file__), "tv_monitoring.db")
DATABASE_URL = f"sqlite:///{DB_PATH}"

engine = create_engine(
    DATABASE_URL, 
    connect_args={"check_same_thread": False}  # Safe for SQLite with multiple threads in FastAPI
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

class Device(Base):
    __tablename__ = "devices"

    device_id = Column(String, primary_key=True, index=True)
    ip_address = Column(String, nullable=True)
    capture_mode = Column(String, nullable=True)  # "image" or "video"
    status = Column(String, default="offline")    # "online", "offline", "error"
    disk_free_gb = Column(Float, default=0.0)
    cpu_usage = Column(Float, default=0.0)
    cpu_temp = Column(Float, default=0.0)
    ram_usage = Column(Float, default=0.0)
    last_seen = Column(DateTime, default=datetime.utcnow)

class Upload(Base):
    __tablename__ = "uploads"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    device_id = Column(String, ForeignKey("devices.device_id"), index=True)
    filename = Column(String, index=True)
    file_type = Column(String)  # "image" or "video"
    file_path = Column(String)
    file_size_kb = Column(Float, default=0.0)
    timestamp = Column(DateTime, default=datetime.utcnow)

class EdgeLog(Base):
    __tablename__ = "edge_logs"

    id = Column(Integer, primary_key=True, index=True, autoincrement=True)
    device_id = Column(String, ForeignKey("devices.device_id"), index=True)
    level = Column(String)  # "INFO", "WARNING", "ERROR", "CRITICAL"
    message = Column(Text)
    timestamp = Column(DateTime, default=datetime.utcnow)

def init_db():
    Base.metadata.create_all(bind=engine)

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
