from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import Optional
from pydantic import BaseModel
from app.database import get_db
from app.models.models import Ruangan, User
from app.schemas import RuanganCreate, RuanganOut

router = APIRouter(prefix="/ruangan", tags=["Ruangan"])


class RuanganUpdate(BaseModel):
    nama:   str
    lokasi: Optional[str] = None
    lantai: Optional[int] = None


@router.get("/", response_model=list[RuanganOut])
def get_all(db: Session = Depends(get_db)):
    return db.query(Ruangan)\
             .options(joinedload(Ruangan.penanggung_jawab))\
             .filter(Ruangan.aktif == True)\
             .order_by(Ruangan.id).all()


@router.get("/{ruangan_id}", response_model=RuanganOut)
def get_ruangan(ruangan_id: int, db: Session = Depends(get_db)):
    r = db.query(Ruangan)\
          .options(joinedload(Ruangan.penanggung_jawab))\
          .filter(Ruangan.id == ruangan_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Ruangan tidak ditemukan")
    return r


@router.post("/", response_model=RuanganOut)
def create_ruangan(payload: RuanganCreate, db: Session = Depends(get_db)):
    ruangan = Ruangan(**payload.model_dump())
    db.add(ruangan)
    db.commit()
    db.refresh(ruangan)
    return ruangan


@router.put("/{ruangan_id}", response_model=RuanganOut)
def update_ruangan(
    ruangan_id: int,
    payload: RuanganUpdate,
    db: Session = Depends(get_db)
):
    r = db.query(Ruangan).filter(Ruangan.id == ruangan_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Ruangan tidak ditemukan")
    r.nama   = payload.nama
    r.lokasi = payload.lokasi
    r.lantai = payload.lantai
    db.commit()
    db.refresh(r)
    return r


@router.patch("/{ruangan_id}/toggle")
def toggle_ruangan(ruangan_id: int, db: Session = Depends(get_db)):
    r = db.query(Ruangan).filter(Ruangan.id == ruangan_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Ruangan tidak ditemukan")
    r.aktif = not r.aktif
    db.commit()
    return {"pesan": f"Ruangan {r.nama} "
            f"{'diaktifkan' if r.aktif else 'dinonaktifkan'}"}


@router.post("/{ruangan_id}/penanggung-jawab/{user_id}")
def tambah_pj(
    ruangan_id: int,
    user_id: int,
    db: Session = Depends(get_db)
):
    """Tambah penanggung jawab ke ruangan."""
    r = db.query(Ruangan).options(
        joinedload(Ruangan.penanggung_jawab)
    ).filter(Ruangan.id == ruangan_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Ruangan tidak ditemukan")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    if user.role not in ("dosen", "teknisi", "admin"):
        raise HTTPException(
            status_code=400,
            detail="Hanya dosen/teknisi/admin yang bisa jadi penanggung jawab"
        )

    # Cek sudah ada belum
    if any(u.id == user_id for u in r.penanggung_jawab):
        raise HTTPException(
            status_code=400,
            detail=f"{user.nama} sudah menjadi penanggung jawab ruangan ini"
        )

    r.penanggung_jawab.append(user)
    db.commit()
    return {
        "pesan":   f"{user.nama} ditambahkan sebagai penanggung jawab {r.nama}",
        "ruangan": r.nama,
        "user":    user.nama
    }


@router.delete("/{ruangan_id}/penanggung-jawab/{user_id}")
def hapus_pj(
    ruangan_id: int,
    user_id: int,
    db: Session = Depends(get_db)
):
    """Hapus penanggung jawab dari ruangan."""
    r = db.query(Ruangan).options(
        joinedload(Ruangan.penanggung_jawab)
    ).filter(Ruangan.id == ruangan_id).first()
    if not r:
        raise HTTPException(status_code=404, detail="Ruangan tidak ditemukan")

    user = next((u for u in r.penanggung_jawab if u.id == user_id), None)
    if not user:
        raise HTTPException(
            status_code=404,
            detail="User bukan penanggung jawab ruangan ini"
        )

    r.penanggung_jawab.remove(user)
    db.commit()
    return {"pesan": f"{user.nama} dihapus dari penanggung jawab {r.nama}"}