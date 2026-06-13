"""
Device Bridge API — berjalan di Railway
Menyediakan endpoint untuk komunikasi dengan local bridge script.
"""
from fastapi import APIRouter, Depends, HTTPException, Header
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, date
import os

from app.database import get_db
from app.models.models import User, AccessLog, JadwalRuangan, Absensi

router = APIRouter(prefix="/device-bridge", tags=["Device Bridge"])

BRIDGE_API_KEY = os.getenv("BRIDGE_API_KEY", "bridge-key-polsri-2026")

# Mapping kode Verified dari device ke metode
VERIFY_MAP = {
    "0": "password",
    "1": "fingerprint", "2": "fingerprint", "3": "fingerprint",
    "4": "face",        "5": "face",        "6": "face",
    "15": "password",
}

ROLE_BEBAS = {"admin", "teknisi"}


def verify_key(x_api_key: str = Header(...)):
    if x_api_key != BRIDGE_API_KEY:
        raise HTTPException(403, "API key tidak valid")
    return x_api_key


# ── Helper: validasi jadwal KBM ─────────────────────────
def cek_akses_device(
    ruangan_id: int, user_id: int,
    role: str, waktu: datetime, db: Session
):
    if role in ROLE_BEBAS:
        return True, f"Akses bebas ({role})", None

    today    = waktu.strftime("%Y-%m-%d")
    now_time = waktu.strftime("%H:%M")

    jadwal = db.query(JadwalRuangan).options(
        joinedload(JadwalRuangan.mahasiswa_diizinkan)
    ).filter(
        JadwalRuangan.ruangan_id  == ruangan_id,
        JadwalRuangan.tanggal     == today,
        JadwalRuangan.jam_mulai   <= now_time,
        JadwalRuangan.jam_selesai >  now_time,
    ).first()

    if not jadwal:
        return False, "Tidak ada jadwal aktif saat ini", None

    mhs_ids = [m.id for m in jadwal.mahasiswa_diizinkan]

    if role == "dosen":
        return True, f"Dosen — {jadwal.nama_kegiatan}", jadwal

    if not mhs_ids:
        return True, f"Jadwal terbuka — {jadwal.nama_kegiatan}", jadwal

    if user_id in mhs_ids:
        return True, f"{jadwal.nama_kegiatan} ({jadwal.kelas or ''})", jadwal

    return (
        False,
        f"Tidak terdaftar di {jadwal.nama_kegiatan} "
        f"({jadwal.kelas or ''})",
        None
    )


def catat_absensi_device(
    db, jadwal_id, user_id, jam_mulai, waktu_scan
):
    existing = db.query(Absensi).filter(
        Absensi.jadwal_id == jadwal_id,
        Absensi.user_id   == user_id
    ).first()

    today  = waktu_scan.strftime("%Y-%m-%d")
    jam_dt = datetime.strptime(
        f"{today} {jam_mulai}", "%Y-%m-%d %H:%M"
    )
    selisih = (waktu_scan - jam_dt).total_seconds() / 60
    status  = "hadir" if selisih <= 15 else "terlambat"

    if existing:
        if existing.status == "tidak_hadir":
            existing.waktu_masuk = waktu_scan
            existing.status      = status
            db.commit()
        return existing

    ab = Absensi(
        jadwal_id   = jadwal_id,
        user_id     = user_id,
        waktu_masuk = waktu_scan,
        status      = status
    )
    db.add(ab)
    db.commit()
    db.refresh(ab)
    return ab


# ══════════════════════════════════════════════════════════
# ENDPOINT 1 — Status / Health Check
# ══════════════════════════════════════════════════════════
@router.get("/status")
def bridge_status(key=Depends(verify_key)):
    return {
        "status": "online",
        "server": "SmartDoorLock Railway",
        "time":   datetime.now().isoformat()
    }


