"""
Router X606-S Lab Multimedia 2 - AUTO SYNC VERSION
Lokasi: app/routers/x606_lab.py

Perubahan utama:
- quick-sync: SetUserInfo → GetAllUserInfo (cari user baru) → Auto register cache
- Semua logic PIN mapping otomatis
"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from typing import List, Optional
from datetime import datetime, time
from pydantic import BaseModel as PydanticBase

from app.database import SessionLocal
from app.models.x606_models import (
    X606JadwalKBM, X606JadwalPeserta, AbsensiX606, X606UserCache,
    X606Device, StatusAbsensiX606, HariEnum
)
from app.models.models import User, Ruangan
from app.schemas import (
    X606JadwalKBMCreate, X606JadwalKBMUpdate, X606JadwalKBMOut,
    AbsensiX606Out, PullLogResponse, LabAccessCheck,
    X606UserCacheCreate
)
from app.services.x606_service import X606LabService, X606SOAPClient

router = APIRouter(prefix="/lab-multimedia", tags=["Lab Multimedia 2 - Smart Lock"])

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ==================== PAYLOAD MODELS ====================

class QuickSyncPayload(PydanticBase):
    pin_request: str
    name: str
    user_id: int


# ==================== AUTO SYNC USER (QUICK TEST) ====================


class QuickSyncPayload(PydanticBase):
    pin_request: str
    name: str
    user_id: int

@router.post("/devices/{device_id}/quick-sync")
def quick_sync_user(
    device_id: str,
    payload: QuickSyncPayload,
    db: Session = Depends(get_db)
):
    pin_request = payload.pin_request
    name        = payload.name
    user_id     = payload.user_id
    """
    Endpoint otomatis: Set user ke X606-S, lalu auto-detect PIN device dan register ke cache.
    
    Request Body (JSON):
    {
        "pin_request": "00001",
        "name": "John Doe",
        "user_id": 1
    }

    Flow:
    1. SetUserInfo dengan pin_request (device akan assign PIN internal baru)
    2. GetAllUserInfo untuk cari user yang baru ditambah (match by name atau PIN2)
    3. Ambil PIN device (internal) dari response
    4. Register ke x606_user_cache dengan PIN device
    5. Return PIN device untuk referensi
    """
    pin_request = payload.pin_request
    name = payload.name
    user_id = payload.user_id
    
    device = db.query(X606Device).filter(X606Device.device_id == device_id).first()
    if not device:
        raise HTTPException(404, "Device tidak ditemukan")

    client = X606SOAPClient(ip=device.ip_address, com_key=device.com_key)

    # Step 1: Set user dengan TZ all day (0000-2359)
    import http.client
    xml_payload = (
        f'<SetUserInfo>'
        f'<ArgComKey xsi:type="xsd:integer">{device.com_key}</ArgComKey>'
        f'<Arg>'
        f'<PIN>{pin_request}</PIN>'
        f'<Name>{name}</Name>'
        f'<Privilege>0</Privilege>'
        f'<TZ1>0000-2359</TZ1>'
        f'<TZ2></TZ2>'
        f'<TZ3></TZ3>'
        f'</Arg>'
        f'</SetUserInfo>'
    )

    try:
        conn = http.client.HTTPConnection(device.ip_address, 80, timeout=5)
        headers = {"Content-Type": "text/xml"}
        conn.request("POST", "/iWsService", body=xml_payload, headers=headers)
        resp = conn.getresponse()
        body = conn.read().decode("utf-8", errors="ignore")
        conn.close()
    except Exception as e:
        return {"success": False, "message": f"Gagal koneksi ke device: {str(e)}"}

    # Step 2: Cek apakah SetUserInfo berhasil
    set_success = "Successfully" in body or "Succeed" in body or "<Result>1</Result>" in body

    # Step 3: GetAllUserInfo untuk cari user dan dapatkan PIN device
    users = client.get_all_users()

    pin_device = None
    matched_user = None

    for u in users:
        # Cari match by name atau PIN2
        if u.get("Name") == name or u.get("PIN2") == pin_request:
            pin_device = u.get("PIN")
            matched_user = u
            break

    if not pin_device:
        return {
            "success": False,
            "message": f"User {name} tidak ditemukan di device setelah SetUserInfo. Response: {body[:200]}",
            "users_found": len(users)
        }

    # Step 4: Refresh DB
    client.refresh_db()

    # Step 5: Register ke cache dengan PIN device
    cache = db.query(X606UserCache).filter(
        X606UserCache.device_id == device_id,
        X606UserCache.pin == pin_device
    ).first()

    if not cache:
        cache = X606UserCache(
            device_id=device_id,
            pin=pin_device,           # PIN device (internal)
            user_id=user_id,
            name=name
        )
        db.add(cache)
    else:
        cache.name = name
        cache.last_sync = datetime.now()

    db.commit()

    return {
        "success": True,
        "message": f"User {name} berhasil di-sync",
        "pin_request": pin_request,      # PIN yang kita kirim (00001)
        "pin_device": pin_device,         # PIN device yang di-assign (12, 13, ...)
        "user_info": matched_user,
        "raw_response": body[:200]
    }

@router.post("/devices/{device_id}/quick-test-scan")
def quick_test_scan(device_id: str, db: Session = Depends(get_db)):
    """
    Pull log dan proses tanpa cek jadwal. Semua scan = HADIR.
    """
    device = db.query(X606Device).filter(X606Device.device_id == device_id).first()
    if not device:
        raise HTTPException(404, "Device tidak ditemukan")

    client = X606SOAPClient(ip=device.ip_address, com_key=device.com_key)

    try:
        logs = client.get_logs("All")
    except Exception as e:
        raise HTTPException(400, f"Gagal koneksi: {str(e)}")

    new_records = 0
    for log in logs:
        pin = log.get("PIN", "")
        dt_str = log.get("DateTime", "")
        verified = log.get("Verified", "")
        status = log.get("Status", "")

        if not pin or not dt_str:
            continue

        try:
            scan_time = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
        except ValueError:
            continue

        # Cek duplikat
        exists = db.query(AbsensiX606).filter(
            AbsensiX606.device_id == device_id,
            AbsensiX606.waktu_scan == scan_time
        ).first()
        if exists:
            continue

        # Cari user cache - try PIN device dan PIN2
        cache = db.query(X606UserCache).filter(
            X606UserCache.device_id == device_id,
            X606UserCache.pin == pin
        ).first()

        if not cache:
            # Coba dengan leading zeros
            cache = db.query(X606UserCache).filter(
                X606UserCache.device_id == device_id,
                X606UserCache.pin == pin.zfill(5)
            ).first()

        if cache:
            absensi = AbsensiX606(
                user_id=cache.user_id,
                ruangan_id=device.ruangan_id or 0,
                device_id=device_id,
                waktu_scan=scan_time,
                verified=verified,
                status_scan=status,
                status_absensi=StatusAbsensiX606.HADIR,
                is_valid_jadwal=True,
                keterangan="Quick test - tanpa jadwal"
            )
            db.add(absensi)
            new_records += 1
        else:
            # Still record but mark as unknown
            absensi = AbsensiX606(
                user_id=0,
                ruangan_id=device.ruangan_id or 0,
                device_id=device_id,
                waktu_scan=scan_time,
                verified=verified,
                status_scan=status,
                status_absensi=StatusAbsensiX606.TIDAK_TERJADWAL,
                is_valid_jadwal=False,
                keterangan=f"PIN {pin} tidak terdaftar di cache"
            )
            db.add(absensi)
            new_records += 1

    device.last_sync = datetime.now()
    db.commit()

    return {
        "success": True,
        "device_id": device_id,
        "new_records": new_records,
        "message": f"Berhasil pull {new_records} log (quick test)"
    }

# ==================== JADWAL KBM ====================

@router.post("/jadwal", response_model=X606JadwalKBMOut)
def create_jadwal(data: X606JadwalKBMCreate, db: Session = Depends(get_db)):
    try:
        dump = data.model_dump(exclude={"peserta_ids"})
        if "hari" in dump and hasattr(dump["hari"], "value"):
            dump["hari"] = dump["hari"].value

        jadwal = X606JadwalKBM(**dump)
        db.add(jadwal)
        db.flush()
        for uid in data.peserta_ids:
            db.add(X606JadwalPeserta(jadwal_id=jadwal.id, user_id=uid))
        db.commit()
        db.refresh(jadwal)
        return jadwal
    except Exception as e:
        db.rollback()
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@router.get("/jadwal", response_model=List[X606JadwalKBMOut])
def list_jadwal(ruangan_id: Optional[int] = None, db: Session = Depends(get_db)):
    q = db.query(X606JadwalKBM)
    if ruangan_id:
        q = q.filter(X606JadwalKBM.ruangan_id == ruangan_id)
    return q.all()

@router.get("/jadwal/{jadwal_id}", response_model=X606JadwalKBMOut)
def get_jadwal(jadwal_id: int, db: Session = Depends(get_db)):
    j = db.query(X606JadwalKBM).filter(X606JadwalKBM.id == jadwal_id).first()
    if not j:
        raise HTTPException(404, "Jadwal tidak ditemukan")
    return j

@router.put("/jadwal/{jadwal_id}", response_model=X606JadwalKBMOut)
def update_jadwal(jadwal_id: int, data: X606JadwalKBMUpdate, db: Session = Depends(get_db)):
    j = db.query(X606JadwalKBM).filter(X606JadwalKBM.id == jadwal_id).first()
    if not j:
        raise HTTPException(404, "Jadwal tidak ditemukan")
    for k, v in data.model_dump(exclude_unset=True).items():
        if k == "peserta_ids" and v is not None:
            db.query(X606JadwalPeserta).filter(X606JadwalPeserta.jadwal_id == jadwal_id).delete()
            for uid in v:
                db.add(X606JadwalPeserta(jadwal_id=jadwal_id, user_id=uid))
        elif k == "hari" and hasattr(v, "value"):
            setattr(j, k, v.value)
        else:
            setattr(j, k, v)
    db.commit()
    db.refresh(j)
    return j

@router.delete("/jadwal/{jadwal_id}")
def delete_jadwal(jadwal_id: int, db: Session = Depends(get_db)):
    j = db.query(X606JadwalKBM).filter(X606JadwalKBM.id == jadwal_id).first()
    if not j:
        raise HTTPException(404, "Jadwal tidak ditemukan")
    db.delete(j)
    db.commit()
    return {"success": True}

# ==================== CEK AKSES REAL-TIME ====================

@router.get("/ruangan/{ruangan_id}/cek-akses/{user_id}", response_model=LabAccessCheck)
def cek_akses(ruangan_id: int, user_id: int, db: Session = Depends(get_db)):
    svc = X606LabService(db)
    access = svc.check_user_access(user_id, ruangan_id)
    user = db.query(User).filter(User.id == user_id).first()
    return LabAccessCheck(
        user_id=user_id,
        user_name=user.nama if user else "Unknown",
        can_access=access["can_access"],
        reason=access["reason"],
        jadwal_aktif=access["jadwal"]
    )

# ==================== ABSENSI ====================

@router.get("/absensi", response_model=List[AbsensiX606Out])
def list_absensi(
    ruangan_id: Optional[int] = None,
    user_id: Optional[int] = None,
    tanggal: Optional[str] = None,
    db: Session = Depends(get_db)
):
    q = db.query(AbsensiX606)
    if ruangan_id:
        q = q.filter(AbsensiX606.ruangan_id == ruangan_id)
    if user_id:
        q = q.filter(AbsensiX606.user_id == user_id)
    if tanggal:
        d = datetime.strptime(tanggal, "%Y-%m-%d").date()
        q = q.filter(
            AbsensiX606.waktu_scan >= datetime.combine(d, time.min),
            AbsensiX606.waktu_scan <= datetime.combine(d, time.max)
        )
    return q.order_by(AbsensiX606.waktu_scan.desc()).all()

@router.get("/absensi/ringkasan-harian")
def ringkasan_harian(tanggal: str, ruangan_id: int, db: Session = Depends(get_db)):
    d = datetime.strptime(tanggal, "%Y-%m-%d").date()
    start = datetime.combine(d, time.min)
    end = datetime.combine(d, time.max)
    q = db.query(AbsensiX606).filter(
        AbsensiX606.ruangan_id == ruangan_id,
        AbsensiX606.waktu_scan >= start,
        AbsensiX606.waktu_scan <= end
    )
    hadir = q.filter(AbsensiX606.status_absensi == StatusAbsensiX606.HADIR).count()
    terlambat = q.filter(AbsensiX606.status_absensi == StatusAbsensiX606.TERLAMBAT).count()
    tidak_terjadwal = q.filter(AbsensiX606.status_absensi == StatusAbsensiX606.TIDAK_TERJADWAL).count()
    hari_map = {
        "Monday": "Senin", "Tuesday": "Selasa", "Wednesday": "Rabu",
        "Thursday": "Kamis", "Friday": "Jumat", "Saturday": "Sabtu", "Sunday": "Minggu"
    }
    hari = hari_map[d.strftime("%A")]
    jadwals = db.query(X606JadwalKBM).filter(
        X606JadwalKBM.ruangan_id == ruangan_id,
        X606JadwalKBM.hari == hari
    ).all()
    total_peserta = sum(len(j.peserta) for j in jadwals)
    hadir_unique = db.query(AbsensiX606.user_id).filter(
        AbsensiX606.ruangan_id == ruangan_id,
        AbsensiX606.waktu_scan >= start,
        AbsensiX606.waktu_scan <= end,
        AbsensiX606.is_valid_jadwal == True
    ).distinct().count()
    alfa = max(0, total_peserta - hadir_unique)
    return {
        "tanggal": tanggal, "ruangan_id": ruangan_id,
        "hadir": hadir, "terlambat": terlambat,
        "tidak_terjadwal": tidak_terjadwal, "alfa": alfa,
        "total_jadwal": len(jadwals), "total_peserta": total_peserta
    }

# ==================== SYNC & PULL LOGS ====================

@router.post("/devices/{device_id}/sync-jadwal/{jadwal_id}")
def sync_jadwal_ke_device(device_id: str, jadwal_id: int, db: Session = Depends(get_db)):
    svc = X606LabService(db)
    result = svc.sync_users_to_device(device_id, jadwal_id)
    if not result["success"]:
        raise HTTPException(400, result["message"])
    return result

@router.post("/devices/{device_id}/pull-logs", response_model=PullLogResponse)
def pull_logs(device_id: str, db: Session = Depends(get_db)):
    svc = X606LabService(db)
    result = svc.pull_logs_from_device(device_id)
    if not result["success"]:
        raise HTTPException(400, result["message"])
    return PullLogResponse(**result)

@router.post("/devices/{device_id}/disable-all")
def disable_all_users(device_id: str, db: Session = Depends(get_db)):
    svc = X606LabService(db)
    result = svc.clear_users_from_device(device_id)
    return result

# ==================== USER CACHE ====================

@router.get("/devices/{device_id}/user-cache")
def get_user_cache(device_id: str, db: Session = Depends(get_db)):
    caches = db.query(X606UserCache).filter(X606UserCache.device_id == device_id).all()
    return [{"pin": c.pin, "user_id": c.user_id, "name": c.name} for c in caches]

@router.post("/devices/{device_id}/user-cache")
def add_user_cache(
    device_id: str,
    data: X606UserCacheCreate,
    db: Session = Depends(get_db)
):
    cache = X606UserCache(
        device_id=device_id,
        pin=data.pin,
        user_id=data.user_id,
        name=data.name
    )
    db.add(cache)
    db.commit()

    return {"success": True}