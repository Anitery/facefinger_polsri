from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import InventarisAlat
from app.schemas import InventarisCreate, InventarisOut
from typing import Optional

router = APIRouter(prefix="/inventaris", tags=["Inventaris"])


@router.get("/", response_model=list[InventarisOut])
def get_inventaris(
    ruangan_id: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    q = db.query(InventarisAlat)
    if ruangan_id:
        q = q.filter(InventarisAlat.ruangan_id == ruangan_id)
    return q.all()

@router.get("/barcode/{kode}", response_model=InventarisOut)
def get_by_barcode(kode: str, db: Session = Depends(get_db)):
    alat = db.query(InventarisAlat).filter(InventarisAlat.kode_barcode == kode).first()
    if not alat:
        raise HTTPException(status_code=404, detail="Alat tidak ditemukan")
    return alat


@router.post("/", response_model=InventarisOut)
def create_alat(payload: InventarisCreate, db: Session = Depends(get_db)):
    alat = InventarisAlat(**payload.model_dump())
    db.add(alat)
    db.commit()
    db.refresh(alat)
    return alat


@router.patch("/{alat_id}/status")
def update_status(alat_id: int, status: str, db: Session = Depends(get_db)):
    alat = db.query(InventarisAlat).filter(InventarisAlat.id == alat_id).first()
    if not alat:
        raise HTTPException(status_code=404, detail="Alat tidak ditemukan")
    if status not in ["tersedia", "dipinjam", "rusak"]:
        raise HTTPException(status_code=400, detail="Status tidak valid")
    alat.status = status
    db.commit()
    return {"pesan": f"Status {alat.nama_alat} diperbarui ke '{status}'"}

@router.put("/{alat_id}")
def update_alat(alat_id: int, payload: InventarisCreate, db: Session = Depends(get_db)):
    alat = db.query(InventarisAlat).filter(InventarisAlat.id == alat_id).first()
    if not alat:
        raise HTTPException(status_code=404, detail="Alat tidak ditemukan")
    alat.kode_barcode = payload.kode_barcode
    alat.nama_alat    = payload.nama_alat
    alat.jumlah       = payload.jumlah
    alat.keterangan   = payload.keterangan
    db.commit()
    db.refresh(alat)
    return alat

@router.delete("/{alat_id}")
def delete_alat(alat_id: int, db: Session = Depends(get_db)):
    alat = db.query(InventarisAlat).filter(InventarisAlat.id == alat_id).first()
    if not alat:
        raise HTTPException(status_code=404, detail="Alat tidak ditemukan")
    db.delete(alat)
    db.commit()
    return {"pesan": "Alat dihapus"}