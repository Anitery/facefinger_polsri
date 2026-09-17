"""
Device Bridge API — berjalan di server rack lokal (FastAPI + Nginx)
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
    BiometricTemplate,
    UserDeviceSync,
)
from app.routers.pengaturan import get_pengaturan
from app.services.auth_service import get_current_user_session
import requests

router = APIRouter(prefix="/device-bridge", tags=["Device Bridge"])

BRIDGE_API_KEY = os.getenv("BRIDGE_API_KEY", "bridge-key-polsri-2026")

# Kredensial admin panel bawaan X606-S — SEKARANG dipakai oleh door_service.py
# yang jalan di STB (bukan langsung dari server ini), karena server mungkin
# tidak satu jaringan langsung dengan device.
DEVICE_WEBPANEL_USER = os.getenv("DEVICE_WEBPANEL_USER", "1")
DEVICE_WEBPANEL_PASS = os.getenv("DEVICE_WEBPANEL_PASS", "8888")

# door_service.py berjalan di STB (satu jaringan dengan device). Server ini
# memanggilnya lewat HTTP biasa, bukan menghubungi device secara langsung.
#
# CATATAN MULTI-DEVICE:
# Dulu di sini cuma ada 1 DOOR_SERVICE_URL global dari .env — jadi semua
# ruangan (walaupun door_service-nya beda port/beda STB) selalu diarahkan
# ke 1 alamat yang sama. Itu sebabnya multi-lab tidak bisa jalan tanpa
# hack manual. Sekarang resolusinya per-ruangan_id lewat resolve_door_service()
# di bawah, dengan urutan prioritas: kolom DB Ruangan.door_service_url →
# pola env DOOR_SERVICE_URL_L{ruangan_id} → fallback DOOR_SERVICE_URL lama
# (untuk kompatibilitas deployment single-lab yang belum diisi kolom DB-nya).
DOOR_SERVICE_API_KEY_DEFAULT = os.getenv("DOOR_SERVICE_API_KEY", "ganti-key-ini-di-env")
DOOR_SERVICE_URL_FALLBACK    = os.getenv("DOOR_SERVICE_URL")  # boleh kosong


def resolve_door_service(ruangan_id: int, db: Session) -> "tuple[str, str]":
    """
    Tentukan (url, api_key) door_service.py yang benar untuk sebuah ruangan.

    Prioritas:
      1. Ruangan.door_service_url (diatur admin lewat dashboard/endpoint
         PATCH /ruangan/{id}/door-service) — cara utama untuk multi-STB/
         multi-port tanpa perlu redeploy backend.
      2. Environment variable pola DOOR_SERVICE_URL_L{ruangan_id}, contoh
         DOOR_SERVICE_URL_L3=http://10.17.47.163:8103 — berguna kalau mau
         atur lewat .env server rack tanpa sentuh DB.
      3. DOOR_SERVICE_URL lama (satu alamat global) — fallback supaya
         deployment lama/single-lab yang belum migrasi tetap jalan.

    Raise HTTPException(400) kalau tidak ada satupun yang cocok, supaya
    error-nya jelas ("ruangan X belum dikonfigurasi") daripada diam-diam
    salah kirim ke STB/port yang salah.
    """
    ruangan = db.query(Ruangan).filter(Ruangan.id == ruangan_id).first()

    if ruangan and ruangan.door_service_url:
        url = ruangan.door_service_url.rstrip("/")
        key = ruangan.door_service_api_key or DOOR_SERVICE_API_KEY_DEFAULT
        return url, key

    env_url = os.getenv(f"DOOR_SERVICE_URL_L{ruangan_id}")
    if env_url:
        return env_url.rstrip("/"), DOOR_SERVICE_API_KEY_DEFAULT

    if DOOR_SERVICE_URL_FALLBACK:
        log.warning(
            f"Ruangan {ruangan_id} belum punya door_service_url sendiri — "
            f"pakai DOOR_SERVICE_URL fallback global ({DOOR_SERVICE_URL_FALLBACK}). "
            f"Ini TIDAK aman untuk multi-lab, tolong set lewat dashboard."
        )
        return DOOR_SERVICE_URL_FALLBACK.rstrip("/"), DOOR_SERVICE_API_KEY_DEFAULT

    raise HTTPException(
        status_code=400,
        detail=(
            f"Ruangan {ruangan_id} belum dikonfigurasi door_service_url-nya. "
            f"Set lewat PATCH /ruangan/{ruangan_id}/door-service, atau env "
            f"DOOR_SERVICE_URL_L{ruangan_id}."
        ),
    )

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


def _jam_ke_menit(jam_str: str) -> Optional[int]:
    """Konversi 'HH:MM' -> total menit sejak 00:00. None kalau formatnya rusak."""
    try:
        jam, menit = jam_str.split(":")
        return int(jam) * 60 + int(menit)
    except (ValueError, AttributeError):
        return None


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
    now_menit = _jam_ke_menit(now_time)

    # Toleransi masuk lebih awal (menit) — jadwal jam 15:00 dengan
    # toleransi 15 menit berarti user sudah boleh masuk sejak 14:45.
    # Dihitung di Python (bukan filter SQL) karena jam_mulai/jam_selesai
    # disimpan sebagai string "HH:MM", bukan tipe waktu asli.
    toleransi_awal = pengaturan.toleransi_masuk_awal_menit or 0

    jadwals_hari_ini = db.query(JadwalRuangan).options(
        joinedload(JadwalRuangan.mahasiswa_diizinkan)
    ).filter(
        JadwalRuangan.ruangan_id == ruangan_id,
        JadwalRuangan.tanggal    == today,
    ).order_by(JadwalRuangan.jam_mulai).all()

    jadwal = None
    for j in jadwals_hari_ini:
        mulai_menit   = _jam_ke_menit(j.jam_mulai)
        selesai_menit = _jam_ke_menit(j.jam_selesai)
        if mulai_menit is None or selesai_menit is None or now_menit is None:
            continue
        if (mulai_menit - toleransi_awal) <= now_menit < selesai_menit:
            jadwal = j
            break

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
        "server": "SmartDoorLock Server Rack",
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
    Sekaligus mendeteksi user yang PIN-nya sudah cocok tapi BELUM punya
    template biometrik tersimpan di server — supaya bridge tahu perlu
    ekstrak & upload template untuk PIN-PIN itu (lihat /upload-templates).
    """
    updated = 0
    need_download = []

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

        if user:
            punya_template = db.query(BiometricTemplate).filter(
                BiometricTemplate.user_id == user.id
            ).first()
            if not punya_template:
                need_download.append(perangkat_id)

    return {
        "status":        "ok",
        "updated":       updated,
        "total":         len(payload.device_users),
        "need_download": need_download,
    }


