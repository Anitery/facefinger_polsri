from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload
from typing import Optional
from datetime import datetime, date as date_cls
from io import BytesIO

# Excel (openpyxl) imports
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment

from app.database import get_db
from app.models.models import Absensi, JadwalRuangan, User, Ruangan
from app.services.absensi_service import tutup_absensi_jadwal, get_rekap_jadwal

router = APIRouter(prefix="/absensi", tags=["Absensi"])

STATUS_COLOR = {
    "hadir":       "dcfce7",
    "terlambat":   "fef9c3",
    "tidak_hadir": "fee2e2",
    "izin":        "eff6ff",
}

# --- Helper Function ---
def get_current_user_session(request: Request):
    from app.services.auth_service import decode_session_token
    token = request.cookies.get("session_token")
    if not token:
        raise HTTPException(401, "Sesi tidak valid")
    
    user = decode_session_token(token)
    if not user:
        raise HTTPException(401, "Sesi tidak valid")
    
    return user


@router.get("/jadwal/{jadwal_id}")
def get_absensi_jadwal(jadwal_id: int, request: Request, db: Session = Depends(get_db)):
    """Ambil rekap absensi untuk satu jadwal."""
    current = get_current_user_session(request)
    jadwal = db.query(JadwalRuangan).filter(JadwalRuangan.id == jadwal_id).first()
    
    if not jadwal:
        raise HTTPException(404, "Jadwal tidak ditemukan")
        
    if current["role"] == "dosen" and jadwal.dosen != current["nama"]:
        raise HTTPException(403, "Anda bukan dosen pengampu jadwal ini")
        
    return get_rekap_jadwal(db, jadwal_id)


@router.get("/rekap")
def get_rekap_ruangan(
    request: Request,
    ruangan_id:  Optional[int] = Query(None),
    bulan:       Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Rekap semua absensi per jadwal dalam satu ruangan/bulan.
    Dosen hanya bisa melihat rekap jadwal yang diampunya.
    """
    current = get_current_user_session(request)
    q = db.query(JadwalRuangan)
    
    if ruangan_id:
        q = q.filter(JadwalRuangan.ruangan_id == ruangan_id)
    if bulan:
        q = q.filter(JadwalRuangan.tanggal.startswith(bulan))
        
    # Dosen hanya melihat jadwal yang ia ampu sendiri
    if current["role"] == "dosen":
        q = q.filter(JadwalRuangan.dosen == current["nama"])

    jadwal_list = q.order_by(
        JadwalRuangan.tanggal, JadwalRuangan.jam_mulai
    ).all()

    result = []
    for j in jadwal_list:
        absensi = db.query(Absensi).filter(
            Absensi.jadwal_id == j.id
        ).all()
        result.append({
            "jadwal_id":     j.id,
            "nama_kegiatan": j.nama_kegiatan,
            "kelas":         j.kelas,
            "tanggal":       j.tanggal,
            "jam_mulai":     j.jam_mulai,
            "jam_selesai":   j.jam_selesai,
            "dosen":         j.dosen,
            "total":         len(absensi),
            "hadir":         sum(1 for a in absensi if a.status == "hadir"),
            "terlambat":     sum(1 for a in absensi if a.status == "terlambat"),
            "tidak_hadir":   sum(1 for a in absensi if a.status == "tidak_hadir"),
            "izin":          sum(1 for a in absensi if a.status == "izin"),
            "sudah_ditutup": any(
                a.status == "tidak_hadir" for a in absensi
            ),
        })
    return result
