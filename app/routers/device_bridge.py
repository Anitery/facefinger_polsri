"""
Device Bridge API — berjalan di Railway
Menyediakan endpoint untuk komunikasi dengan local bridge script.
"""
from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
    Header,
    Request,
    Query
)
from sqlalchemy import func
from sqlalchemy.orm import Session, joinedload
from pydantic import BaseModel
from typing import List, Optional
from datetime import datetime, timedelta, timezone, date
import os
import logging
import traceback

log = logging.getLogger(__name__)

from app.database import get_db
from app.models.models import (
    User,
    AccessLog,
    JadwalRuangan,
    Absensi,
    BridgeHeartbeat,
    Ruangan,
    PengaturanSistem,
)
from app.routers.pengaturan import get_pengaturan

router = APIRouter(prefix="/device-bridge", tags=["Device Bridge"])

BRIDGE_API_KEY = os.getenv("BRIDGE_API_KEY", "bridge-key-polsri-2026")

# Definisikan Timezone WIB (UTC+7)
WIB = timezone(timedelta(hours=7))

def wib_now() -> datetime:
    """Mengembalikan datetime saat ini dalam timezone WIB."""
    return datetime.now(timezone.utc).astimezone(WIB)

def wib_today_str() -> str:
    """Tanggal hari ini dalam format STRING (YYYY-MM-DD) berbasis WIB."""
    return wib_now().strftime("%Y-%m-%d")

# Mapping kode Verified dari device ke metode database
VERIFY_MAP = {
    "0":   "password",
    "1":   "fingerprint",
    "2":   "fingerprint",
    "3":   "password",    
    "4":   "face",
    "5":   "face",
    "6":   "face",
    "7":   "face",
    "9":   "face",
    "15":  "face",        
    "200": "other",
}

ROLE_BEBAS = {"admin", "teknisi"}


def verify_key(x_api_key: str = Header(...)):
    if x_api_key != BRIDGE_API_KEY:
        raise HTTPException(403, "API key tidak valid")
    return x_api_key


# ── Helper: Validasi Jadwal KBM ─────────────────────────
def cek_akses_device(
    ruangan_id: int, user_id: int,
    role: str, waktu: datetime, db: Session
):
    pengaturan = get_pengaturan(db)

    # Mode pemeliharaan: tolak semua akses KECUALI admin/teknisi,
    # supaya mereka tetap bisa masuk untuk perbaikan.
    if pengaturan.mode_pemeliharaan and role not in ROLE_BEBAS:
        return False, "Sistem sedang dalam mode pemeliharaan", None

    if role in ROLE_BEBAS:
        return True, f"Akses bebas ({role})", None

    # Jadwal dinonaktifkan sepenuhnya — semua scan langsung berhasil
    # tanpa validasi jadwal KBM (tidak ada pencatatan presensi otomatis
    # karena tidak ada jadwal_id untuk diacu).
    if not pengaturan.wajib_jadwal:
        return True, "Akses berhasil (mode jadwal dinonaktifkan)", None

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
    db: Session, jadwal_id: int, user_id: int, jam_mulai: str, waktu_scan: datetime
):
    existing = db.query(Absensi).filter(
        Absensi.jadwal_id == jadwal_id,
        Absensi.user_id   == user_id
    ).first()

    today  = waktu_scan.strftime("%Y-%m-%d")
    jam_dt = datetime.strptime(
        f"{today} {jam_mulai}",
        "%Y-%m-%d %H:%M"
    ).replace(tzinfo=WIB)

    toleransi = get_pengaturan(db).toleransi_keterlambatan_menit
    selisih = (waktu_scan - jam_dt).total_seconds() / 60
    status  = "hadir" if selisih <= toleransi else "terlambat"

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
        "time":   wib_now().isoformat()
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
    Return semua user aktif dengan id_perangkat.
    Bridge akan set user ini ke device via SOAP SetUserInfo.
    """
    users = db.query(User).filter(
        User.aktif          == True,
        User.id_perangkat != None
    ).all()

    return [
        {
            "user_id":        u.id,
            "id_perangkat":   u.id_perangkat,
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
    Return jadwal hari ini + id_perangkat mahasiswa per jadwal.
    """
    today   = wib_today_str()
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
            "id_perangkat_diizinkan": [
                m.id_perangkat
                for m in j.mahasiswa_diizinkan
                if m.id_perangkat is not None
            ],
        }
        for j in jadwals
    ]