# ══════════════════════════════════════════════════════════
# ENDPOINT 2 — Daftar user untuk sync ke device
# ══════════════════════════════════════════════════════════
@router.get("/users")
def get_users_for_device(
    key=Depends(verify_key),
    db: Session = Depends(get_db)
):
    """
    Return semua user aktif dengan fingerprint_id.
    Bridge akan set user ini ke device via SOAP SetUserInfo.
    fingerprint_id = PIN yang dipakai di device.
    """
    users = db.query(User).filter(
        User.aktif          == True,
        User.fingerprint_id != None
    ).all()

    return [
        {
            "user_id":        u.id,
            "fingerprint_id": u.fingerprint_id,
            "nama":           u.nama,
            "role":           u.role,
            "nim_nip":        u.nim_nip,
        }
        for u in users
    ]


# ══════════════════════════════════════════════════════════
# ENDPOINT 3 — Jadwal hari ini (untuk timezone device)
# ══════════════════════════════════════════════════════════
@router.get("/jadwal-hari-ini")
def get_jadwal_hari_ini(
    ruangan_id: int,
    key=Depends(verify_key),
    db: Session = Depends(get_db)
):
    """
    Return jadwal hari ini + fingerprint_id mahasiswa per jadwal.
    Bridge gunakan ini untuk set timezone akses di device.
    """
    today   = date.today().strftime("%Y-%m-%d")
    jadwals = db.query(JadwalRuangan).options(
        joinedload(JadwalRuangan.mahasiswa_diizinkan)
    ).filter(
        JadwalRuangan.ruangan_id == ruangan_id,
        JadwalRuangan.tanggal    == today
    ).order_by(JadwalRuangan.jam_mulai).all()

    return [
        {
            "jadwal_id":       j.id,
            "nama_kegiatan":   j.nama_kegiatan,
            "kelas":           j.kelas,
            "jam_mulai":       j.jam_mulai,
            "jam_selesai":     j.jam_selesai,
            "dosen":           j.dosen,
            # fingerprint_id mahasiswa yang boleh akses di jadwal ini
            "fp_ids_diizinkan": [
                m.fingerprint_id
                for m in j.mahasiswa_diizinkan
                if m.fingerprint_id is not None
            ],
        }
        for j in jadwals
    ]


# ══════════════════════════════════════════════════════════
# ENDPOINT 4 — Terima log dari bridge, proses, simpan
# ══════════════════════════════════════════════════════════
class LogItem(BaseModel):
    pin:        str
    datetime:   str   # "YYYY-MM-DD HH:MM:SS"
    verified:   str   # "1"=fp, "4"=face, "0"=password
    status:     str   # "0"=masuk, "1"=keluar


class PushLogsPayload(BaseModel):
    ruangan_id: int
    device_sn:  str
    logs:       List[LogItem]


