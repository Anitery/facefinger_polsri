from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List
import json
from app.database import get_db
from app.models.models import User
from app.schemas import UserCreate, UserOut, UserUpdate
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

# --- Ranks & Permissions Constants ---
ROLE_ORDER = {"admin": 0, "teknisi": 1, "dosen": 2, "mahasiswa": 3}

ROLE_ALLOWED_TO_CREATE = {
    "admin":   {"admin", "teknisi", "dosen", "mahasiswa"},
    "dosen":   {"mahasiswa"},
    "teknisi": {"dosen"},
}

ROLE_ALLOWED_TO_MODIFY = {
    "admin":   {"admin", "teknisi", "dosen", "mahasiswa"},
    "dosen":   {"mahasiswa"},
    "teknisi": {"dosen"},
}

# --- Helper Functions ---
def get_current_role(request: Request) -> str:
    from app.services.auth_service import decode_session_token
    token = request.cookies.get("session_token")
    if not token:
        raise HTTPException(status_code=401, detail="Sesi tidak valid")
    return decode_session_token(token)["role"]

# --- Face & Fingerprint Endpoints ---
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

# --- Read Endpoints ---
@router.get("/", response_model=List[UserOut])
def get_users(include_inactive: bool = False, db: Session = Depends(get_db)):
    q = db.query(User)
    if not include_inactive:
        q = q.filter(User.aktif == True)
    users = q.all()

    def sort_key(u):
        role_rank = ROLE_ORDER.get(u.role, 99)
        if u.role == "mahasiswa":
            return (role_rank, u.kelas or "", u.nama or "", u.nim_nip or "")
        return (role_rank, u.nama or "")

    users.sort(key=sort_key)
    return users

@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    return user

# --- Write/Modify Endpoints ---
@router.post("/", response_model=UserOut)
def create_user(
    payload: UserCreate,
    request: Request,
    db: Session = Depends(get_db)
):
    current_role = get_current_role(request)
    allowed = ROLE_ALLOWED_TO_CREATE.get(current_role, set())
    
    if payload.role not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Role '{current_role}' tidak boleh menambahkan pengguna dengan role '{payload.role}'"
        )

    # Cek apakah NIP/NIM sudah ada
    existing = db.query(User).filter(User.nim_nip == payload.nim_nip).first()
    if existing:
        raise HTTPException(status_code=400, detail="NIM/NIP sudah terdaftar")
        
    user = User(
        nama=payload.nama, 
        nim_nip=payload.nim_nip, 
        role=payload.role,
        kelas=payload.kelas if hasattr(payload, 'kelas') else None, 
        aktif=True,
        password_hash=_hash_pw(payload.password) if getattr(payload, 'password', None) else None,
    )
    
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

@router.put("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int, 
    payload: UserUpdate, 
    request: Request,
    db: Session = Depends(get_db)
):
    current_role = get_current_role(request)
    target = db.query(User).filter(User.id == user_id).first()
    
    if not target:
        raise HTTPException(status_code=404, detail="Pengguna tidak ditemukan")
        
    allowed = ROLE_ALLOWED_TO_MODIFY.get(current_role, set())
    if target.role not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Role '{current_role}' tidak boleh mengubah data pengguna dengan role '{target.role}'"
        )
        
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(target, field, value)
        
    db.commit()
    db.refresh(target)
    return target

@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    request: Request,
    force: bool = Query(False, description="Hapus juga seluruh data & relasi terkait"),
    db: Session = Depends(get_db)
):
    current_role = get_current_role(request)
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(404, "Pengguna tidak ditemukan")

    allowed = ROLE_ALLOWED_TO_MODIFY.get(current_role, set())
    if target.role not in allowed:
        raise HTTPException(403, f"Role '{current_role}' tidak boleh menghapus pengguna dengan role '{target.role}'")
    if current_role != "admin":
        raise HTTPException(403, "Hanya admin yang dapat menghapus permanen, gunakan nonaktifkan")

    from app.models.models import AccessLog, Absensi, jadwal_mahasiswa, penanggung_jawab

    has_relasi = (
        db.query(AccessLog).filter(AccessLog.user_id == user_id).first() is not None
        or db.query(Absensi).filter(Absensi.user_id == user_id).first() is not None
        or db.execute(jadwal_mahasiswa.select().where(jadwal_mahasiswa.c.user_id == user_id)).first() is not None
        or db.execute(penanggung_jawab.select().where(penanggung_jawab.c.user_id == user_id)).first() is not None
    )

    if has_relasi and not force:
        raise HTTPException(
            400,
            "Pengguna ini memiliki riwayat/relasi data (log akses, absensi, jadwal, "
            "atau penanggung jawab ruangan). Centang opsi 'hapus beserta riwayat' "
            "untuk menghapus paksa, atau nonaktifkan saja untuk menjaga data historis."
        )

    if force:
        db.query(AccessLog).filter(AccessLog.user_id == user_id).delete()
        db.query(Absensi).filter(Absensi.user_id == user_id).delete()
        db.execute(jadwal_mahasiswa.delete().where(jadwal_mahasiswa.c.user_id == user_id))
        db.execute(penanggung_jawab.delete().where(penanggung_jawab.c.user_id == user_id))

    try:
        db.delete(target)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Gagal menghapus pengguna: {str(e)}")

    return {"pesan": "Pengguna dihapus" + (" beserta seluruh riwayatnya" if force else "")}

@router.patch("/{user_id}/toggle-aktif")
def toggle_aktif(user_id: int, request: Request, db: Session = Depends(get_db)):
    """Nonaktifkan/aktifkan — dipakai dosen & teknisi sebagai pengganti delete."""
    current_role = get_current_role(request)
    target = db.query(User).filter(User.id == user_id).first()
    
    if not target:
        raise HTTPException(status_code=404, detail="Pengguna tidak ditemukan")
        
    allowed = ROLE_ALLOWED_TO_MODIFY.get(current_role, set())
    if target.role not in allowed:
        raise HTTPException(status_code=403, detail=f"Tidak diizinkan mengubah status role '{target.role}'")
        
    target.aktif = not target.aktif
    db.commit()
    return {"pesan": "Status diperbarui", "aktif": target.aktif}

# --- Password Endpoints ---
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