# ══════════════════════════════════════════════════════════
# ENDPOINT 4 — Terima log dari bridge, proses, simpan
# ══════════════════════════════════════════════════════════
class LogItem(BaseModel):
    pin:        str
    datetime:   str   # "YYYY-MM-DD HH:MM:SS+07:00" atau naive string
    verified:   int   # 0=password, 1=fingerprint, 15=face
    status:     int   # 0=masuk, 1=keluar
    workcode:   str = "0"


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
    berhasil = 0
    ditolak  = 0
    duplikat = 0
    error    = 0

    log.info(f"TOTAL LOGS: {len(payload.logs)}")

    for log_item in payload.logs:
        log.info(f"PIN={log_item.pin} verified={log_item.verified} datetime={log_item.datetime}")
        try:
            # ── Parse waktu ──────────────────────────────
            dt_str = log_item.datetime
            try:
                if "+07:00" in dt_str:
                    waktu = datetime.fromisoformat(dt_str).astimezone(WIB)
                else:
                    waktu = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
                    waktu = waktu.replace(tzinfo=WIB)
            except (ValueError, TypeError) as e:
                log.warning(f"Parse waktu gagal '{dt_str}': {e}")
                error += 1
                continue

            # ── Tentukan metode verifikasi ───────────────
            metode = VERIFY_MAP.get(str(log_item.verified), "other")

            # ── Cari user berdasarkan id_perangkat ────
            try:
                perangkat_id = int(log_item.pin)
            except ValueError:
                perangkat_id = None

            user = None
            if perangkat_id is not None:
                user = db.query(User).filter(
                    User.id_perangkat == perangkat_id,
                    User.aktif == True
                ).first()

            # ── User tidak ditemukan ─────────────────────
            if not user:
                dup = db.query(AccessLog).filter(
                    AccessLog.ruangan_id == payload.ruangan_id,
                    AccessLog.waktu_akses == waktu,
                    AccessLog.keterangan.contains(f"PIN:{log_item.pin}")
                ).first()
                
                if dup:
                    duplikat += 1
                    continue

                keterangan = f"PIN:{log_item.pin} tidak terdaftar | {metode} | SN:{payload.device_sn}"[:200]

                db.add(AccessLog(
                    user_id     = None,
                    ruangan_id  = payload.ruangan_id,
                    waktu_akses = waktu,
                    metode      = metode,
                    status      = "ditolak",
                    keterangan  = keterangan
                ))
                db.commit()
                ditolak += 1
                continue

            # ── Cek duplikat untuk user terdaftar ──────────
            dup = db.query(AccessLog).filter(
                AccessLog.user_id == user.id,
                AccessLog.ruangan_id == payload.ruangan_id,
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
            keterangan = f"{alasan} | {metode} | SN:{payload.device_sn}"[:200]

            db.add(AccessLog(
                user_id     = user.id,
                ruangan_id  = payload.ruangan_id,
                waktu_akses = waktu,
                metode      = metode,
                status      = status_akses,
                keterangan  = keterangan
            ))
            db.commit()

            # ── Catat absensi jika berhasil + ada jadwal ─
            if boleh and jadwal_aktif:
                if user.role == "mahasiswa":
                    catat_absensi_device(
                        db         = db,
                        jadwal_id  = jadwal_aktif.id,
                        user_id    = user.id,
                        jam_mulai  = jadwal_aktif.jam_mulai,
                        waktu_scan = waktu
                    )
                    log.info(f"ABSENSI BERHASIL: user={user.id} | jadwal={jadwal_aktif.id}")
                else:
                    log.info(f"ABSENSI DIABAIKAN: user={user.id} bukan mahasiswa (role: {user.role})")

            if boleh:
                berhasil += 1
                log.info(f"✓ PIN:{log_item.pin} ({user.nama}) — {alasan}")
            else:
                ditolak += 1
                log.info(f"✗ PIN:{log_item.pin} ({user.nama}) — {alasan}")

        except Exception as e:
            log.error(f"[BRIDGE ERROR] PIN:{log_item.pin} -> {str(e)}")
            log.error(traceback.format_exc())
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
def request_sync(ruangan_id: int, key=Depends(verify_key)):
    """
    Tandai bahwa sync diperlukan.
    Bridge akan melakukan sync saat polling berikutnya.
    """
    return {
        "status":     "sync_requested",
        "ruangan_id": ruangan_id,
        "message":    "Bridge akan sync dalam interval berikutnya"
    }


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
    Bridge kirim daftar user yang ada di device untuk reverse-sync ke DB Cloud.
    """
    updated = 0
    for du in payload.device_users:
        try:
            perangkat_id = int(du.pin)
        except ValueError:
            continue

        user = db.query(User).filter(
            User.id_perangkat == perangkat_id,
            User.aktif          == True
        ).first()

        if not user:
            if not du.name or not du.name.strip():
                continue
            
            # Ambil potongan nama depan untuk meraba nama di DB
            nama_depan = du.name.split()[0]
            user = db.query(User).filter(
                User.nama.ilike(f"%{nama_depan}%"),
                User.aktif == True
            ).first()
            
            if user and not user.id_perangkat:
                user.id_perangkat = perangkat_id
                db.commit()
                updated += 1
                log.info(f"Auto-mapped: {user.nama} → ID Perangkat:{perangkat_id}")

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
    """Info lengkap untuk paket inisialisasi awal bridge local."""
    users = db.query(User).filter(
        User.aktif          == True,
        User.id_perangkat != None
    ).all()

    today = wib_today_str()
    jadwals = db.query(JadwalRuangan).options(
        joinedload(JadwalRuangan.mahasiswa_diizinkan)
    ).filter(
        JadwalRuangan.ruangan_id == ruangan_id,
        JadwalRuangan.tanggal    == today
    ).all()

    return {
        "users": [
            {
                "id_perangkat":   u.id_perangkat,
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
                "id_perangkat_diizinkan": [
                    m.id_perangkat
                    for m in j.mahasiswa_diizinkan
                    if m.id_perangkat
                ],
            }
            for j in jadwals
        ],
        "server_time": wib_now().isoformat(),
        "today":       today,
    }


@router.post("/status")
def bridge_heartbeat(
    request: Request,
    device_sn: str = Query(default=""),
    device_ip: str = Query(default=""),
    device_time: str = Query(default=""),
    total_user: int = Query(default=0),
    ruangan_id: int = Query(default=0),
    key=Depends(verify_key),
    db: Session = Depends(get_db)
):
    """
    Bridge ping endpoint — menyimpan detak heartbeat berkala ke DB.
    """
    now_utc = datetime.now(timezone.utc)
    hb = db.query(BridgeHeartbeat).filter(
        BridgeHeartbeat.device_sn == device_sn
    ).first()

    if hb:
        hb.device_ip   = device_ip
        hb.device_time = device_time
        hb.total_user  = total_user
        hb.ruangan_id  = ruangan_id
        hb.last_seen   = now_utc
    else:
        hb = BridgeHeartbeat(
            device_sn   = device_sn,
            device_ip   = device_ip,
            device_time = device_time,
            total_user  = total_user,
            ruangan_id  = ruangan_id,
            last_seen   = now_utc
        )
        db.add(hb)

    db.commit()
    return {
        "status": "ok",
        "time": wib_now().isoformat()
    }


@router.get("/status-public")
def bridge_status_public(
    ruangan_id: int,
    role: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Status bridge + info device ringkas dan identitas ruangan untuk dashboard sipil."""
    hb = db.query(BridgeHeartbeat).filter(
        BridgeHeartbeat.ruangan_id == ruangan_id
    ).order_by(
        BridgeHeartbeat.last_seen.desc()
    ).first()

    bridge_aktif = False
    device_ip    = "—"
    device_sn    = "—"
    device_time  = "—"
    last_bridge  = "—"
    total_user   = 0

    if hb and hb.last_seen:
        last_seen_utc = hb.last_seen if hb.last_seen.tzinfo else hb.last_seen.replace(tzinfo=timezone.utc)
        diff = (datetime.now(timezone.utc) - last_seen_utc).total_seconds()
        bridge_aktif = diff < 300

        device_ip   = hb.device_ip or "—"
        device_sn   = hb.device_sn or "—"
        device_time = hb.device_time or "—"
        total_user  = hb.total_user or 0
        last_bridge = last_seen_utc.astimezone(WIB).strftime("%d/%m %H:%M:%S")

    # Sensor IP disembunyikan jika diaktifkan di Pengaturan Sistem —
    # admin/teknisi tetap melihat IP asli untuk keperluan troubleshooting.
    pengaturan = get_pengaturan(db)
    device_ip_display = device_ip
    if pengaturan.sembunyikan_ip and role not in ROLE_BEBAS:
        device_ip_display = "Terhubung" if bridge_aktif else "—"

    # ── Identitas Ruangan & Penanggung Jawab ─────────────────
    ruangan = db.query(Ruangan).options(
        joinedload(Ruangan.penanggung_jawab)
    ).filter(Ruangan.id == ruangan_id).first()

    pj_list = []
    if ruangan and hasattr(ruangan, "penanggung_jawab") and ruangan.penanggung_jawab:
        pj_list = [
            {"nama": u.nama, "role": u.role}
            for u in ruangan.penanggung_jawab
        ]

    today = wib_today_str()
    jadwals = db.query(JadwalRuangan).options(
        joinedload(JadwalRuangan.mahasiswa_diizinkan)
    ).filter(
        JadwalRuangan.ruangan_id == ruangan_id,
        JadwalRuangan.tanggal == today
    ).all()

    log_hari_ini = db.query(AccessLog).filter(
        AccessLog.ruangan_id == ruangan_id,
        func.date(AccessLog.waktu_akses) == func.date(datetime.now(timezone.utc).astimezone(WIB))
    ).count()

    return {
        "bridge_aktif": bridge_aktif,
        "last_bridge": last_bridge,
        "device_ip": device_ip_display,
        "device_sn": device_sn,
        "device_time": device_time,
        "total_user_device": total_user,
        "log_hari_ini": log_hari_ini,
        "identitas_ruangan": {
            "nama":             ruangan.nama if ruangan else "—",
            "lokasi":           ruangan.lokasi if ruangan else "—",
            "lantai":           getattr(ruangan, "lantai", None) if ruangan else None,
            "penanggung_jawab": pj_list,
        },
        "jadwal_hari_ini": [
            {
                "jadwal_id": j.id,
                "nama_kegiatan": j.nama_kegiatan,
                "kelas": j.kelas,
                "jam_mulai": j.jam_mulai,
                "jam_selesai": j.jam_selesai,
                "dosen": j.dosen,
                "id_perangkat_diizinkan": [
                    m.id_perangkat
                    for m in j.mahasiswa_diizinkan
                    if m.id_perangkat
                ],
            }
            for j in jadwals
        ],
    }


@router.get("/debug-logs")
def debug_recent_logs(
    limit: int = 10,
    key=Depends(verify_key),
    db: Session = Depends(get_db)
):
    """Melihat riwayat log akses masuk terbaru untuk kebutuhan debugging."""
    logs = db.query(AccessLog).options(
        joinedload(AccessLog.user)
    ).order_by(
        AccessLog.waktu_akses.desc()
    ).limit(limit).all()

    return [
        {
            "id":          l.id,
            "waktu":       l.waktu_akses.isoformat() if l.waktu_akses else None,
            "user_id":     l.user_id,
            "nama":        l.user.nama if l.user else "TIDAK DIKENAL",
            "nim_nip":     l.user.nim_nip if l.user else "—",
            "id_perangkat":l.user.id_perangkat if l.user else "—",
            "metode":      l.metode,
            "status":      l.status,
            "keterangan":  l.keterangan,
            "ruangan_id":  l.ruangan_id,
        }
        for l in logs
    ]


@router.get("/status-semua-ruangan")
def status_semua_ruangan(role: Optional[str] = None, db: Session = Depends(get_db)):
    """Memantau detak online/offline semua ruangan sekaligus (Bulk Query)."""
    pengaturan = get_pengaturan(db)
    sembunyikan = pengaturan.sembunyikan_ip and role not in ROLE_BEBAS

    ruangans = db.query(Ruangan).filter(
        Ruangan.aktif == True
    ).order_by(Ruangan.id).all()

    if not ruangans:
        return []

    ruangan_ids = [r.id for r in ruangans]

    # Subquery: optimasi performa mengambil heartbeat id terakhir dari tiap ruangan
    latest_hb_ids = db.query(
        func.max(BridgeHeartbeat.id)
    ).filter(
        BridgeHeartbeat.ruangan_id.in_(ruangan_ids)
    ).group_by(BridgeHeartbeat.ruangan_id).subquery()

    heartbeats = db.query(BridgeHeartbeat).filter(
        BridgeHeartbeat.id.in_(latest_hb_ids)
    ).all()

    hb_map = {hb.ruangan_id: hb for hb in heartbeats}
    hasil = []
    batas_online = datetime.now(timezone.utc) - timedelta(minutes=2)

    for r in ruangans:
        hb = hb_map.get(r.id)

        bridge_aktif = False
        last_bridge  = None
        device_ip    = None
        device_sn    = None
        device_time  = None

        # Perbaikan aman dari crash NoneType jika ruangan belum pernah menyimpan heartbeat
        if hb:
            device_ip   = hb.device_ip
            device_sn   = hb.device_sn
            device_time = hb.device_time
            if hb.last_seen:
                last_seen_utc = hb.last_seen if hb.last_seen.tzinfo else hb.last_seen.replace(tzinfo=timezone.utc)
                last_bridge  = last_seen_utc.astimezone(WIB).isoformat()
                bridge_aktif = last_seen_utc > batas_online

        hasil.append({
            "ruangan_id":   r.id,
            "nama_ruangan": r.nama,
            "lokasi":       r.lokasi or "—",
            "bridge_aktif": bridge_aktif,
            "last_bridge":  last_bridge,
            "device_ip":    ("Terhubung" if bridge_aktif else "—") if sembunyikan else device_ip,
            "device_sn":    device_sn,
            "device_time":  device_time,
        })

    return hasil