from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Ruangan
from app.schemas import RuanganCreate, RuanganOut

router = APIRouter(prefix="/ruangan", tags=["Ruangan"])


@router.get("/", response_model=list[RuanganOut])
def get_all(db: Session = Depends(get_db)):
    return db.query(Ruangan).filter(Ruangan.aktif == True).all()


@router.post("/", response_model=RuanganOut)
def create_ruangan(payload: RuanganCreate, db: Session = Depends(get_db)):
    ruangan = Ruangan(**payload.model_dump())
    db.add(ruangan)
    db.commit()
    db.refresh(ruangan)
    return ruangan