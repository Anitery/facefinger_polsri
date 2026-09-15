"""
app/routers/sesi_finger.py
=========================================================
Sesi input fingerprint terkontrol — admin pilih device + user, sistem
push PIN+nama (tanpa template) ke device via door_service.py, admin
enroll fisik tiap user, lalu klik "Selesaikan Sesi" untuk ekstrak
semua template sekaligus & simpan ke database.

Selama sesi aktif: jadwal yang sedang berjalan di ruangan itu
dinonaktifkan sementara, dan loop sync biometrik otomatis
(door_service.py) di-skip untuk ruangan ini.
"""
import os
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload
import requests

from app.database import get_db
from app.models.models import (
    SesiInputFinger, User, Ruangan, JadwalRuangan, BiometricTemplate, BridgeHeartbeat,
)
from app.services.auth_service import get_current_user_session

router = APIRouter(prefix="/sesi-finger", tags=["Sesi Input Fingerprint"])

DOOR_SERVICE_URL     = os.getenv("DOOR_SERVICE_URL", "http://10.17.44.161:8081")
DOOR_SERVICE_API_KEY = os.getenv("DOOR_SERVICE_API_KEY", "ganti-key-ini-di-env")


def _door_service_post(path: str, data: dict, timeout: int = 60):
    try:
        r = requests.post(
            f"{DOOR_SERVICE_URL}{path}",
            headers={"X-API-Key": DOOR_SERVICE_API_KEY},
            json=data, timeout=timeout,
        )
        return r.ok, (r.json() if r.headers.get("content-type", "").startswith("application/json") else r.text)
    except Exception as e:
        return False, str(e)


@router.get("/aktif")
def cek_sesi_aktif(ruangan_id: Optional[int] = None, db: Session = Depends(get_db), user=Depends(get_current_user_session)):
    """Cek apakah ada sesi yang sedang berjalan (buat UI tahu status tombol)."""
    q = db.query(SesiInputFinger).options(
        joinedload(SesiInputFinger.ruangan), joinedload(SesiInputFinger.peserta)
    ).filter(SesiInputFinger.status == "aktif")
    if ruangan_id:
        q = q.filter(SesiInputFinger.ruangan_id == ruangan_id)
    sesi = q.first()
    if not sesi:
        return {"aktif": False}
    return {
        "aktif": True,
        "id": sesi.id,
        "ruangan_id": sesi.ruangan_id,
        "nama_ruangan": sesi.ruangan.nama if sesi.ruangan else "—",
        "dimulai_at": sesi.dimulai_at.isoformat() if sesi.dimulai_at else None,
        "peserta": [{"id": p.id, "nama": p.nama, "pin": p.id_perangkat} for p in sesi.peserta],
    }


class MulaiSesiPayload(BaseModel):
    ruangan_id: int
    user_ids: List[int]