@router.post("/upload-templates")
def upload_templates(
    payload: dict,
    key=Depends(verify_key),
    db: Session = Depends(get_db),
):
    """
    Bridge mengirim template biometrik hasil ekstraksi SOAP
    (GetUserTemplate) dari device-nya, untuk PIN-PIN yang server
    tandai butuh download lewat /sync-enrollment. Body:
        {"pin": "4", "templates": [{"finger_id":0,"size":"512","valid":"1","template":"..."}]}
    """
    pin = payload.get("pin")
    templates = payload.get("templates", [])
    if not pin or not templates:
        raise HTTPException(status_code=400, detail="pin dan templates wajib diisi")

    try:
        perangkat_id = int(pin)
    except ValueError:
        raise HTTPException(status_code=400, detail="pin harus angka")

    user = db.query(User).filter(User.id_perangkat == perangkat_id, User.aktif == True).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User dengan id_perangkat {pin} tidak ditemukan")

    tersimpan = 0
    for t in templates:
        existing = db.query(BiometricTemplate).filter(
            BiometricTemplate.user_id == user.id,
            BiometricTemplate.finger_id == int(t["finger_id"]),
        ).first()
        if existing:
            existing.size = t.get("size")
            existing.template = t.get("template")
            existing.valid = t.get("valid", "1")
        else:
            db.add(BiometricTemplate(
                user_id=user.id,
                finger_id=int(t["finger_id"]),
                size=t.get("size"),
                template=t.get("template"),
                valid=t.get("valid", "1"),
            ))
        tersimpan += 1
    db.commit()

    log.info(f"Template biometrik tersimpan untuk {user.nama} (PIN {pin}): {tersimpan} jari")
    return {"status": "ok", "user": user.nama, "tersimpan": tersimpan}


