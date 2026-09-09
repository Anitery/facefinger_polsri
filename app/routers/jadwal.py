import requests as http_requests
from functools import lru_cache
from datetime import datetime
from typing import Optional, List, Tuple
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session, joinedload

from app.database import get_db
from app.models.models import JadwalRuangan, User, Absensi, jadwal_mahasiswa
from app.services.auth_service import get_current_user_session

# PASTIKAN SESUAIKAN IMPORT INI DENGAN MODUL AUTENTIKASI ANDA:
# from app.dependencies import get_current_user_session 

router = APIRouter(prefix="/jadwal", tags=["Jadwal Ruangan"])

class JadwalCreate(BaseModel):
    ruangan_id: int
    nama_kegiatan: str
    kelas: Optional[str] = None
    dosen: Optional[str] = None
    mata_kuliah: Optional[str] = None
    tanggal: str
    jam_mulai: str
    jam_selesai: str
    keterangan: Optional[str] = None

class MahasiswaInfo(BaseModel):
    id: int
    nama: str
    nim_nip: str
    role: str
    model_config = {"from_attributes": True}

class JadwalOut(JadwalCreate):
    id: int
    mahasiswa_diizinkan: List[MahasiswaInfo] = []
    is_active: bool  
    model_config = {"from_attributes": True}


@lru_cache(maxsize=24)  # Cache per bulan agar tidak spam ke API eksternal
def _fetch_hari_libur_cached(year: int, month: int):
    """
    Sumber: api-hari-libur.vercel.app (scraping tanggalans.com, update
    otomatis harian). Menggantikan api-harilibur.vercel.app (paused) dan
    libur.deno.dev (down).
    """
    try:
        r = http_requests.get(
            "https://api-hari-libur.vercel.app/api",
            params={"year": year, "month": month},
            timeout=5
        )
        if r.ok:
            body = r.json()
            return body.get("data", [])
    except Exception:
        pass
    return []

def is_hari_libur(tanggal: str) -> Tuple[bool, str]:
    """
    Cek apakah tanggal adalah hari libur nasional Indonesia.
    Returns: (is_libur, nama_libur)
    """
    try:
        year, month = int(tanggal[:4]), int(tanggal[5:7])
        for h in _fetch_hari_libur_cached(year, month):
            if h.get("date") == tanggal:
                return True, h.get("description", "Hari libur nasional")
    except Exception:
        pass  # Kalau API gagal, jangan blokir (fail-open untuk ketersediaan)
    return False, ""


@router.get("/hari-libur")
def get_hari_libur(
    year: int = Query(...),
    month: int = Query(...)
):
    """
    Ambil daftar hari libur nasional Indonesia untuk bulan tertentu.
    Data dari api-hari-libur.vercel.app (scraping SKB dari tanggalans.com).
    """
    data = _fetch_hari_libur_cached(year, month)
    return [
        {
            "tanggal": d.get("date"),
            "nama":    d.get("description"),
            "is_national_holiday": True,
        }
        for d in data
        if d.get("date")
    ]


@router.get("/", response_model=List[JadwalOut])
def get_jadwal(
    ruangan_id: Optional[int] = Query(None),
    bulan: Optional[str] = Query(None),
    include_inactive: bool = Query(False),
    db: Session = Depends(get_db)
):
    q = db.query(JadwalRuangan).options(
        joinedload(JadwalRuangan.mahasiswa_diizinkan)
    )
    
    if not include_inactive:
        q = q.filter(JadwalRuangan.is_active == True)
        
    if ruangan_id:
        q = q.filter(JadwalRuangan.ruangan_id == ruangan_id)
        
    if bulan:
        q = q.filter(JadwalRuangan.tanggal.startswith(bulan))
        
    return q.order_by(JadwalRuangan.tanggal, JadwalRuangan.jam_mulai).all()


