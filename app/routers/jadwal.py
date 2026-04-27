from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from typing import Optional
from pydantic import BaseModel
from app.database import get_db
from app.models.models import JadwalRuangan

router = APIRouter(prefix="/jadwal", tags=["Jadwal Ruangan"])


class JadwalCreate(BaseModel):
    ruangan_id: int
    nama_kegiatan: str
    dosen: Optional[str] = None
    mata_kuliah: Optional[str] = None
    tanggal: str        # YYYY-MM-DD
    jam_mulai: str      # HH:MM
    jam_selesai: str    # HH:MM
    keterangan: Optional[str] = None


class JadwalOut(JadwalCreate):
    id: int
    model_config = {"from_attributes": True}


@router.get("/", response_model=list[JadwalOut])
def get_jadwal(
    ruangan_id: Optional[int] = Query(None),
    bulan: Optional[str] = Query(None),   # format: YYYY-MM
    db: Session = Depends(get_db)
):
    q = db.query(JadwalRuangan)
    if ruangan_id:
        q = q.filter(JadwalRuangan.ruangan_id == ruangan_id)
    if bulan:
        q = q.filter(JadwalRuangan.tanggal.startswith(bulan))
    return q.order_by(JadwalRuangan.tanggal, JadwalRuangan.jam_mulai).all()


@router.post("/", response_model=JadwalOut)
def buat_jadwal(payload: JadwalCreate, db: Session = Depends(get_db)):
    jadwal = JadwalRuangan(**payload.model_dump())
    db.add(jadwal)
    db.commit()
    db.refresh(jadwal)
    return jadwal


@router.delete("/{jadwal_id}")
def hapus_jadwal(jadwal_id: int, db: Session = Depends(get_db)):
    jadwal = db.query(JadwalRuangan).filter(JadwalRuangan.id == jadwal_id).first()
    if not jadwal:
        raise HTTPException(status_code=404, detail="Jadwal tidak ditemukan")
    db.delete(jadwal)
    db.commit()
    return {"pesan": "Jadwal dihapus"}