@router.post("/push-logs")
def receive_logs(
    payload: PushLogsPayload,
    key=Depends(verify_key),
    db: Session = Depends(get_db)
):
    """
    Terima raw SOAP log dari bridge, proses:
    1. Cari user dari fingerprint_id (PIN di device)
    2. Validasi jadwal KBM
    3. Simpan ke access_log + absensi
    """
    berhasil = ditolak = duplikat = error = 0

    for log_item in payload.logs:
        try:
            # Parse waktu
            try:
                waktu = datetime.strptime(
                    log_item.datetime, "%Y-%m-%d %H:%M:%S"
                )
            except ValueError:
                error += 1
                continue

            metode = VERIFY_MAP.get(str(log_item.verified), "fingerprint")

            # Cari user berdasarkan fingerprint_id = PIN device
            try:
                fp_id = int(log_item.pin)
            except ValueError:
                fp_id = None

            user = None
            if fp_id is not None:
                user = db.query(User).filter(
                    User.fingerprint_id == fp_id,
                    User.aktif          == True
                ).first()

            # ── User tidak ditemukan ─────────────────────
            if not user:
                # Cek duplikat
                dup = db.query(AccessLog).filter(
                    AccessLog.ruangan_id  == payload.ruangan_id,
                    AccessLog.waktu_akses == waktu,
                    AccessLog.keterangan.contains(f"PIN:{log_item.pin}")
                ).first()
                if dup:
                    duplikat += 1
                    continue

                db.add(AccessLog(
                    user_id     = None,
                    ruangan_id  = payload.ruangan_id,
                    waktu_akses = waktu,
                    metode      = metode,
                    status      = "ditolak",
                    keterangan  = (f"PIN:{log_item.pin} tidak terdaftar "
                                   f"| SN:{payload.device_sn}")
                ))
                db.commit()
                ditolak += 1
                continue

            # ── Cek duplikat untuk user ini ──────────────
            dup = db.query(AccessLog).filter(
                AccessLog.user_id     == user.id,
                AccessLog.ruangan_id  == payload.ruangan_id,
                AccessLog.waktu_akses == waktu
            ).first()
            if dup:
                duplikat += 1
                continue

            # ── Validasi jadwal KBM ──────────────────────
            boleh, alasan, jadwal_aktif = cek_akses_device(
                ruangan_id = payload.ruangan_id,
                user_id    = user.id,
                role       = user.role,
                waktu      = waktu,
                db         = db
            )

            status_akses = "berhasil" if boleh else "ditolak"

            # ── Catat log akses ──────────────────────────
            db.add(AccessLog(
                user_id     = user.id,
                ruangan_id  = payload.ruangan_id,
                waktu_akses = waktu,
                metode      = metode,
                status      = status_akses,
                keterangan  = f"{alasan} | SN:{payload.device_sn}"
            ))
            db.commit()

            # ── Catat absensi jika berhasil + ada jadwal ─
            if boleh and jadwal_aktif:
                catat_absensi_device(
                    db         = db,
                    jadwal_id  = jadwal_aktif.id,
                    user_id    = user.id,
                    jam_mulai  = jadwal_aktif.jam_mulai,
                    waktu_scan = waktu
                )

            if boleh:
                berhasil += 1
            else:
                ditolak += 1

        except Exception as e:
            print(f"[BRIDGE ERROR] {log_item}: {e}")
            error += 1
            db.rollback()

    return {
        "status":   "ok",
        "berhasil": berhasil,
        "ditolak":  ditolak,
        "duplikat": duplikat,
        "error":    error,
        "total":    len(payload.logs)
    }


# ══════════════════════════════════════════════════════════
# ENDPOINT 5 — Sync manual (trigger dari dashboard)
# ══════════════════════════════════════════════════════════
@router.post("/request-sync")
def request_sync(
    ruangan_id: int,
    key=Depends(verify_key)
):
    """
    Tandai bahwa sync diperlukan.
    Bridge akan melakukan sync saat polling berikutnya.
    """
    # Untuk saat ini cukup return OK
    # Bisa diperluas dengan Redis/queue di masa depan
    return {
        "status":     "sync_requested",
        "ruangan_id": ruangan_id,
        "message":    "Bridge akan sync dalam interval berikutnya"
    }

# Tambahkan di bawah endpoint yang sudah ada

class DeviceUserItem(BaseModel):
    pin:  str
    name: str
    pin2: str = ""


class SyncEnrollmentPayload(BaseModel):
    device_sn:    str
    ruangan_id:   int
    device_users: List[DeviceUserItem]


@router.post("/sync-enrollment")
def sync_enrollment(
    payload: SyncEnrollmentPayload,
    key=Depends(verify_key),
    db: Session = Depends(get_db)
):
    """
    Bridge kirim daftar user yang ada di device.
    Server verifikasi dan update fingerprint_id jika perlu.
    """
    updated = 0
    for du in payload.device_users:
        # PIN di device = fingerprint_id di database kita
        try:
            fp_id = int(du.pin)
        except ValueError:
            continue

        # Cari user berdasarkan nama (fallback jika fp_id belum diset)
        user = db.query(User).filter(
            User.fingerprint_id == fp_id,
            User.aktif          == True
        ).first()

        if not user:
            # Coba cari by nama yang mirip
            user = db.query(User).filter(
                User.nama.ilike(f"%{du.name.split()[0]}%"),
                User.aktif == True
            ).first()
            if user and not user.fingerprint_id:
                user.fingerprint_id = fp_id
                db.commit()
                updated += 1
                log.info(
                    f"Auto-mapped: {user.nama} → FP:{fp_id}"
                )

    return {
        "status":  "ok",
        "updated": updated,
        "total":   len(payload.device_users)
    }


