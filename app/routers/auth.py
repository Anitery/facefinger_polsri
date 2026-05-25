from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session, joinedload
from datetime import datetime
import json
import numpy as np
from app.database import get_db
from app.models.models import User, AccessLog, JadwalRuangan

router = APIRouter(prefix="/auth", tags=["Autentikasi"])

FACE_THRESHOLD = 0.5

# Role yang BEBAS akses kapan saja (tidak dibatasi jadwal)
ROLE_BEBAS = {"admin", "teknisi", "dosen"}


def euclidean_distance(enc1, enc2):
    return float(np.linalg.norm(np.array(enc1) - np.array(enc2)))


def cek_jadwal_aktif(ruangan_id: int, user_id: int, db: Session):
    """
    Cek apakah user boleh akses ruangan sekarang berdasarkan jadwal.
    Return: (boleh: bool, alasan: str)
    """
    now      = datetime.now()
    today    = now.strftime("%Y-%m-%d")
    now_time = now.strftime("%H:%M")

    # Cari jadwal yang aktif sekarang di ruangan ini
    jadwal = db.query(JadwalRuangan).options(
        joinedload(JadwalRuangan.mahasiswa_diizinkan)
    ).filter(
        JadwalRuangan.ruangan_id  == ruangan_id,
        JadwalRuangan.tanggal     == today,
        JadwalRuangan.jam_mulai   <= now_time,
        JadwalRuangan.jam_selesai >  now_time,
    ).first()

    if not jadwal:
        # Tidak ada jadwal aktif — hanya admin/teknisi/dosen boleh masuk
        return False, "Tidak ada jadwal aktif saat ini"

    # Ada jadwal — cek apakah user terdaftar di jadwal ini
    mahasiswa_ids = [m.id for m in jadwal.mahasiswa_diizinkan]

    if not mahasiswa_ids:
        # Jadwal ada tapi belum ada mahasiswa didaftarkan → izinkan semua
        return True, f"Jadwal: {jadwal.nama_kegiatan} (semua diizinkan)"

    if user_id in mahasiswa_ids:
        return True, f"Jadwal: {jadwal.nama_kegiatan} ({jadwal.kelas or ''})"

    return False, f"Tidak terdaftar di jadwal {jadwal.nama_kegiatan} ({jadwal.kelas or ''})"


@router.post("/face")
def auth_face(payload, db: Session = Depends(get_db)):
    from app.schemas import AuthFaceRequest, AuthResponse

    users = db.query(User).filter(
        User.aktif        == True,
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
        # Wajah tidak dikenal
        db.add(AccessLog(
            user_id=None, ruangan_id=payload.ruangan_id,
            metode="face", status="ditolak",
            keterangan="Wajah tidak dikenal"
        ))
        db.commit()
        raise HTTPException(status_code=401, detail="Wajah tidak dikenal")

    # Wajah dikenal — cek hak akses berdasarkan jadwal
    if best_match.role in ROLE_BEBAS:
        # Admin/teknisi/dosen bebas akses kapan saja
        alasan = f"Akses bebas ({best_match.role})"
        boleh  = True
    else:
        # Mahasiswa — cek jadwal
        boleh, alasan = cek_jadwal_aktif(
            payload.ruangan_id, best_match.id, db
        )

    if boleh:
        db.add(AccessLog(
            user_id=best_match.id, ruangan_id=payload.ruangan_id,
            metode="face", status="berhasil",
            keterangan=f"{alasan} | jarak: {best_dist:.4f}"
        ))
        db.commit()
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
        raise HTTPException(
            status_code=403,
            detail=f"Akses ditolak — {alasan}"
        )