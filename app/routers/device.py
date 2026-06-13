"""
Router ADMS — menerima data push dari Solution X606-S.

Endpoint yang dipanggil device:
  GET  /iclock/getrequest  → heartbeat device (polling perintah)
  POST /iclock/cdata       → push data transaksi absensi
"""
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import PlainTextResponse
from sqlalchemy.orm import Session, joinedload
from datetime import datetime
from typing import Optional
import os
import json

from app.database import get_db
from app.models.models import User, AccessLog, JadwalRuangan

router = APIRouter(prefix="/iclock", tags=["Device"])

# Ruangan ID default untuk device ini
DEVICE_RUANGAN_ID = int(os.getenv("DEVICE_RUANGAN_ID", "1"))

# Mapping kode verifikasi → metode
VERIFY_MAP = {
    "0":  "password",
    "1":  "fingerprint",
    "2":  "fingerprint",
    "3":  "fingerprint",
    "4":  "face",
    "5":  "face",
    "6":  "face",
    "15": "password",
}

# Role yang bebas akses tanpa cek jadwal
ROLE_BEBAS = {"admin", "teknisi"}


# ── Helper: cek jadwal aktif berdasarkan waktu tertentu ─────
def cek_jadwal_aktif_waktu(
    ruangan_id: int,
    user_id: int,
    role: str,
    waktu: datetime,
    db: Session
):
    """
    Validasi hak akses berdasarkan jadwal KBM.
    Menggunakan `waktu` dari device (bukan datetime.now()).
    Returns: (boleh: bool, alasan: str, jadwal: JadwalRuangan|None)
    """
    # Admin & teknisi bebas akses
    if role in ROLE_BEBAS:
        return True, f"Akses bebas ({role})", None

    today    = waktu.strftime("%Y-%m-%d")
    now_time = waktu.strftime("%H:%M")

    # Cari jadwal aktif saat waktu transaksi
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

    mahasiswa_ids = [m.id for m in jadwal.mahasiswa_diizinkan]

    # Dosen → otomatis diizinkan jika ada jadwal
    if role == "dosen":
        return True, f"Dosen — {jadwal.nama_kegiatan}", jadwal

    # Mahasiswa → cek terdaftar di jadwal
    if not mahasiswa_ids:
        return True, f"Jadwal terbuka — {jadwal.nama_kegiatan}", jadwal

    if user_id in mahasiswa_ids:
        return True, f"{jadwal.nama_kegiatan} ({jadwal.kelas or ''})", jadwal

    return False, \
        f"Tidak terdaftar di {jadwal.nama_kegiatan} ({jadwal.kelas or ''})", \
        None


# ── Helper: catat absensi dari device ───────────────────────
def catat_absensi_device(
    db: Session,
    jadwal_id: int,
    user_id: int,
    jam_mulai: str,
    waktu_scan: datetime
):
    """
    Catat absensi dengan waktu dari device (bukan datetime.now()).
    """
    from app.models.models import Absensi

    existing = db.query(Absensi).filter(
        Absensi.jadwal_id == jadwal_id,
        Absensi.user_id   == user_id,
    ).first()

    # Hitung selisih dengan jam mulai jadwal
    today    = waktu_scan.strftime("%Y-%m-%d")
    jam_dt   = datetime.strptime(f"{today} {jam_mulai}", "%Y-%m-%d %H:%M")
    selisih  = (waktu_scan - jam_dt).total_seconds() / 60
    status   = "hadir" if selisih <= 15 else "terlambat"

    if existing:
        if existing.status == "tidak_hadir":
            existing.waktu_masuk = waktu_scan
            existing.status      = status
            db.commit()
        return existing

    absensi = Absensi(
        jadwal_id   = jadwal_id,
        user_id     = user_id,
        waktu_masuk = waktu_scan,
        status      = status,
    )
    db.add(absensi)
    db.commit()
    db.refresh(absensi)
    return absensi


# ══════════════════════════════════════════════════════════
# ENDPOINT 1 — Heartbeat (device polling perintah dari server)
# ══════════════════════════════════════════════════════════

@router.api_route(
    "/{full_path:path}",
    methods=["GET", "POST", "PUT", "DELETE"],
    include_in_schema=False
)
async def capture_semua(full_path: str, request: Request):
    """
    Tangkap SEMUA request dari device — untuk analisis format ADMS.
    """
    body    = await request.body()
    headers = dict(request.headers)
    params  = dict(request.query_params)

    print("\n" + "█" * 60)
    print(f"[CAPTURE] Method  : {request.method}")
    print(f"[CAPTURE] Path    : /iclock/{full_path}")
    print(f"[CAPTURE] Params  : {json.dumps(params, indent=2)}")
    print(f"[CAPTURE] Headers :")
    for k, v in headers.items():
        print(f"           {k}: {v}")
    print(f"[CAPTURE] Body ({len(body)} bytes):")
    print(body.decode("utf-8", errors="replace"))
    print("█" * 60 + "\n")

    return PlainTextResponse("OK")

@router.get("/getrequest", response_class=PlainTextResponse)
async def device_heartbeat(
    SN:   str = Query(default=""),
    INFO: str = Query(default=""),
):
    """
    Device memanggil endpoint ini secara periodik (~30 detik sekali).
    Server membalas 'OK' jika tidak ada perintah,
    atau 'C:ID:CMD' jika ada perintah untuk device.
    """
    print(f"[DEVICE] ♥ Heartbeat — SN: {SN}")
    return "OK"


