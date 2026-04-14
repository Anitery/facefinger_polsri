from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
import json
from app.database import get_db
from app.models.models import User
from app.schemas import UserCreate, UserOut

router = APIRouter(prefix="/users", tags=["Pengguna"])


@router.get("/", response_model=list[UserOut])
def get_all_users(db: Session = Depends(get_db)):
    return db.query(User).filter(User.aktif == True).all()


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