@router.post("/mulai")
def mulai_sesi(payload: MulaiSesiPayload, db: Session = Depends(get_db), user=Depends(get_current_user_session)):
    if user["role"] not in ("admin", "teknisi"):
        raise HTTPException(status_code=403, detail="Hanya admin/teknisi yang boleh memulai sesi input finger")

    existing = db.query(SesiInputFinger).filter(
        SesiInputFinger.ruangan_id == payload.ruangan_id, SesiInputFinger.status == "aktif"
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Sudah ada sesi aktif di ruangan ini")

    ruangan = db.query(Ruangan).filter(Ruangan.id == payload.ruangan_id).first()
    if not ruangan:
        raise HTTPException(status_code=404, detail="Ruangan tidak ditemukan")

    hb = db.query(BridgeHeartbeat).filter(BridgeHeartbeat.ruangan_id == ruangan.id).order_by(BridgeHeartbeat.last_seen.desc()).first()
    device_ip = hb.device_ip if hb else None

    peserta = db.query(User).filter(User.id.in_(payload.user_ids), User.id_perangkat.isnot(None)).all()
    if not peserta:
        raise HTTPException(status_code=400, detail="Tidak ada user valid (pastikan semua sudah punya ID Perangkat)")

    # Pause jadwal yang sedang aktif di ruangan ini (kalau ada)
    jadwal_aktif = db.query(JadwalRuangan).filter(
        JadwalRuangan.ruangan_id == ruangan.id, JadwalRuangan.is_active == True
    ).first()
    if jadwal_aktif:
        jadwal_aktif.is_active = False

    sesi = SesiInputFinger(
        ruangan_id=ruangan.id, device_ip=device_ip, status="aktif",
        dimulai_oleh=user["user_id"],
        jadwal_dipause_id=jadwal_aktif.id if jadwal_aktif else None,
    )
    sesi.peserta = peserta
    db.add(sesi)
    db.commit()
    db.refresh(sesi)

    # Push PIN+nama (tanpa template) ke device via door_service
    ok, hasil = _door_service_post("/provision-users", {
        "users": [{"pin": str(p.id_perangkat), "nama": p.nama} for p in peserta]
    })

    if not ok:
        # Sesi tetap dibuat (biar admin bisa retry/batalkan manual), tapi kasih tahu gagal
        return {
            "sesi_id": sesi.id, "peringatan": f"Sesi dibuat, tapi push ke device GAGAL: {hasil}",
            "jumlah_peserta": len(peserta),
        }

    return {"sesi_id": sesi.id, "pesan": "Sesi dimulai, user sudah di-push ke device", "jumlah_peserta": len(peserta)}


class SelesaiSesiPayload(BaseModel):
    sesi_id: int


@router.post("/selesai")
def selesaikan_sesi(payload: SelesaiSesiPayload, db: Session = Depends(get_db), user=Depends(get_current_user_session)):
    if user["role"] not in ("admin", "teknisi"):
        raise HTTPException(status_code=403, detail="Hanya admin/teknisi yang boleh menyelesaikan sesi")

    sesi = db.query(SesiInputFinger).options(joinedload(SesiInputFinger.peserta)).filter(
        SesiInputFinger.id == payload.sesi_id
    ).first()
    if not sesi:
        raise HTTPException(status_code=404, detail="Sesi tidak ditemukan")
    if sesi.status != "aktif":
        raise HTTPException(status_code=400, detail="Sesi ini sudah tidak aktif")

    pins = [str(p.id_perangkat) for p in sesi.peserta]
    ok, hasil = _door_service_post("/extract-session-templates", {"pins": pins}, timeout=120)

    tersimpan = 0
    gagal_pin = []
    if ok and isinstance(hasil, dict):
        for p in sesi.peserta:
            pin = str(p.id_perangkat)
            templates = hasil.get(pin, [])
            if not templates:
                gagal_pin.append(pin)
                continue
            for t in templates:
                existing = db.query(BiometricTemplate).filter(
                    BiometricTemplate.user_id == p.id, BiometricTemplate.finger_id == int(t["finger_id"])
                ).first()
                if existing:
                    existing.size = t.get("size")
                    existing.template = t.get("template")
                    existing.valid = t.get("valid", "1")
                else:
                    db.add(BiometricTemplate(
                        user_id=p.id, finger_id=int(t["finger_id"]),
                        size=t.get("size"), template=t.get("template"), valid=t.get("valid", "1"),
                    ))
            tersimpan += 1
    else:
        gagal_pin = pins

    # Reaktifkan jadwal yang tadi dipause
    if sesi.jadwal_dipause_id:
        jadwal = db.query(JadwalRuangan).filter(JadwalRuangan.id == sesi.jadwal_dipause_id).first()
        if jadwal:
            jadwal.is_active = True

    sesi.status = "selesai"
    sesi.selesai_at = datetime.now()
    db.commit()

    return {
        "pesan": "Sesi selesai",
        "tersimpan": tersimpan,
        "gagal": gagal_pin,
        "jadwal_diaktifkan_lagi": sesi.jadwal_dipause_id is not None,
    }


@router.post("/batal")
def batalkan_sesi(payload: SelesaiSesiPayload, db: Session = Depends(get_db), user=Depends(get_current_user_session)):
    """Batalkan sesi tanpa ekstrak template (misal salah pilih user) — jadwal tetap direaktivasi."""
    if user["role"] not in ("admin", "teknisi"):
        raise HTTPException(status_code=403, detail="Hanya admin/teknisi yang boleh membatalkan sesi")

    sesi = db.query(SesiInputFinger).filter(SesiInputFinger.id == payload.sesi_id).first()
    if not sesi or sesi.status != "aktif":
        raise HTTPException(status_code=404, detail="Sesi aktif tidak ditemukan")

    if sesi.jadwal_dipause_id:
        jadwal = db.query(JadwalRuangan).filter(JadwalRuangan.id == sesi.jadwal_dipause_id).first()
        if jadwal:
            jadwal.is_active = True

    sesi.status = "batal"
    db.commit()
    return {"pesan": "Sesi dibatalkan"}