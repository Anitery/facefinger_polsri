from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Ruangan, User, InventarisAlat
import bcrypt
import os

router = APIRouter(prefix="/setup", tags=["Setup"])

SETUP_KEY = os.getenv("SETUP_KEY", "")


def hash_pw(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


@router.post("/init")
def init_database(key: str, db: Session = Depends(get_db)):
    if not SETUP_KEY or key != SETUP_KEY:
        raise HTTPException(status_code=403, detail="Kunci tidak valid")

    if db.query(Ruangan).first():
        raise HTTPException(
            status_code=400,
            detail="Database sudah berisi data."
        )

    # ── 12 Ruangan ────────────────────────────────────────
    ruangan_list = [
        {"nama": "Ruang Multimedia",                   "lokasi": "Lantai 2", "lantai": 2},
        {"nama": "Lab Pemrograman 1",                  "lokasi": "Lantai 1", "lantai": 1},
        {"nama": "Lab Pemrograman 2",                  "lokasi": "Lantai 1", "lantai": 1},
        {"nama": "Lab Pemrograman 3",                  "lokasi": "Lantai 1", "lantai": 1},
        {"nama": "Lab Pemrograman 4",                  "lokasi": "Lantai 1", "lantai": 1},
        {"nama": "Lab Multimedia",                     "lokasi": "Lantai 2", "lantai": 2},
        {"nama": "Lab Sensor & Wireless",              "lokasi": "Lantai 2", "lantai": 2},
        {"nama": "Lab Video & Audio",                  "lokasi": "Lantai 2", "lantai": 2},
        {"nama": "Lab Multimedia 2",                   "lokasi": "Lantai 2", "lantai": 2},
        {"nama": "Lab Keamanan & Jaringan",            "lokasi": "Lantai 3", "lantai": 3},
        {"nama": "Lab Infrastruktur & Komputasi Awan", "lokasi": "Lantai 3", "lantai": 3},
        {"nama": "Perpustakaan Tekkom",                "lokasi": "Lantai 1", "lantai": 1},
        {"nama": "Gudang Teknisi",                     "lokasi": "Lantai 1", "lantai": 1},
    ]

    ruangan_objs = []
    for r in ruangan_list:
        obj = Ruangan(**r)
        db.add(obj)
        db.commit()
        db.refresh(obj)
        ruangan_objs.append(obj)

    # ── Users ─────────────────────────────────────────────
    users_data = [
        {"nama": "Administrator",     "nim_nip": "ADMIN001",           "role": "admin",     "fingerprint_id": 1, "password": "admin123"},
        {"nama": "Teknisi Lab",       "nim_nip": "TEKNISI001",         "role": "teknisi",   "fingerprint_id": 2, "password": "teknisi123"},
        {"nama": "Dr. Slamet Widodo", "nim_nip": "197305162002121001", "role": "dosen",     "fingerprint_id": 3, "password": "dosen123"},
        {"nama": "Fatah Alfi Syahri", "nim_nip": "062330701514",       "role": "mahasiswa", "fingerprint_id": 4, "password": None},
    ]

    user_objs = []
    for u in users_data:
        pw = u.pop("password")
        obj = User(
            **u,
            ruangan_id=None,
            password_hash=hash_pw(pw) if pw else None
        )
        db.add(obj)
        user_objs.append(obj)
    db.commit()

    # ── Inventaris (Ruang Multimedia) ─────────────────────
    inventaris_data = [
        {"kode_barcode": "KMP-PC-001",  "nama_alat": "Komputer Desktop HP",   "jumlah": 1},
        {"kode_barcode": "KMP-PC-002",  "nama_alat": "Komputer Desktop HP",   "jumlah": 1},
        {"kode_barcode": "KMP-PC-003",  "nama_alat": "Komputer Desktop HP",   "jumlah": 1},
        {"kode_barcode": "KMP-MON-001", "nama_alat": "Monitor LCD 24 inch",   "jumlah": 1},
        {"kode_barcode": "KMP-MON-002", "nama_alat": "Monitor LCD 24 inch",   "jumlah": 1},
        {"kode_barcode": "KMP-KBD-001", "nama_alat": "Keyboard + Mouse set",  "jumlah": 3},
        {"kode_barcode": "KMP-UPS-001", "nama_alat": "UPS APC 650VA",         "jumlah": 1},
        {"kode_barcode": "KMP-RTR-001", "nama_alat": "Router WiFi TP-Link",   "jumlah": 1},
    ]
    for item in inventaris_data:
        db.add(InventarisAlat(**item, ruangan_id=ruangan_objs[0].id))
    db.commit()

    return {
        "status": "berhasil",
        "data": {
            "ruangan":   len(ruangan_objs),
            "users":     len(users_data),
            "inventaris": len(inventaris_data)
        },
        "akun": [
            {"role": "admin",   "nim_nip": "ADMIN001",             "password": "admin123"},
            {"role": "teknisi", "nim_nip": "TEKNISI001",           "password": "teknisi123"},
            {"role": "dosen",   "nim_nip": "197305162002121001",   "password": "dosen123"},
        ],
        "PENTING": "Segera ganti password setelah login pertama!"
    }


@router.get("/status")
def check_status(db: Session = Depends(get_db)):
    return {
        "ruangan":    db.query(Ruangan).count(),
        "users":      db.query(User).count(),
        "inventaris": db.query(InventarisAlat).count(),
        "sudah_init": db.query(Ruangan).count() > 0
    }
