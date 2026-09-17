from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session, joinedload
from typing import Optional
from pydantic import BaseModel
from app.database import get_db
from app.models.models import Ruangan, User
from app.schemas import RuanganCreate, RuanganOut, RuanganDoorServiceUpdate
from app.services.auth_service import get_current_user_session

router = APIRouter(prefix="/ruangan", tags=["Ruangan"])

class RuanganUpdate(BaseModel):
    nama:   str
    lokasi: Optional[str] = None
    lantai: Optional[int] = None


@router.get("/", response_model=list[RuanganOut])
def get_all(include_inactive: bool = False, db: Session = Depends(get_db)):
    """Mendapatkan daftar ruangan. Admin bisa melihat data nonaktif dengan include_inactive=True"""
    q = db.query(Ruangan).options(joinedload(Ruangan.penanggung_jawab))
    if not include_inactive:
        q = q.filter(Ruangan.aktif == True)
    return q.order_by(Ruangan.id).all()


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


@router.delete("/{ruangan_id}")
def delete_ruangan(
    ruangan_id: int,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_session),
):
    """Hapus ruangan secara permanen (Hanya Admin).

    BUG LAMA: endpoint ini memanggil get_current_role(request) yang tidak
    pernah diimpor (importnya dikomentari), jadi setiap kali dipanggil
    selalu meledak NameError -> 500, bukan 403 seperti yang dimaksud.
    Diganti pakai get_current_user_session yang sudah dipakai konsisten
    di router lain (auth_service.py) supaya endpoint ini benar-benar bisa
    dipanggil dan role-check-nya jalan.
    """
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Hanya admin yang dapat menghapus ruangan")

    ruangan = db.query(Ruangan).filter(Ruangan.id == ruangan_id).first()
    if not ruangan:
        raise HTTPException(status_code=404, detail="Ruangan tidak ditemukan")

    db.delete(ruangan)
    db.commit()
    return {"pesan": "Ruangan dihapus"}


@router.patch("/{ruangan_id}/door-service", response_model=RuanganOut)
def set_door_service(
    ruangan_id: int,
    payload: RuanganDoorServiceUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_session),
):
    """
    Atur alamat door_service.py (STB) untuk 1 ruangan spesifik — ini yang
    membuat backend bisa melayani banyak lab sekaligus (beda STB/port)
    tanpa perlu env DOOR_SERVICE_URL tunggal & tanpa redeploy.

    Contoh body:
        {"door_service_url": "http://10.17.47.163:8103"}

    Kosongkan/kirim null untuk kembali memakai fallback global/env.
    """
    if user["role"] not in ("admin", "teknisi"):
        raise HTTPException(status_code=403, detail="Hanya admin/teknisi yang boleh mengubah konfigurasi door_service")

    ruangan = db.query(Ruangan).filter(Ruangan.id == ruangan_id).first()
    if not ruangan:
        raise HTTPException(status_code=404, detail="Ruangan tidak ditemukan")

    if payload.door_service_url is not None:
        ruangan.door_service_url = payload.door_service_url.strip() or None
    if payload.door_service_api_key is not None:
        ruangan.door_service_api_key = payload.door_service_api_key.strip() or None

    db.commit()
    db.refresh(ruangan)
    return ruangan