@router.get("/roster-ruangan")
def get_roster_ruangan(
    ruangan_id: int,
    hari_kedepan: int = 3,
    key=Depends(verify_key),
    db: Session = Depends(get_db),
):
    """
    Daftar mahasiswa yang SEHARUSNYA ada di device ruangan ini — dari
    jadwal hari ini sampai N hari ke depan (default 3, supaya bisa
    di-provision SEBELUM kelasnya mulai). Dipakai Process 2 (di STB)
    untuk tahu siapa yang perlu di-push/provision/hapus dari device.

    Admin/teknisi/dosen TIDAK lewat endpoint ini — mereka akses bebas
    (ROLE_BEBAS), diprovision terpisah/manual, tidak terikat jadwal.
    """
    today = datetime.now(WIB).date()
    tanggal_list = [(today + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(hari_kedepan + 1)]

    jadwals = db.query(JadwalRuangan).options(
        joinedload(JadwalRuangan.mahasiswa_diizinkan)
    ).filter(
        JadwalRuangan.ruangan_id == ruangan_id,
        JadwalRuangan.tanggal.in_(tanggal_list),
        JadwalRuangan.is_active == True,
    ).all()

    user_ids = set()
    for j in jadwals:
        for m in j.mahasiswa_diizinkan:
            user_ids.add(m.id)

    if not user_ids:
        return []

    users = db.query(User).filter(
        User.id.in_(user_ids), User.id_perangkat.isnot(None), User.aktif == True
    ).all()

    hasil = []
    for u in users:
        punya_template = db.query(BiometricTemplate).filter(BiometricTemplate.user_id == u.id).first() is not None
        hasil.append({
            "user_id": u.id,
            "pin": u.id_perangkat,
            "nama": u.nama,
            "punya_template": punya_template,
        })
    return hasil


@router.get("/to-remove")
def get_to_remove_ruangan(
    ruangan_id: int,
    hari_kedepan: int = 3,
    key=Depends(verify_key),
    db: Session = Depends(get_db),
):
    """
    Kebalikan dari /roster-ruangan — user yang statusnya SUDAH
    provisioned/synced di ruangan ini di UserDeviceSync, TAPI sekarang
    TIDAK LAGI ada di roster (jadwalnya sudah habis/berubah). Dipakai
    Process 2 (STB) untuk tahu siapa yang perlu dihapus dari device.
    """
    today = datetime.now(WIB).date()
    tanggal_list = [(today + timedelta(days=i)).strftime("%Y-%m-%d") for i in range(hari_kedepan + 1)]

    jadwals = db.query(JadwalRuangan).options(
        joinedload(JadwalRuangan.mahasiswa_diizinkan)
    ).filter(
        JadwalRuangan.ruangan_id == ruangan_id,
        JadwalRuangan.tanggal.in_(tanggal_list),
        JadwalRuangan.is_active == True,
    ).all()

    roster_ids = set()
    for j in jadwals:
        for m in j.mahasiswa_diizinkan:
            roster_ids.add(m.id)

    aktif_sync = db.query(UserDeviceSync).filter(
        UserDeviceSync.ruangan_id == ruangan_id,
        UserDeviceSync.status.in_(["synced", "provisioned"]),
    ).all()

    hasil = []
    for s in aktif_sync:
        if s.user_id not in roster_ids:
            u = db.query(User).filter(User.id == s.user_id).first()
            if u and u.id_perangkat:
                hasil.append({"user_id": u.id, "pin": u.id_perangkat, "nama": u.nama})
    return hasil


@router.get("/user-templates")
def get_user_templates(pin: int, key=Depends(verify_key), db: Session = Depends(get_db)):
    """Ambil semua template fingerprint 1 user (buat STB push ke device lokalnya)."""
    user = db.query(User).filter(User.id_perangkat == pin).first()
    if not user:
        raise HTTPException(status_code=404, detail=f"User dengan PIN {pin} tidak ditemukan")
    templates = db.query(BiometricTemplate).filter(BiometricTemplate.user_id == user.id).all()
    return {
        "user_id": user.id,
        "nama": user.nama,
        "pin": pin,
        "templates": [
            {"finger_id": t.finger_id, "size": t.size, "valid": t.valid, "template": t.template}
            for t in templates
        ],
    }


class ReportSyncStatusPayload(BaseModel):
    ruangan_id: int
    user_id: int
    status: str  # provisioned / synced / removed / gagal


@router.post("/report-sync-status")
def report_sync_status(
    payload: ReportSyncStatusPayload,
    key=Depends(verify_key),
    db: Session = Depends(get_db),
):
    """STB melaporkan hasil push/provision/hapus — server catat di UserDeviceSync."""
    row = db.query(UserDeviceSync).filter(
        UserDeviceSync.user_id == payload.user_id,
        UserDeviceSync.ruangan_id == payload.ruangan_id,
    ).first()
    if row:
        row.status = payload.status
    else:
        db.add(UserDeviceSync(user_id=payload.user_id, ruangan_id=payload.ruangan_id, status=payload.status))
    db.commit()
    return {"status": "ok"}


@router.get("/sync-status")
def get_sync_status(
    ruangan_id: Optional[int] = None,
    status: Optional[str] = None,
    user=Depends(get_current_user_session),
    db: Session = Depends(get_db),
):
    """
    Dashboard monitoring: status sync biometrik semua user x ruangan.
    Dipanggil dari browser (session login), BUKAN dari STB.
    """
    q = db.query(UserDeviceSync).options(
        joinedload(UserDeviceSync.user), joinedload(UserDeviceSync.ruangan)
    )
    if ruangan_id:
        q = q.filter(UserDeviceSync.ruangan_id == ruangan_id)
    if status:
        q = q.filter(UserDeviceSync.status == status)

    rows = q.order_by(UserDeviceSync.updated_at.desc()).all()
    return [
        {
            "id": r.id,
            "user_id": r.user_id,
            "nama": r.user.nama if r.user else "—",
            "pin": r.user.id_perangkat if r.user else None,
            "ruangan_id": r.ruangan_id,
            "nama_ruangan": r.ruangan.nama if r.ruangan else "—",
            "status": r.status,
            "updated_at": r.updated_at.isoformat() if r.updated_at else None,
        }
        for r in rows
    ]


@router.get("/sync-status/ringkasan")
def get_sync_status_ringkasan(user=Depends(get_current_user_session), db: Session = Depends(get_db)):
    """Hitung jumlah per status, per ruangan — buat kartu ringkasan di dashboard."""
    rows = db.query(
        UserDeviceSync.ruangan_id, Ruangan.nama, UserDeviceSync.status, func.count(UserDeviceSync.id)
    ).join(Ruangan, Ruangan.id == UserDeviceSync.ruangan_id).group_by(
        UserDeviceSync.ruangan_id, Ruangan.nama, UserDeviceSync.status
    ).all()

    ringkasan = {}
    for ruangan_id, nama_ruangan, status, jumlah in rows:
        if ruangan_id not in ringkasan:
            ringkasan[ruangan_id] = {"ruangan_id": ruangan_id, "nama_ruangan": nama_ruangan,
                                       "synced": 0, "provisioned": 0, "removed": 0, "gagal": 0}
        ringkasan[ruangan_id][status] = jumlah

    return list(ringkasan.values())


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


@router.post("/open-door")
def open_door_manual(
    ruangan_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_session),
):
    """
    Buka pintu secara manual lewat dashboard. Hanya admin/teknisi — ini
    aksi fisik yang sensitif.

    Server ini TIDAK menghubungi device secara langsung — request
    diteruskan ke door_service.py yang berjalan di STB (satu jaringan
    dengan device), karena server utama mungkin tidak satu jaringan
    langsung dengan X606-S.

    Setiap ruangan bisa punya door_service_url/port berbeda (multi-STB
    atau 1 STB dengan banyak port) — lihat resolve_door_service().
    """
    if user["role"] not in ROLE_BEBAS:
        raise HTTPException(status_code=403, detail="Hanya admin/teknisi yang boleh membuka pintu manual")

    door_service_url, door_service_api_key = resolve_door_service(ruangan_id, db)

    try:
        r = requests.post(
            f"{door_service_url}/open-door",
            headers={"X-API-Key": door_service_api_key},
            timeout=15,
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gagal menghubungi door_service di STB ({door_service_url}): {e}")

    if not r.ok:
        try:
            detail = r.json().get("detail", r.text)
        except Exception:
            detail = r.text
        raise HTTPException(status_code=502, detail=f"door_service melaporkan gagal: {detail}")

    # Catat sebagai access_log untuk jejak audit
    log = AccessLog(
        ruangan_id=ruangan_id,
        user_id=user["user_id"],
        status="berhasil",
        metode="manual",
        keterangan=f"Pintu dibuka manual dari dashboard oleh {user['nama']}",
        waktu_akses=datetime.now(WIB),
    )
    db.add(log)
    db.commit()

    return {"pesan": "Pintu berhasil dibuka", "ruangan_id": ruangan_id}


@router.get("/sesi-finger-aktif")
def cek_sesi_finger_aktif_bridge(ruangan_id: int, key=Depends(verify_key), db: Session = Depends(get_db)):
    """
    Versi khusus STB (auth API key, bukan session) dari cek sesi input
    finger aktif — dipakai door_service.py buat skip sync biometrik
    kalau lagi ada sesi manual berjalan di ruangannya.
    """
    from app.models.models import SesiInputFinger
    sesi = db.query(SesiInputFinger).filter(
        SesiInputFinger.ruangan_id == ruangan_id, SesiInputFinger.status == "aktif"
    ).first()
    return {"aktif": sesi is not None}