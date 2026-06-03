from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session, joinedload
from typing import Optional
from datetime import datetime
from io import BytesIO
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from app.database import get_db
from app.models.models import Absensi, JadwalRuangan, User
from app.services.absensi_service import (
    tutup_absensi_jadwal, get_rekap_jadwal
)

router = APIRouter(prefix="/absensi", tags=["Absensi"])

STATUS_COLOR = {
    "hadir":       "dcfce7",
    "terlambat":   "fef9c3",
    "tidak_hadir": "fee2e2",
    "izin":        "eff6ff",
}


@router.get("/jadwal/{jadwal_id}")
def get_absensi_jadwal(jadwal_id: int, db: Session = Depends(get_db)):
    """Ambil rekap absensi untuk satu jadwal."""
    return get_rekap_jadwal(db, jadwal_id)


@router.get("/rekap")
def get_rekap_ruangan(
    ruangan_id:  Optional[int] = Query(None),
    bulan:       Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """
    Rekap semua absensi per jadwal dalam satu ruangan/bulan.
    """
    q = db.query(JadwalRuangan)
    if ruangan_id:
        q = q.filter(JadwalRuangan.ruangan_id == ruangan_id)
    if bulan:
        q = q.filter(JadwalRuangan.tanggal.startswith(bulan))

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


@router.get("/mahasiswa/{user_id}")
def get_absensi_mahasiswa(
    user_id:    int,
    ruangan_id: Optional[int] = Query(None),
    bulan:      Optional[str] = Query(None),
    db: Session = Depends(get_db)
):
    """Rekap absensi per mahasiswa."""
    q = db.query(Absensi).options(
        joinedload(Absensi.jadwal)
    ).filter(Absensi.user_id == user_id)

    if bulan:
        q = q.join(JadwalRuangan).filter(
            JadwalRuangan.tanggal.startswith(bulan)
        )
    if ruangan_id:
        q = q.join(JadwalRuangan).filter(
            JadwalRuangan.ruangan_id == ruangan_id
        )

    absensi_list = q.all()
    user = db.query(User).filter(User.id == user_id).first()

    return {
        "user_id":    user_id,
        "nama":       user.nama    if user else "—",
        "nim_nip":    user.nim_nip if user else "—",
        "total":      len(absensi_list),
        "hadir":      sum(1 for a in absensi_list if a.status == "hadir"),
        "terlambat":  sum(1 for a in absensi_list if a.status == "terlambat"),
        "tidak_hadir":sum(1 for a in absensi_list if a.status == "tidak_hadir"),
        "izin":       sum(1 for a in absensi_list if a.status == "izin"),
        "detail": [
            {
                "jadwal_id":     a.jadwal_id,
                "nama_kegiatan": a.jadwal.nama_kegiatan if a.jadwal else "—",
                "kelas":         a.jadwal.kelas         if a.jadwal else "—",
                "tanggal":       a.jadwal.tanggal       if a.jadwal else "—",
                "status":        a.status,
                "waktu_masuk":   a.waktu_masuk.strftime("%H:%M")
                                 if a.waktu_masuk else "—",
            }
            for a in sorted(
                absensi_list,
                key=lambda x: x.jadwal.tanggal if x.jadwal else ""
            )
        ]
    }


@router.post("/tutup/{jadwal_id}")
def tutup_absensi(jadwal_id: int, db: Session = Depends(get_db)):
    """Tutup absensi manual — isi tidak hadir untuk yang belum scan."""
    count = tutup_absensi_jadwal(db, jadwal_id)
    return {
        "pesan":        f"Absensi ditutup. {count} orang ditandai tidak hadir.",
        "tidak_hadir":  count
    }


@router.patch("/{absensi_id}/status")
def update_status_absensi(
    absensi_id: int,
    status:     str,
    keterangan: Optional[str] = None,
    db: Session = Depends(get_db)
):
    """Update status absensi manual (misal ubah ke izin)."""
    valid = {"hadir", "terlambat", "tidak_hadir", "izin"}
    if status not in valid:
        raise HTTPException(
            status_code=400,
            detail=f"Status tidak valid. Pilihan: {', '.join(valid)}"
        )
    ab = db.query(Absensi).filter(Absensi.id == absensi_id).first()
    if not ab:
        raise HTTPException(status_code=404, detail="Data absensi tidak ditemukan")

    ab.status     = status
    ab.keterangan = keterangan
    db.commit()
    return {"pesan": "Status absensi diperbarui"}


@router.get("/export/excel/{jadwal_id}")
def export_absensi_excel(jadwal_id: int, db: Session = Depends(get_db)):
    """Export absensi satu jadwal ke Excel."""
    rekap = get_rekap_jadwal(db, jadwal_id)
    if not rekap:
        raise HTTPException(status_code=404, detail="Jadwal tidak ditemukan")

    wb = Workbook()
    ws = wb.active
    ws.title = "Absensi"

    # Judul
    ws.merge_cells("A1:F1")
    ws["A1"] = (
        f"ABSENSI — {rekap['nama_kegiatan']} "
        f"({rekap.get('kelas','')}) | "
        f"{rekap['tanggal']} {rekap['jam_mulai']}–{rekap['jam_selesai']}"
    )
    ws["A1"].font      = Font(bold=True, size=12, color="1F3864")
    ws["A1"].alignment = Alignment(horizontal="center")
    ws.row_dimensions[1].height = 20

    # Info dosen
    ws["A2"] = f"Dosen: {rekap.get('dosen','—')}"
    ws["A2"].font = Font(italic=True, size=10, color="64748b")
    ws.merge_cells("A2:F2")

    # Ringkasan
    ws["A3"] = (
        f"Hadir: {rekap['hadir']} | "
        f"Terlambat: {rekap['terlambat']} | "
        f"Tidak Hadir: {rekap['tidak_hadir']} | "
        f"Izin: {rekap['izin']}"
    )
    ws["A3"].font = Font(size=10)
    ws.merge_cells("A3:F3")
    ws.row_dimensions[3].height = 16

    # Header tabel
    headers    = ["No", "Nama", "NIM/NIP", "Role", "Status", "Jam Masuk"]
    col_widths = [5, 28, 18, 12, 14, 12]
    hdr_fill   = PatternFill("solid", fgColor="1F3864")
    hdr_font   = Font(bold=True, color="FFFFFF", size=10)

    for col, (h, w) in enumerate(zip(headers, col_widths), 1):
        cell = ws.cell(row=4, column=col, value=h)
        cell.fill      = hdr_fill
        cell.font      = hdr_font
        cell.alignment = Alignment(horizontal="center", vertical="center")
        ws.column_dimensions[cell.column_letter].width = w
    ws.row_dimensions[4].height = 18

    # Data
    STATUS_LABEL = {
        "hadir":       "Hadir ✓",
        "terlambat":   "Terlambat ⚠",
        "tidak_hadir": "Tidak Hadir ✗",
        "izin":        "Izin 📋",
    }

    for i, d in enumerate(rekap["detail"], 1):
        row = [
            i, d["nama"], d["nim_nip"], d["role"],
            STATUS_LABEL.get(d["status"], d["status"]),
            d["waktu_masuk"]
        ]
        fill_color = STATUS_COLOR.get(d["status"], "FFFFFF")
        for col, val in enumerate(row, 1):
            cell            = ws.cell(row=i+4, column=col, value=val)
            cell.alignment  = Alignment(vertical="center")
            cell.fill       = PatternFill("solid", fgColor=fill_color)

    # Save
    buf = BytesIO()
    wb.save(buf)
    buf.seek(0)

    fname = (
        f"absensi_{rekap['nama_kegiatan'].replace(' ','_')}_"
        f"{rekap['tanggal']}.xlsx"
    )
    return StreamingResponse(
        buf,
        media_type=(
            "application/vnd.openxmlformats-officedocument"
            ".spreadsheetml.sheet"
        ),
        headers={"Content-Disposition": f"attachment; filename={fname}"}
    )