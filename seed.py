"""
Jalankan sekali untuk mengisi data awal:
    python seed.py
"""
from app.database import engine, SessionLocal, Base
from app.models.models import Ruangan, User, InventarisAlat
import bcrypt

Base.metadata.create_all(bind=engine)
db = SessionLocal()

def hash_pw(pw): 
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()

# Cek apakah sudah ada data
if db.query(Ruangan).first():
    print("⚠ Data sudah ada, seed dibatalkan.")
    db.close()
    exit()

# ── 12 Ruangan ───────────────────────────────────────────
ruangan_list = [
    {"nama": "Lab Pemrograman 1",               "lokasi": "Lantai 2", "lantai": 2},
    {"nama": "Lab Pemrograman 2",               "lokasi": "Lantai 2", "lantai": 2},
    {"nama": "Lab Pemrograman 3",               "lokasi": "Lantai 2", "lantai": 2},
    {"nama": "Lab Pemrograman 4",               "lokasi": "Lantai 2", "lantai": 2},
    {"nama": "Lab Multimedia",                  "lokasi": "Lantai 2", "lantai": 2},
    {"nama": "Lab Sensor & Wireless",           "lokasi": "Lantai 2", "lantai": 2},
    {"nama": "Lab Video & Audio",               "lokasi": "Lantai 2", "lantai": 2},
    {"nama": "Lab Multimedia 2",                "lokasi": "Lantai 2", "lantai": 2},
    {"nama": "Lab Keamanan & Jaringan",         "lokasi": "Lantai 2", "lantai": 2},
    {"nama": "Lab Infrastruktur & Komputasi Awan", "lokasi": "Lantai 2", "lantai": 2},
    {"nama": "Perpustakaan Tekkom",             "lokasi": "Lantai Dasar", "lantai": 0},
    {"nama": "Gudang Teknisi",                  "lokasi": "Lantai Dasar", "lantai": 0},
]

ruangan_objs = []
for r in ruangan_list:
    obj = Ruangan(**r)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    ruangan_objs.append(obj)
    print(f"✓ Ruangan: {obj.nama} (id={obj.id})")

# ── Users ────────────────────────────────────────────────
# ruangan_id=None artinya bisa akses semua ruangan
users_data = [
    {"nama": "Administrator",       "nim_nip": "ADMIN001",           "role": "admin",     "fingerprint_id": 1,  "password": "admin123"},
    {"nama": "Teknisi Lab",         "nim_nip": "TEKNISI001",         "role": "teknisi",   "fingerprint_id": 2,  "password": "teknisi123"},
    {"nama": "Dr. Slamet Widodo",   "nim_nip": "197305162002121001", "role": "dosen",     "fingerprint_id": 3,  "password": "dosen123"},
    {"nama": "Fatah Alfi Syahri",   "nim_nip": "062330701514",       "role": "mahasiswa", "fingerprint_id": 4,  "password": None},
]

for u in users_data:
    pw = u.pop("password")
    user = User(
        **u,
        ruangan_id=None,   # akses semua ruangan
        password_hash=hash_pw(pw) if pw else None
    )
    db.add(user)
db.commit()
print(f"✓ {len(users_data)} user dibuat")

# ── Inventaris (hanya untuk Ruang Multimedia) ────────────
r_multimedia = ruangan_objs[0]
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
    db.add(InventarisAlat(**item, ruangan_id=r_multimedia.id))
db.commit()
print(f"✓ {len(inventaris_data)} item inventaris dibuat")

db.close()
print("\n✅ Seed selesai!")
print("\nAkun login:")
print("  Admin   → ADMIN001           | admin123")
print("  Teknisi → TEKNISI001         | teknisi123")
print("  Dosen   → 197305162002121001 | dosen123")