@router.get("/hari-ini-semua-ruangan")
def get_jadwal_hari_ini_semua_ruangan(db: Session = Depends(get_db)):
    """
    Jadwal aktif hari ini dari SEMUA ruangan sekaligus — dipakai dashboard
    saat pilihan ruangan di sidebar/navbar di-set ke "Semua Ruangan".
    """
    today = datetime.now().strftime("%Y-%m-%d")
    rows = db.query(JadwalRuangan).options(
        joinedload(JadwalRuangan.ruangan)
    ).filter(
        JadwalRuangan.tanggal == today,
        JadwalRuangan.is_active == True,
    ).order_by(JadwalRuangan.jam_mulai).all()

    return [
        {
            "id": j.id,
            "ruangan_id": j.ruangan_id,
            "nama_ruangan": j.ruangan.nama if j.ruangan else "-",
            "nama_kegiatan": j.nama_kegiatan,
            "kelas": j.kelas,
            "jam_mulai": j.jam_mulai,
            "jam_selesai": j.jam_selesai,
        }
        for j in rows
    ]


@router.get("/dosen-list")
def get_dosen_list(db: Session = Depends(get_db)):
    dosens = db.query(User).filter(
        User.role == "dosen", User.aktif == True
    ).order_by(User.nama).all()
    return [{"id": d.id, "nama": d.nama, "nim_nip": d.nim_nip} for d in dosens]


@router.get("/aktif/{ruangan_id}")
def get_jadwal_aktif(ruangan_id: int, db: Session = Depends(get_db)):
    """
    Cek apakah ada jadwal yang sedang aktif sekarang di ruangan ini.
    Dipakai oleh endpoint autentikasi.
    """
    now      = datetime.now()
    today    = now.strftime("%Y-%m-%d")
    now_time = now.strftime("%H:%M")

    jadwal = db.query(JadwalRuangan).options(
        joinedload(JadwalRuangan.mahasiswa_diizinkan)
    ).filter(
        JadwalRuangan.ruangan_id == ruangan_id,
        JadwalRuangan.tanggal    == today,
        JadwalRuangan.jam_mulai  <= now_time,
        JadwalRuangan.jam_selesai > now_time,
        JadwalRuangan.is_active  == True
    ).first()

    if not jadwal:
        return {"aktif": False, "jadwal": None}

    return {
        "aktif": True,
        "jadwal": {
            "id":            jadwal.id,
            "nama_kegiatan": jadwal.nama_kegiatan,
            "kelas":         jadwal.kelas,
            "dosen":         jadwal.dosen,
            "jam_mulai":     jadwal.jam_mulai,
            "jam_selesai":   jadwal.jam_selesai,
            "mahasiswa_ids": [m.id for m in jadwal.mahasiswa_diizinkan]
        }
    }


@router.post("/", response_model=JadwalOut)
def create_jadwal(
    payload: JadwalCreate,
    request: Request,
    db: Session = Depends(get_db)
):
    current = get_current_user_session(request)
    
    # Dosen tidak boleh tambah jadwal di hari libur nasional
    if current["role"] == "dosen":
        libur, nama_libur = is_hari_libur(payload.tanggal)
        if libur:
            raise HTTPException(
                400,
                f"Tanggal {payload.tanggal} adalah hari libur nasional "
                f"({nama_libur}). Jadwal tidak dapat dibuat pada hari libur."
            )
            
    jadwal = JadwalRuangan(**payload.model_dump())
    db.add(jadwal)
    db.commit()
    db.refresh(jadwal)
    return jadwal


@router.patch("/{jadwal_id}/toggle-aktif")
def toggle_aktif_jadwal(jadwal_id: int, request: Request, db: Session = Depends(get_db)):
    """Aktifkan atau nonaktifkan jadwal (Admin / Dosen pengampu)."""
    current = get_current_user_session(request)
    if current["role"] not in ("admin", "dosen"):
        raise HTTPException(403, "Tidak diizinkan")
        
    jadwal = db.query(JadwalRuangan).filter(JadwalRuangan.id == jadwal_id).first()
    if not jadwal:
        raise HTTPException(404, "Jadwal tidak ditemukan")
        
    if current["role"] == "dosen" and jadwal.dosen != current["nama"]:
        raise HTTPException(403, "Anda bukan dosen pengampu jadwal ini")
        
    jadwal.is_active = not jadwal.is_active
    db.commit()
    return {"pesan": "Status jadwal diperbarui", "is_active": jadwal.is_active}


