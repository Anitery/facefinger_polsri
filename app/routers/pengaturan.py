from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.database import get_db
from app.models.models import PengaturanSistem
from app.schemas import PengaturanOut, PengaturanUpdate
from app.services.auth_service import get_current_user_session

router = APIRouter(prefix="/pengaturan", tags=["Pengaturan Sistem"])


def get_pengaturan(db: Session) -> PengaturanSistem:
    """Get-or-create pola single-row settings — selalu ada baris id=1."""
    p = db.query(PengaturanSistem).filter(PengaturanSistem.id == 1).first()
    if not p:
        p = PengaturanSistem(id=1)
        db.add(p)
        db.commit()
        db.refresh(p)
    return p


@router.get("/", response_model=PengaturanOut)
def read_pengaturan(db: Session = Depends(get_db)):
    return get_pengaturan(db)


@router.put("/", response_model=PengaturanOut)
def update_pengaturan(
    payload: PengaturanUpdate,
    db: Session = Depends(get_db),
    user=Depends(get_current_user_session),
):
    if user["role"] != "admin":
        raise HTTPException(status_code=403, detail="Hanya admin yang bisa mengubah pengaturan sistem")

    p = get_pengaturan(db)
    data = payload.model_dump(exclude_unset=True)

    if "toleransi_keterlambatan_menit" in data and data["toleransi_keterlambatan_menit"] is not None:
        if data["toleransi_keterlambatan_menit"] < 0:
            raise HTTPException(status_code=400, detail="Toleransi keterlambatan tidak boleh negatif")

    if "toleransi_masuk_awal_menit" in data and data["toleransi_masuk_awal_menit"] is not None:
        if data["toleransi_masuk_awal_menit"] < 0:
            raise HTTPException(status_code=400, detail="Toleransi masuk awal tidak boleh negatif")

    for field, value in data.items():
        setattr(p, field, value)

    db.commit()
    db.refresh(p)
    return p