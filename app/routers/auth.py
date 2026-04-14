from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import json
import numpy as np
from app.database import get_db
from app.models.models import User, AccessLog
from app.schemas import AuthFaceRequest, AuthFingerprintRequest, AuthResponse

router = APIRouter(prefix="/auth", tags=["Autentikasi"])

FACE_THRESHOLD = 0.5  # jarak Euclidean maksimum untuk dianggap cocok


def euclidean_distance(enc1: list, enc2: list) -> float:
    a = np.array(enc1)
    b = np.array(enc2)
    return float(np.linalg.norm(a - b))


@router.post("/face", response_model=AuthResponse)
def auth_face(payload: AuthFaceRequest, db: Session = Depends(get_db)):
    """
    Endpoint dipanggil oleh Raspberry Pi saat wajah terdeteksi.
    Mencocokkan encoding wajah dengan seluruh user terdaftar.
    """
    users = db.query(User).filter(
        User.aktif == True,
        User.face_encoding != None,
        User.ruangan_id == payload.ruangan_id
    ).all()

    best_match = None
    best_dist = float("inf")

    for user in users:
        try:
            stored_enc = json.loads(user.face_encoding)
            dist = euclidean_distance(payload.face_encoding, stored_enc)
            if dist < best_dist:
                best_dist = dist
                best_match = user
        except Exception:
            continue

    if best_match and best_dist <= FACE_THRESHOLD:
        # Simpan log berhasil
        log = AccessLog(
            user_id=best_match.id,
            ruangan_id=payload.ruangan_id,
            metode="face",
            foto_url=None,
            status="berhasil",
            keterangan=f"Jarak encoding: {best_dist:.4f}"
        )
        db.add(log)
        db.commit()
        return AuthResponse(
            status="berhasil",
            user_id=best_match.id,
            nama=best_match.nama,
            pesan="Akses diberikan"
        )
    else:
        # Simpan log ditolak
        log = AccessLog(
            user_id=None,
            ruangan_id=payload.ruangan_id,
            metode="face",
            foto_url=None,
            status="ditolak",
            keterangan="Wajah tidak dikenali"
        )
        db.add(log)
        db.commit()
        raise HTTPException(status_code=401, detail="Wajah tidak dikenali")


@router.post("/fingerprint", response_model=AuthResponse)
def auth_fingerprint(payload: AuthFingerprintRequest, db: Session = Depends(get_db)):
    """
    Endpoint dipanggil oleh Raspberry Pi saat fingerprint terbaca.
    """
    user = db.query(User).filter(
        User.fingerprint_id == payload.fingerprint_id,
        User.aktif == True,
        User.ruangan_id == payload.ruangan_id
    ).first()

    if user:
        log = AccessLog(
            user_id=user.id,
            ruangan_id=payload.ruangan_id,
            metode="fingerprint",
            status="berhasil",
            keterangan=f"Fingerprint ID: {payload.fingerprint_id}"
        )
        db.add(log)
        db.commit()
        return AuthResponse(
            status="berhasil",
            user_id=user.id,
            nama=user.nama,
            pesan="Akses diberikan via fingerprint"
        )
    else:
        log = AccessLog(
            user_id=None,
            ruangan_id=payload.ruangan_id,
            metode="fingerprint",
            status="ditolak",
            keterangan=f"Fingerprint ID {payload.fingerprint_id} tidak terdaftar"
        )
        db.add(log)
        db.commit()
        raise HTTPException(status_code=401, detail="Fingerprint tidak terdaftar")