"""
app/routers/transfer.py
=========================================================
Halaman "Transfer Data Alat" — pindahkan user (yang sudah punya
fingerprint MAUPUN yang belum) dari 1 device X606-S (ruangan asal) ke
device X606-S lain (ruangan tujuan), tanpa perlu daftar ulang fisik
kalau user itu sudah punya template di device asal.

Alur teknis (semua lewat door_service.py masing-masing STB, server ini
TIDAK pernah bicara SOAP langsung ke device):

    1. GET  {door_service_asal}/device-users
       -> daftar user yang ADA SEKARANG di device asal + status
          fingerprint (sudah/belum) — buat ditampilkan di halaman
          supaya admin bisa pilih siapa yang mau dipindah.

    2. POST {door_service_asal}/export-users {"pins": [...]}
       -> ambil nama + seluruh template fingerprint (kalau ada) untuk
          PIN-PIN yang dipilih admin.

    3. POST {door_service_tujuan}/import-users {"users": [...]}
       -> push data itu (nama, dan template kalau ada) ke device
          tujuan. User yang belum punya fingerprint tetap
          dipindah/dibuatkan (nama+PIN saja) supaya tinggal daftar
          jari fisik di device tujuan.

    4. Simpan salinan template ke DB server (biometric_template) untuk
       user yang PIN-nya cocok dengan user terdaftar (id_perangkat) —
       supaya sekali dipindah, template ini juga ikut jadi "master
       copy" di server dan bisa dipakai roster sync biasa ke ruangan
       lain di masa depan (bukan cuma tersimpan di device tujuan).
"""
import logging
from typing import List, Optional
import requests
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import Ruangan, User, BiometricTemplate, UserDeviceSync
from app.services.auth_service import get_current_user_session
from app.routers.device_bridge import resolve_door_service

log = logging.getLogger(__name__)

router = APIRouter(prefix="/transfer", tags=["Transfer Data Alat"])

ROLE_DIIZINKAN = ("admin", "teknisi")


def _wajib_teknisi(user: dict):
    if user["role"] not in ROLE_DIIZINKAN:
        raise HTTPException(status_code=403, detail="Hanya admin/teknisi yang boleh mengakses transfer data alat")


def _push_dan_catat_sync(ruangan_tujuan_id: int, data_users: list, db: Session) -> dict:
    """
    Kirim `data_users` (bentuk: [{"pin","nama","templates":[...]}, ...]) ke
    door_service ruangan tujuan lewat /import-users, lalu catat hasilnya ke
    biometric_template (master copy di server) + user_device_sync.
    Dipakai bersama oleh transfer antar-alat (/push) maupun transfer
    dari database server ke alat (/push-dari-database).
    """
    url_tujuan, key_tujuan = resolve_door_service(ruangan_tujuan_id, db)
    try:
        r = requests.post(
            f"{url_tujuan}/import-users",
            headers={"X-API-Key": key_tujuan},
            json={"users": data_users},
            timeout=120,
        )
        r.raise_for_status()
        hasil_push = r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gagal push data ke device tujuan ({url_tujuan}): {e}")

    berhasil_pins = set(hasil_push.get("berhasil", []))
    tersimpan_db = 0

    for u in data_users:
        pin = str(u.get("pin", ""))
        if pin not in berhasil_pins:
            continue
        try:
            db_user = db.query(User).filter(User.id_perangkat == int(pin)).first()
        except (TypeError, ValueError):
            db_user = None
        if not db_user:
            continue

        for t in u.get("templates", []):
            existing = db.query(BiometricTemplate).filter(
                BiometricTemplate.user_id == db_user.id,
                BiometricTemplate.finger_id == int(t["finger_id"]),
            ).first()
            if existing:
                existing.size = t.get("size")
                existing.template = t.get("template")
                existing.valid = t.get("valid", "1")
            else:
                db.add(BiometricTemplate(
                    user_id=db_user.id, finger_id=int(t["finger_id"]),
                    size=t.get("size"), template=t.get("template"), valid=t.get("valid", "1"),
                ))
        if u.get("templates"):
            tersimpan_db += 1

        sync_row = db.query(UserDeviceSync).filter(
            UserDeviceSync.user_id == db_user.id,
            UserDeviceSync.ruangan_id == ruangan_tujuan_id,
        ).first()
        status_sync = "synced" if u.get("templates") else "provisioned"
        if sync_row:
            sync_row.status = status_sync
        else:
            db.add(UserDeviceSync(user_id=db_user.id, ruangan_id=ruangan_tujuan_id, status=status_sync))

    db.commit()
    return {
        "berhasil": hasil_push.get("berhasil", []),
        "gagal": hasil_push.get("gagal", []),
        "template_disalin_ke_server": tersimpan_db,
    }


@router.get("/device-users")
def get_device_users(
    ruangan_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_session),
):
    """Daftar user yang ada di device milik satu ruangan, + status fingerprint."""
    _wajib_teknisi(user)
    door_service_url, api_key = resolve_door_service(ruangan_id, db)

    try:
        r = requests.get(
            f"{door_service_url}/device-users",
            headers={"X-API-Key": api_key},
            timeout=30,
        )
        r.raise_for_status()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gagal membaca user dari device ({door_service_url}): {e}")

    return r.json()