# ══════════════════════════════════════════════════════════
# ENDPOINT 2 — Terima data transaksi dari device
# ══════════════════════════════════════════════════════════
@router.post("/cdata", response_class=PlainTextResponse)
async def terima_data_device(
    request: Request,
    SN:    str = Query(default=""),
    table: str = Query(default=""),
    Stamp: str = Query(default=""),
    db: Session = Depends(get_db),
):
    """
    Device POST ke sini setiap ada transaksi (scan wajah/fingerprint).

    Format body (ATTLOG):
    PIN<TAB>DateTime<TAB>VerifyCode<TAB>InOutState
    Contoh:
    4\t2025-06-01 08:05:33\t4\t0
    """
    body     = await request.body()
    body_str = body.decode("utf-8", errors="ignore").strip()

    print(f"\n[DEVICE] ═══ Data masuk ═══")
    print(f"[DEVICE] SN    : {SN}")
    print(f"[DEVICE] Table : {table}")
    print(f"[DEVICE] Stamp : {Stamp}")
    print(f"[DEVICE] Body  : {repr(body_str)}")

    # Hanya proses tabel ATTLOG (data absensi/akses)
    if table.upper() != "ATTLOG" or not body_str:
        return "OK"

    lines     = body_str.split("\n")
    berhasil  = 0
    ditolak   = 0
    error     = 0

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Coba parse dengan tab, fallback spasi
        parts = line.split("\t")
        if len(parts) < 2:
            parts = line.split()
        if len(parts) < 2:
            print(f"[DEVICE] ✗ Format tidak dikenal: {line!r}")
            error += 1
            continue

        try:
            pin         = parts[0].strip()
            dt_str      = parts[1].strip()
            verify_code = parts[2].strip() if len(parts) > 2 else "1"

            # Parse waktu transaksi dari device
            waktu = None
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                        "%Y/%m/%d %H:%M:%S"):
                try:
                    waktu = datetime.strptime(dt_str, fmt)
                    break
                except ValueError:
                    continue

            if not waktu:
                print(f"[DEVICE] ✗ Format waktu tidak dikenal: {dt_str}")
                error += 1
                continue

            metode = VERIFY_MAP.get(verify_code, "fingerprint")

            # ── Cari user berdasarkan PIN ────────────────
            # PIN di device = fingerprint_id di database kita
            user = None
            try:
                fp_id = int(pin)
                user  = db.query(User).filter(
                    User.fingerprint_id == fp_id,
                    User.aktif          == True
                ).first()
            except ValueError:
                # PIN bukan angka → coba nim_nip
                user = db.query(User).filter(
                    User.nim_nip == pin,
                    User.aktif   == True
                ).first()

            if not user:
                print(f"[DEVICE] ✗ PIN {pin!r} tidak ditemukan di database")
                db.add(AccessLog(
                    user_id     = None,
                    ruangan_id  = DEVICE_RUANGAN_ID,
                    waktu_akses = waktu,
                    metode      = metode,
                    status      = "ditolak",
                    keterangan  = f"PIN '{pin}' tidak terdaftar"
                ))
                db.commit()
                ditolak += 1
                continue

            # ── Validasi jadwal KBM ──────────────────────
            boleh, alasan, jadwal_aktif = cek_jadwal_aktif_waktu(
                ruangan_id = DEVICE_RUANGAN_ID,
                user_id    = user.id,
                role       = user.role,
                waktu      = waktu,
                db         = db
            )

            status_akses = "berhasil" if boleh else "ditolak"

            # ── Catat log akses ──────────────────────────
            db.add(AccessLog(
                user_id     = user.id,
                ruangan_id  = DEVICE_RUANGAN_ID,
                waktu_akses = waktu,
                metode      = metode,
                status      = status_akses,
                keterangan  = f"SN:{SN} | {alasan}"
            ))
            db.commit()

            # ── Catat absensi jika berhasil ──────────────
            if boleh and jadwal_aktif:
                catat_absensi_device(
                    db         = db,
                    jadwal_id  = jadwal_aktif.id,
                    user_id    = user.id,
                    jam_mulai  = jadwal_aktif.jam_mulai,
                    waktu_scan = waktu
                )

            icon = "✓" if boleh else "✗"
            print(f"[DEVICE] {icon} {user.nama:20} | {metode:12} | "
                  f"{status_akses:8} | {alasan}")

            if boleh:
                berhasil += 1
            else:
                ditolak += 1

        except Exception as e:
            print(f"[DEVICE] ✗ Error: {e} — line: {line!r}")
            error += 1
            continue

    print(f"[DEVICE] Selesai: {berhasil} berhasil, "
          f"{ditolak} ditolak, {error} error\n")
    return "OK"


# ══════════════════════════════════════════════════════════
# ENDPOINT 3 — Info device (opsional, untuk diagnostik)
# ══════════════════════════════════════════════════════════
@router.get("/ping", response_class=PlainTextResponse)
async def ping_device():
    """Test apakah server bisa dijangkau oleh device."""
    return "PONG: SmartDoorLock Server OK"