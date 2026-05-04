from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List
import json
from app.database import get_db
from app.models.models import User
from app.schemas import UserCreate, UserOut
import bcrypt

def _hash_pw(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def _verify_pw(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False

router = APIRouter(prefix="/users", tags=["Pengguna"])

class FaceEncodingPayload(BaseModel):
    encoding: List[float]

@router.post("/{user_id}/enroll-face")
def enroll_face(
    user_id: int,
    payload: FaceEncodingPayload,
    db: Session = Depends(get_db)
):
    """Simpan face encoding hasil proses face-api.js dari browser."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    if len(payload.encoding) != 128:
        raise HTTPException(
            status_code=400,
            detail=f"Encoding harus 128 dimensi, diterima {len(payload.encoding)}"
        )
    user.face_encoding = json.dumps(payload.encoding)
    db.commit()
    return {
        "pesan":   f"Face encoding {user.nama} berhasil disimpan",
        "user_id": user.id,
        "nama":    user.nama
    }

@router.delete("/{user_id}/enroll-face")
def hapus_face(user_id: int, db: Session = Depends(get_db)):
    """Hapus face encoding user."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    user.face_encoding = None
    db.commit()
    return {"pesan": f"Face encoding {user.nama} dihapus"}

@router.get("/", response_model=list[UserOut])
def get_all_users(aktif_only: bool = True, db: Session = Depends(get_db)):
    query = db.query(User)
    if aktif_only:
        query = query.filter(User.aktif == True)
    return query.all()


@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    return user


@router.post("/", response_model=UserOut)
def create_user(payload: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.nim_nip == payload.nim_nip).first()
    if existing:
        raise HTTPException(status_code=400, detail="NIM/NIP sudah terdaftar")
    user = User(**payload.model_dump())
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

@router.put("/{user_id}")
def update_user(user_id: int, payload: UserCreate, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    user.nama      = payload.nama
    user.nim_nip   = payload.nim_nip
    user.role      = payload.role
    user.ruangan_id = payload.ruangan_id
    db.commit()
    db.refresh(user)
    return user

@router.put("/{user_id}/face-encoding")
def update_face_encoding(user_id: int, encoding: list[float], db: Session = Depends(get_db)):
    """Simpan/update encoding wajah pengguna (128 dimensi)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    if len(encoding) != 128:
        raise HTTPException(status_code=400, detail="Encoding harus 128 dimensi")
    user.face_encoding = json.dumps(encoding)
    db.commit()
    return {"pesan": f"Face encoding user {user.nama} berhasil disimpan"}


@router.patch("/{user_id}/fingerprint")
def update_fingerprint(user_id: int, fingerprint_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    user.fingerprint_id = fingerprint_id
    db.commit()
    return {"pesan": f"Fingerprint ID {fingerprint_id} disimpan untuk {user.nama}"}

@router.delete("/{user_id}")
def deactivate_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    user.aktif = False
    db.commit()
    return {"pesan": f"User {user.nama} dinonaktifkan"}

@router.patch("/{user_id}/password")
def update_password(
    user_id: int,
    password_lama: str,
    password_baru: str,
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    if user.password_hash and not _verify_pw(password_lama, user.password_hash):
        raise HTTPException(status_code=400, detail="Password lama salah")
    user.password_hash = _hash_pw(password_baru)
    db.commit()
    return {"pesan": "Password berhasil diperbarui"}


@router.post("/{user_id}/set-password")
def set_password_admin(
    user_id: int,
    password_baru: str,
    db: Session = Depends(get_db)
):
    """Khusus admin — set password tanpa perlu password lama."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    user.password_hash = _hash_pw(password_baru)
    db.commit()
    return {"pesan": f"Password {user.nama} berhasil di-set"}