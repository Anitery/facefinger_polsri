from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Ruangan, User, InventarisAlat
import bcrypt
import os

router = APIRouter(prefix="/setup", tags=["Setup"])

# Kunci rahasia untuk proteksi endpoint ini
# Ambil dari environment variable SETUP_KEY
SETUP_KEY = os.getenv("SETUP_KEY", "init-polsri-2025")


def hash_pw(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


@router.post("/init")
def init_database(key: str, db: Session = Depends(get_db)):
    """
    Endpoint untuk inisialisasi data awal di production.
    Hanya bisa dipanggil dengan SETUP_KEY yang benar.
    Jalankan SEKALI saja lalu hapus endpoint ini.
    """
    # Validasi kunci
    if not SETUP_KEY or key != SETUP_KEY:
        raise HTTPException(status_code=403, detail="Kunci tidak valid")

    # Cek apakah sudah pernah diinisialisasi
    if db.query(Ruangan).first():
        raise HTTPException(
            status_code=400,
            detail="Database sudah berisi data. Inisialisasi dibatalkan."
        )

    # ── Buat ruangan ──────────────────────────────────────
    ruangan = Ruangan(
        nama="Ruang Multimedia",
        lokasi="Gedung Kuliah Lantai 2",
        lantai=2
    )
    db.add(ruangan)
    db.commit()
    db.refresh(ruangan)

    # ── Buat users ────────────────────────────────────────
    users_data = [
        {
            "nama":           "Administrator",
            "nim_nip":        "ADMIN001",
            "role":           "admin",
            "fingerprint_id": 1,
            "password":       "admin123",
        },
        {
            "nama":           "Teknisi Lab",
            "nim_nip":        "TEKNISI001",
            "role":           "teknisi",
            "fingerprint_id": 2,
            "password":       "teknisi123",
        },
        {
            "nama":           "Dr. Slamet Widodo",
            "nim_nip":        "197305162002121001",
            "role":           "dosen",
            "fingerprint_id": 3,
            "password":       "dosen123",
        },
        {
            "nama":           "Fatah Alfi Syahri",
            "nim_nip":        "062330701514",
            "role":           "mahasiswa",
            "fingerprint_id": 4,
            "password":       None,
        },
    ]

    for u in users_data:
        pw = u.pop("password")
        user = User(
            **u,
            ruangan_id=ruangan.id,
            password_hash=hash_pw(pw) if pw else None
        )
        db.add(user)
    db.commit()

    # ── Buat inventaris ───────────────────────────────────
    inventaris_data = [
        {"kode_barcode": "KMP-PC-001",  "nama_alat": "Komputer Desktop HP",  "jumlah": 1},
        {"kode_barcode": "KMP-PC-002",  "nama_alat": "Komputer Desktop HP",  "jumlah": 1},
        {"kode_barcode": "KMP-PC-003",  "nama_alat": "Komputer Desktop HP",  "jumlah": 1},
        {"kode_barcode": "KMP-MON-001", "nama_alat": "Monitor LCD 24 inch",  "jumlah": 1},
        {"kode_barcode": "KMP-MON-002", "nama_alat": "Monitor LCD 24 inch",  "jumlah": 1},
        {"kode_barcode": "KMP-KBD-001", "nama_alat": "Keyboard + Mouse set", "jumlah": 3},
        {"kode_barcode": "KMP-UPS-001", "nama_alat": "UPS APC 650VA",        "jumlah": 1},
        {"kode_barcode": "KMP-RTR-001", "nama_alat": "Router WiFi TP-Link",  "jumlah": 1},
    ]

    for item in inventaris_data:
        db.add(InventarisAlat(**item, ruangan_id=ruangan.id))
    db.commit()

    return {
        "status": "berhasil",
        "pesan": "Database berhasil diinisialisasi",
        "data": {
            "ruangan": ruangan.nama,
            "users": len(users_data),
            "inventaris": len(inventaris_data)
        },
        "akun_login": [
            {"role": "admin",   "nim_nip": "ADMIN001",             "password": "admin123"},
            {"role": "teknisi", "nim_nip": "TEKNISI001",           "password": "teknisi123"},
            {"role": "dosen",   "nim_nip": "197305162002121001",   "password": "dosen123"},
        ],
        "PENTING": "Segera ganti password setelah login pertama!"
    }


@router.get("/status")
def check_status(db: Session = Depends(get_db)):
    """Cek status database tanpa perlu key."""
    ruangan_count = db.query(Ruangan).count()
    user_count    = db.query(User).count()
    inv_count     = db.query(InventarisAlat).count()
    return {
        "database": "terhubung",
        "ruangan":   ruangan_count,
        "users":     user_count,
        "inventaris": inv_count,
        "sudah_init": ruangan_count > 0
    }