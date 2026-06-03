from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from datetime import datetime
import json
import numpy as np
from app.database import get_db
from app.models.models import User, AccessLog, JadwalRuangan
from app.services.absensi_service import catat_absensi_masuk

router = APIRouter(prefix="/auth", tags=["Autentikasi"])

FACE_THRESHOLD = 0.5
ROLE_BEBAS     = {"admin", "teknisi"}  # dosen dicatat absensi juga


def euclidean_distance(enc1, enc2):
    return float(np.linalg.norm(np.array(enc1) - np.array(enc2)))


def cek_jadwal_aktif(ruangan_id: int, user_id: int, role: str, db: Session):
    """
    Cek jadwal aktif dan hak akses.
    Returns: (boleh, alasan, jadwal_aktif)
    """
    now      = datetime.now()
    today    = now.strftime("%Y-%m-%d")
    now_time = now.strftime("%H:%M")

    # Admin & teknisi bebas kapan saja
    if role in ROLE_BEBAS:
        return True, f"Akses bebas ({role})", None

    # Cari jadwal aktif sekarang
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

    # Dosen — cek apakah dosen pengampu jadwal ini
    if role == "dosen":
        return True, f"Dosen — {jadwal.nama_kegiatan}", jadwal

    # Mahasiswa — cek terdaftar di jadwal
    if not mahasiswa_ids:
        # Jadwal belum assign mahasiswa → semua boleh
        return True, f"Jadwal: {jadwal.nama_kegiatan} (terbuka)", jadwal

    if user_id in mahasiswa_ids:
        return True, f"Jadwal: {jadwal.nama_kegiatan} ({jadwal.kelas or ''})", jadwal

    return False, \
        f"Tidak terdaftar di jadwal {jadwal.nama_kegiatan} ({jadwal.kelas or ''})", \
        None


@router.post("/face")
def auth_face(payload, db: Session = Depends(get_db)):
    from app.schemas import AuthFaceRequest, AuthResponse

    users = db.query(User).filter(
        User.aktif         == True,
        User.face_encoding != None,
    ).all()

    best_match = None
    best_dist  = float("inf")

    for user in users:
        try:
            stored = json.loads(user.face_encoding)
            dist   = euclidean_distance(payload.face_encoding, stored)
            if dist < best_dist:
                best_dist  = dist
                best_match = user
        except Exception:
            continue

    if not (best_match and best_dist <= FACE_THRESHOLD):
        db.add(AccessLog(
            user_id=None, ruangan_id=payload.ruangan_id,
            metode="face", status="ditolak",
            keterangan="Wajah tidak dikenal"
        ))
        db.commit()
        raise HTTPException(status_code=401, detail="Wajah tidak dikenal")

    # Cek hak akses berdasarkan jadwal
    boleh, alasan, jadwal_aktif = cek_jadwal_aktif(
        payload.ruangan_id, best_match.id, best_match.role, db
    )

    if boleh:
        # Catat log akses
        db.add(AccessLog(
            user_id=best_match.id, ruangan_id=payload.ruangan_id,
            metode="face", status="berhasil",
            keterangan=f"{alasan} | jarak: {best_dist:.4f}"
        ))
        db.commit()

        # Catat absensi jika ada jadwal aktif
        if jadwal_aktif:
            catat_absensi_masuk(
                db        = db,
                jadwal_id = jadwal_aktif.id,
                user_id   = best_match.id,
                jam_mulai = jadwal_aktif.jam_mulai
            )

        return {
            "status":  "berhasil",
            "user_id": best_match.id,
            "nama":    best_match.nama,
            "pesan":   f"Akses diberikan — {alasan}"
        }
    else:
        db.add(AccessLog(
            user_id=best_match.id, ruangan_id=payload.ruangan_id,
            metode="face", status="ditolak",
            keterangan=f"Ditolak: {alasan}"
        ))
        db.commit()
        raise HTTPException(status_code=403, detail=f"Akses ditolak — {alasan}")


@router.post("/fingerprint")
def auth_fingerprint(payload, db: Session = Depends(get_db)):
    from app.schemas import AuthFingerprintRequest, AuthResponse

    user = db.query(User).filter(
        User.fingerprint_id == payload.fingerprint_id,
        User.aktif          == True,
    ).first()

    if not user:
        db.add(AccessLog(
            user_id=None, ruangan_id=payload.ruangan_id,
            metode="fingerprint", status="ditolak",
            keterangan=f"FP ID {payload.fingerprint_id} tidak terdaftar"
        ))
        db.commit()
        raise HTTPException(status_code=401, detail="Fingerprint tidak terdaftar")

    boleh, alasan, jadwal_aktif = cek_jadwal_aktif(
        payload.ruangan_id, user.id, user.role, db
    )

    if boleh:
        db.add(AccessLog(
            user_id=user.id, ruangan_id=payload.ruangan_id,
            metode="fingerprint", status="berhasil",
            keterangan=alasan
        ))
        db.commit()

        if jadwal_aktif:
            catat_absensi_masuk(
                db        = db,
                jadwal_id = jadwal_aktif.id,
                user_id   = user.id,
                jam_mulai = jadwal_aktif.jam_mulai
            )

        return {
            "status":  "berhasil",
            "user_id": user.id,
            "nama":    user.nama,
            "pesan":   f"Akses diberikan via fingerprint — {alasan}"
        }
    else:
        db.add(AccessLog(
            user_id=user.id, ruangan_id=payload.ruangan_id,
            metode="fingerprint", status="ditolak",
            keterangan=f"Ditolak: {alasan}"
        ))
        db.commit()
        raise HTTPException(
            status_code=403,
            detail=f"Akses ditolak — {alasan}"
        )