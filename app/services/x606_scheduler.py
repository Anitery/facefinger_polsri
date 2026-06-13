"""
APScheduler Jobs untuk Smart Lock Lab Multimedia 2
Lokasi: app/services/x606_scheduler.py
"""
from apscheduler.schedulers.background import BackgroundScheduler
from sqlalchemy.orm import Session
from datetime import datetime, timedelta

from app.database import SessionLocal
from app.models.x606_models import X606Device, X606JadwalKBM
from app.services.x606_service import X606LabService

def job_pull_all_logs():
    """Tarik log dari semua device aktif setiap 2 menit."""
    db = SessionLocal()
    try:
        devices = db.query(X606Device).filter(X606Device.is_active == True).all()
        svc = X606LabService(db)
        for dev in devices:
            try:
                result = svc.pull_logs_from_device(dev.device_id)
                print(f"[SCHEDULER PULL] {dev.device_id}: {result['message']}")
            except Exception as e:
                print(f"[SCHEDULER PULL ERROR] {dev.device_id}: {e}")
    finally:
        db.close()

def job_sync_jadwal_aktif():
    """Sync user ke device 15 menit sebelum jadwal. Disable 15 menit setelah selesai."""
    db = SessionLocal()
    try:
        now = datetime.now()
        hari_map = {
            "Monday": "Senin", "Tuesday": "Selasa", "Wednesday": "Rabu",
            "Thursday": "Kamis", "Friday": "Jumat", "Saturday": "Sabtu", "Sunday": "Minggu"
        }
        hari = hari_map[now.strftime("%A")]
        upcoming = db.query(X606JadwalKBM).filter(
            X606JadwalKBM.hari == hari,
            X606JadwalKBM.is_active == True
        ).all()
        svc = X606LabService(db)
        for j in upcoming:
            jam_mulai_dt = datetime.combine(now.date(), j.jam_mulai)
            jam_selesai_dt = datetime.combine(now.date(), j.jam_selesai)
            # SYNC: 15 menit sebelum mulai
            if jam_mulai_dt - timedelta(minutes=15) <= now <= jam_mulai_dt:
                devices = db.query(X606Device).filter(X606Device.ruangan_id == j.ruangan_id).all()
                for dev in devices:
                    try:
                        result = svc.sync_users_to_device(dev.device_id, j.id)
                        print(f"[SCHEDULER SYNC] {dev.device_id} jadwal {j.id}: {result['message']}")
                    except Exception as e:
                        print(f"[SCHEDULER SYNC ERROR] {dev.device_id}: {e}")
            # DISABLE: 15 menit setelah selesai
            if jam_selesai_dt <= now <= jam_selesai_dt + timedelta(minutes=15):
                devices = db.query(X606Device).filter(X606Device.ruangan_id == j.ruangan_id).all()
                for dev in devices:
                    try:
                        result = svc.clear_users_from_device(dev.device_id)
                        print(f"[SCHEDULER DISABLE] {dev.device_id}: {result['message']}")
                    except Exception as e:
                        print(f"[SCHEDULER DISABLE ERROR] {dev.device_id}: {e}")
    finally:
        db.close()

def start_x606_scheduler():
    scheduler = BackgroundScheduler()
    scheduler.add_job(job_pull_all_logs, "interval", minutes=2, id="x606_pull_logs", replace_existing=True)
    scheduler.add_job(job_sync_jadwal_aktif, "interval", minutes=5, id="x606_sync_jadwal", replace_existing=True)
    scheduler.start()
    return scheduler
