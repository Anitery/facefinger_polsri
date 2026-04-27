from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload
from typing import Optional
from datetime import datetime as dt
from pydantic import BaseModel
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from io import BytesIO
from app.database import get_db
from app.models.models import AccessLog

router = APIRouter(prefix="/log-akses", tags=["Log Akses"])


class AccessLogDetail(BaseModel):
    id: int
    user_id: Optional[int] = None
    nama_user: Optional[str] = None
    nim_nip: Optional[str] = None
    ruangan_id: int
    waktu_akses: dt
    metode: str
    foto_url: Optional[str] = None
    status: str
    keterangan: Optional[str] = None

    model_config = {"from_attributes": True}


@router.get("/export/excel")
def export_excel(
    ruangan_id: Optional[int] = Query(None),
    db: Session = Depends(get_db)
):
    q = db.query(AccessLog).options(joinedload(AccessLog.user))
    if ruangan_id:
        q = q.filter(AccessLog.ruangan_id == ruangan_id)
    logs = q.order_by(AccessLog.waktu_akses.desc()).limit(1000).all()

    wb = Workbook()
    ws = wb.active
    ws.title = "Log Akses"

    hdr_font  = Font(bold=True, color="FFFFFF", size=11)
    hdr_fill  = PatternFill("solid", fgColor="1F3864")
    hdr_align = Alignment(horizontal="center", vertical="center")

    headers    = ["No", "Waktu Akses", "Nama Pengguna", "NIM/NIP",
                  "Metode", "Status", "Keterangan"]
    col_widths = [5, 22, 25, 20, 15, 12, 30]

    for col, (h, w) in enumerate(zip(headers, col_widths), 1):
        cell = ws.cell(row=1, column=col, value=h)
        cell.font      = hdr_font
        cell.fill      = hdr_fill
        cell.alignment = hdr_align
        ws.column_dimensions[cell.column_letter].width = w
    ws.row_dimensions[1].height = 22

    for i, log in enumerate(logs, 1):
        waktu = log.waktu_akses.strftime("%d/%m/%Y %H:%M:%S") if log.waktu_akses else ""
        row = [
            i,
            waktu,
            log.user.nama    if log.user else "Tidak dikenal",
            log.user.nim_nip if log.user else "-",
            log.metode,
            log.status,
            log.keterangan or "",
        ]
        for col, val in enumerate(row, 1):
            cell = ws.cell(row=i+1, column=col, value=val)
            cell.alignment = Alignment(vertical="center")
            if i % 2 == 0:
                cell.fill = PatternFill("solid", fgColor="EBF3FB")

    # Judul di baris paling atas
    ws.insert_rows(1)
    ws.merge_cells("A1:G1")
    title_cell = ws["A1"]
    title_cell.value = (
        f"Log Akses — Ruang Multimedia Polsri "
        f"(Export: {dt.now().strftime('%d/%m/%Y %H:%M')})"
    )
    title_cell.font      = Font(bold=True, size=12, color="1F3864")
    title_cell.alignment = Alignment(horizontal="center", vertical="center")
    ws.row_dimensions[1].height = 20

    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    filename = f"log_akses_{dt.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )


@router.get("/", response_model=list[AccessLogDetail])
def get_logs(
    ruangan_id: Optional[int] = Query(None),
    status: Optional[str] = Query(None),
    metode: Optional[str] = Query(None),
    limit: int = Query(50, le=500),
    db: Session = Depends(get_db)
):
    q = db.query(AccessLog).options(joinedload(AccessLog.user))
    if ruangan_id:
        q = q.filter(AccessLog.ruangan_id == ruangan_id)
    if status:
        q = q.filter(AccessLog.status == status)
    if metode:
        q = q.filter(AccessLog.metode == metode)

    logs = q.order_by(AccessLog.waktu_akses.desc()).limit(limit).all()

    return [
        AccessLogDetail(
            id=log.id,
            user_id=log.user_id,
            nama_user=log.user.nama    if log.user else None,
            nim_nip=log.user.nim_nip   if log.user else None,
            ruangan_id=log.ruangan_id,
            waktu_akses=log.waktu_akses,
            metode=log.metode,
            foto_url=log.foto_url,
            status=log.status,
            keterangan=log.keterangan,
        )
        for log in logs
    ]