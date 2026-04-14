from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from typing import Optional
from app.database import get_db
from app.models.models import AccessLog
from app.schemas import AccessLogOut

router = APIRouter(prefix="/log-akses", tags=["Log Akses"])


@router.get("/", response_model=list[AccessLogOut])
def get_logs(
    ruangan_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    limit: int = Query(50, le=200),
    db: Session = Depends(get_db)
):
    q = db.query(AccessLog)
    if ruangan_id:
        q = q.filter(AccessLog.ruangan_id == ruangan_id)
    if status:
        q = q.filter(AccessLog.status == status)
    return q.order_by(AccessLog.waktu_akses.desc()).limit(limit).all()