@router.delete("/{jadwal_id}")
def hapus_jadwal(jadwal_id: int, request: Request, db: Session = Depends(get_db)):
    """Hapus jadwal beserta dependensinya secara permanen (Hanya Admin)."""
    current = get_current_user_session(request)
    if current["role"] != "admin":
        raise HTTPException(403, "Hanya admin yang dapat menghapus jadwal secara permanen")
        
    jadwal = db.query(JadwalRuangan).filter(JadwalRuangan.id == jadwal_id).first()
    if not jadwal:
        raise HTTPException(404, "Jadwal tidak ditemukan")
        
    # Hapus dependensi dulu agar tidak terbentur foreign key constraint
    db.query(Absensi).filter(Absensi.jadwal_id == jadwal_id).delete()
    db.execute(jadwal_mahasiswa.delete().where(jadwal_mahasiswa.c.jadwal_id == jadwal_id))
    
    db.delete(jadwal)
    db.commit()
    return {"pesan": "Jadwal dan seluruh data terkait (absensi & peserta) dihapus permanen"}


@router.post("/{jadwal_id}/mahasiswa/{user_id}")
def tambah_mahasiswa(jadwal_id: int, user_id: int, db: Session = Depends(get_db)):
    """Tambahkan mahasiswa ke daftar yang boleh akses jadwal ini."""
    jadwal = db.query(JadwalRuangan).options(
        joinedload(JadwalRuangan.mahasiswa_diizinkan)
    ).filter(JadwalRuangan.id == jadwal_id).first()
    if not jadwal:
        raise HTTPException(status_code=404, detail="Jadwal tidak ditemukan")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")

    if any(m.id == user_id for m in jadwal.mahasiswa_diizinkan):
        raise HTTPException(
            status_code=400,
            detail=f"{user.nama} sudah terdaftar di jadwal ini"
        )

    jadwal.mahasiswa_diizinkan.append(user)
    db.commit()
    return {"pesan": f"{user.nama} ditambahkan ke jadwal {jadwal.nama_kegiatan}"}


@router.delete("/{jadwal_id}/mahasiswa/{user_id}")
def hapus_mahasiswa(jadwal_id: int, user_id: int, db: Session = Depends(get_db)):
    """Hapus mahasiswa dari daftar akses jadwal."""
    jadwal = db.query(JadwalRuangan).options(
        joinedload(JadwalRuangan.mahasiswa_diizinkan)
    ).filter(JadwalRuangan.id == jadwal_id).first()
    if not jadwal:
        raise HTTPException(status_code=404, detail="Jadwal tidak ditemukan")

    user = next(
        (m for m in jadwal.mahasiswa_diizinkan if m.id == user_id), None
    )
    if not user:
        raise HTTPException(
            status_code=404,
            detail="Mahasiswa tidak ditemukan di jadwal ini"
        )

    jadwal.mahasiswa_diizinkan.remove(user)
    db.commit()
    return {"pesan": f"{user.nama} dihapus dari jadwal"}


@router.post("/{jadwal_id}/mahasiswa/by-kelas/{kelas}")
def tambah_mahasiswa_by_kelas(jadwal_id: int, kelas: str, db: Session = Depends(get_db)):
    """Tambahkan mahasiswa sekaligus berdasarkan kelas."""
    jadwal = db.query(JadwalRuangan).options(
        joinedload(JadwalRuangan.mahasiswa_diizinkan)
    ).filter(JadwalRuangan.id == jadwal_id).first()
    if not jadwal:
        raise HTTPException(404, "Jadwal tidak ditemukan")

    mahasiswa_kelas = db.query(User).filter(
        User.role == "mahasiswa", User.kelas == kelas, User.aktif == True
    ).all()

    sudah_ada_ids = {m.id for m in jadwal.mahasiswa_diizinkan}
    ditambahkan = 0
    for m in mahasiswa_kelas:
        if m.id not in sudah_ada_ids:
            jadwal.mahasiswa_diizinkan.append(m)
            ditambahkan += 1

    db.commit()
    return {
        "pesan": f"{ditambahkan} mahasiswa kelas {kelas} ditambahkan",
        "ditambahkan": ditambahkan,
        "total_kelas": len(mahasiswa_kelas)
    }


@router.get("/kelas-list")
def get_kelas_list(db: Session = Depends(get_db)):
    """Daftar kelas unik dari mahasiswa terdaftar."""
    rows = db.query(User.kelas).filter(
        User.role == "mahasiswa", User.kelas.isnot(None), User.kelas != ""
    ).distinct().all()
    return sorted([r[0] for r in rows])