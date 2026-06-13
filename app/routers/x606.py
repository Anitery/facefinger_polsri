"""
Router X606-S Device Management
Lokasi: app/routers/x606.py
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List
from datetime import datetime

from app.database import SessionLocal
from app.models.x606_models import X606Device
from app.schemas import X606DeviceCreate, X606DeviceOut, X606DeviceUpdate, X606TestResponse
from app.services.x606_service import X606SOAPClient

router = APIRouter(prefix="/x606", tags=["X606-S Device"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

@router.post("/devices", response_model=X606DeviceOut)
def register_device(data: X606DeviceCreate, db: Session = Depends(get_db)):
    if db.query(X606Device).filter(X606Device.device_id == data.device_id).first():
        raise HTTPException(400, "Device ID sudah terdaftar")
    dev = X606Device(**data.model_dump())
    db.add(dev)
    db.commit()
    db.refresh(dev)
    return dev

@router.get("/devices", response_model=List[X606DeviceOut])
def list_devices(db: Session = Depends(get_db), skip: int = 0, limit: int = 100):
    return db.query(X606Device).offset(skip).limit(limit).all()

@router.get("/devices/{device_id}", response_model=X606DeviceOut)
def get_device(device_id: str, db: Session = Depends(get_db)):
    dev = db.query(X606Device).filter(X606Device.device_id == device_id).first()
    if not dev:
        raise HTTPException(404, "Device tidak ditemukan")
    return dev

@router.put("/devices/{device_id}", response_model=X606DeviceOut)
def update_device(device_id: str, data: X606DeviceUpdate, db: Session = Depends(get_db)):
    dev = db.query(X606Device).filter(X606Device.device_id == device_id).first()
    if not dev:
        raise HTTPException(404, "Device tidak ditemukan")
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(dev, field, value)
    db.commit()
    db.refresh(dev)
    return dev

@router.delete("/devices/{device_id}")
def delete_device(device_id: str, db: Session = Depends(get_db)):
    dev = db.query(X606Device).filter(X606Device.device_id == device_id).first()
    if not dev:
        raise HTTPException(404, "Device tidak ditemukan")
    db.delete(dev)
    db.commit()
    return {"success": True}

@router.post("/devices/{device_id}/test", response_model=X606TestResponse)
def test_device(device_id: str, db: Session = Depends(get_db)):
    dev = db.query(X606Device).filter(X606Device.device_id == device_id).first()
    if not dev:
        raise HTTPException(404, "Device tidak ditemukan")
    client = X606SOAPClient(ip=dev.ip_address, com_key=dev.com_key)
    try:
        dt = client.get_time()
        return X606TestResponse(success=True, message="Koneksi berhasil", device_time=dt)
    except HTTPException as e:
        return X606TestResponse(success=False, message=e.detail)
    except Exception as e:
        return X606TestResponse(success=False, message=str(e))

@router.get("/devices/{device_id}/users")
def get_device_users(device_id: str, db: Session = Depends(get_db)):
    dev = db.query(X606Device).filter(X606Device.device_id == device_id).first()
    if not dev:
        raise HTTPException(404, "Device tidak ditemukan")
    client = X606SOAPClient(ip=dev.ip_address, com_key=dev.com_key)
    users = client.get_all_users()
    return {"users": users, "count": len(users)}

@router.post("/devices/{device_id}/restart")
def restart_device(device_id: str, db: Session = Depends(get_db)):
    dev = db.query(X606Device).filter(X606Device.device_id == device_id).first()
    if not dev:
        raise HTTPException(404, "Device tidak ditemukan")
    client = X606SOAPClient(ip=dev.ip_address, com_key=dev.com_key)
    return {"success": client.restart()}

@router.post("/devices/{device_id}/sync-time")
def sync_device_time(device_id: str, db: Session = Depends(get_db)):
    dev = db.query(X606Device).filter(X606Device.device_id == device_id).first()
    if not dev:
        raise HTTPException(404, "Device tidak ditemukan")
    client = X606SOAPClient(ip=dev.ip_address, com_key=dev.com_key)
    now = datetime.now()
    return {"success": client.set_time(now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"))}