class TransferPayload(BaseModel):
    ruangan_asal_id: int
    ruangan_tujuan_id: int
    pins: List[str]


@router.post("/push")
def push_transfer(
    payload: TransferPayload,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_session),
):
    """Eksekusi transfer: ambil data dari device asal, push ke device tujuan."""
    _wajib_teknisi(user)

    if payload.ruangan_asal_id == payload.ruangan_tujuan_id:
        raise HTTPException(status_code=400, detail="Ruangan asal dan tujuan tidak boleh sama")
    if not payload.pins:
        raise HTTPException(status_code=400, detail="Pilih minimal 1 user untuk dipindah")

    url_asal, key_asal = resolve_door_service(payload.ruangan_asal_id, db)

    # ── 1. Ambil data lengkap dari device asal ──────────────────────
    try:
        r = requests.post(
            f"{url_asal}/export-users",
            headers={"X-API-Key": key_asal},
            json={"pins": payload.pins},
            timeout=60,
        )
        r.raise_for_status()
        data_users = r.json()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gagal mengambil data dari device asal ({url_asal}): {e}")

    if not data_users:
        raise HTTPException(status_code=404, detail="Tidak ada data yang bisa diambil dari device asal")

    # ── 2. Push ke device tujuan + catat DB (dipakai bareng dengan
    #      /push-dari-database, lihat _push_dan_catat_sync) ──────────
    hasil = _push_dan_catat_sync(payload.ruangan_tujuan_id, data_users, db)

    return {
        "pesan": f"Transfer selesai: {len(hasil['berhasil'])}/{len(payload.pins)} user berhasil dipindah",
        **hasil,
    }


@router.get("/database-users")
def get_database_users(
    role: Optional[str] = None,
    kelas: Optional[str] = None,
    search: Optional[str] = None,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_session),
):
    """
    Daftar user dari DATABASE SERVER (bukan dari alat) + status fingerprint
    (BiometricTemplate) — dipakai untuk mode "Kirim dari Database Server
    ke Alat": misal alat/lab baru butuh diisi data user tanpa perlu
    ambil dari device lain, langsung dari master data server.
    Default hanya user aktif dengan id_perangkat terisi (PIN) — user
    tanpa PIN tidak bisa di-provision ke device manapun.
    """
    _wajib_teknisi(user)

    q = db.query(User).filter(User.aktif == True, User.id_perangkat.isnot(None))
    if role:
        q = q.filter(User.role == role)
    if kelas:
        q = q.filter(User.kelas == kelas)
    if search:
        q = q.filter(User.nama.ilike(f"%{search}%") | User.nim_nip.ilike(f"%{search}%"))

    users = q.order_by(User.role, User.nama).all()
    user_ids = [u.id for u in users]
    ids_dgn_template = set()
    if user_ids:
        rows = db.query(BiometricTemplate.user_id).filter(
            BiometricTemplate.user_id.in_(user_ids)
        ).distinct().all()
        ids_dgn_template = {r[0] for r in rows}

    return [
        {
            "id": u.id,
            "pin": u.id_perangkat,
            "nama": u.nama,
            "nim_nip": u.nim_nip,
            "role": u.role,
            "kelas": u.kelas,
            "punya_fingerprint": u.id in ids_dgn_template,
        }
        for u in users
    ]


class PushDariDatabasePayload(BaseModel):
    ruangan_tujuan_id: int
    user_ids: List[int]


@router.post("/push-dari-database")
def push_dari_database(
    payload: PushDariDatabasePayload,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_session),
):
    """
    Kirim user LANGSUNG DARI DATABASE SERVER (bukan dari alat lain) ke
    1 device tujuan — dipakai misalnya alat/lab baru mau diisi data user
    tanpa harus ambil dari device manapun, cukup dari master data yang
    sudah ada di server (nama, PIN, dan template kalau sudah pernah
    di-enroll sebelumnya).
    """
    _wajib_teknisi(user)

    if not payload.user_ids:
        raise HTTPException(status_code=400, detail="Pilih minimal 1 user untuk dikirim")

    users_db = db.query(User).filter(User.id.in_(payload.user_ids), User.id_perangkat.isnot(None)).all()
    if not users_db:
        raise HTTPException(status_code=404, detail="Tidak ada user valid (dengan PIN) dari pilihan tersebut")

    data_users = []
    for u in users_db:
        templates = db.query(BiometricTemplate).filter(BiometricTemplate.user_id == u.id).all()
        data_users.append({
            "pin": str(u.id_perangkat),
            "nama": u.nama,
            "templates": [
                {"finger_id": t.finger_id, "size": t.size, "valid": t.valid, "template": t.template}
                for t in templates
            ],
        })

    hasil = _push_dan_catat_sync(payload.ruangan_tujuan_id, data_users, db)

    return {
        "pesan": f"Kirim dari database selesai: {len(hasil['berhasil'])}/{len(payload.user_ids)} user berhasil dikirim ke alat",
        **hasil,
    }