@router.get("/device-info")
def get_device_info(
    ruangan_id: int,
    key=Depends(verify_key),
    db: Session = Depends(get_db)
):
    """Info lengkap untuk bridge: users + jadwal hari ini."""
    users   = db.query(User).filter(
        User.aktif          == True,
        User.fingerprint_id != None
    ).all()

    today   = date.today().strftime("%Y-%m-%d")
    jadwals = db.query(JadwalRuangan).options(
        joinedload(JadwalRuangan.mahasiswa_diizinkan)
    ).filter(
        JadwalRuangan.ruangan_id == ruangan_id,
        JadwalRuangan.tanggal    == today
    ).all()

    return {
        "users": [
            {
                "fingerprint_id": u.fingerprint_id,
                "nama":           u.nama,
                "role":           u.role,
                "nim_nip":        u.nim_nip,
            }
            for u in users
        ],
        "jadwal_hari_ini": [
            {
                "jadwal_id":        j.id,
                "nama_kegiatan":    j.nama_kegiatan,
                "kelas":            j.kelas,
                "jam_mulai":        j.jam_mulai,
                "jam_selesai":      j.jam_selesai,
                "dosen":            j.dosen,
                "fp_ids_diizinkan": [
                    m.fingerprint_id
                    for m in j.mahasiswa_diizinkan
                    if m.fingerprint_id
                ],
            }
            for j in jadwals
        ],
        "server_time": datetime.now().isoformat(),
        "today":       today,
    }

# Cache status bridge (diupdate saat bridge hit /status)
_bridge_cache = {
    "last_seen":   None,
    "device_sn":   None,
    "device_ip":   None,
    "device_time": None,
}


@router.get("/status")
def bridge_status(key=Depends(verify_key)):
    """Dipanggil bridge setiap loop untuk heartbeat."""
    # Bridge kirim info tambahan via query params
    _bridge_cache["last_seen"] = datetime.now().isoformat()
    return {
        "status": "online",
        "server": "SmartDoorLock Railway",
        "time":   datetime.now().isoformat()
    }


@router.get("/status-public")
def bridge_status_public(
    ruangan_id: int,
    db: Session = Depends(get_db)
):
    """Status bridge + info device untuk dashboard (tanpa API key)."""
    last = _bridge_cache.get("last_seen")
    aktif = False
    if last:
        diff = (datetime.now() - datetime.fromisoformat(last)).seconds
        aktif = diff < 180  # bridge dianggap aktif jika < 3 menit

    # Jadwal hari ini
    today   = date.today().strftime("%Y-%m-%d")
    jadwals = db.query(JadwalRuangan).options(
        joinedload(JadwalRuangan.mahasiswa_diizinkan)
    ).filter(
        JadwalRuangan.ruangan_id == ruangan_id,
        JadwalRuangan.tanggal    == today
    ).all()

    return {
        "bridge_aktif":  aktif,
        "last_bridge":   last,
        "device_ip":     BRIDGE_API_KEY and "Terhubung",
        "device_sn":     _bridge_cache.get("device_sn", "—"),
        "device_time":   _bridge_cache.get("device_time", "—"),
        "jadwal_hari_ini": [
            {
                "jadwal_id":        j.id,
                "nama_kegiatan":    j.nama_kegiatan,
                "kelas":            j.kelas,
                "jam_mulai":        j.jam_mulai,
                "jam_selesai":      j.jam_selesai,
                "fp_ids_diizinkan": [
                    m.fingerprint_id
                    for m in j.mahasiswa_diizinkan
                    if m.fingerprint_id
                ],
            }
            for j in jadwals
        ],
        "total_user_device": None,
    }
