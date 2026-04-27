"""
Jalankan sekali untuk mengisi data awal:
  python seed.py
"""
from app.database import engine, SessionLocal, Base
from app.models.models import Ruangan, User, InventarisAlat
from app.services.auth_service import hash_password

Base.metadata.create_all(bind=engine)
db = SessionLocal()

# Cek apakah sudah ada data
if db.query(Ruangan).first():
    print("⚠️  Data sudah ada, seed dibatalkan.")
    db.close()
    exit()

# ── Ruangan ──────────────────────────────────────────────
ruangan = Ruangan(nama="Ruang Multimedia", lokasi="Gedung Kuliah Lantai 2", lantai=2)
db.add(ruangan)
db.commit()
db.refresh(ruangan)
print(f"✓ Ruangan: {ruangan.nama} (id={ruangan.id})")

# ── Users ────────────────────────────────────────────────
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
        "password":       None,   # mahasiswa tidak bisa login dashboard
    },
]

for u in users_data:
    pw = u.pop("password")
    user = User(
        **u,
        ruangan_id=ruangan.id,
        password_hash=hash_password(pw) if pw else None
    )
    db.add(user)
db.commit()
print(f"✓ {len(users_data)} user dibuat")

# ── Inventaris ───────────────────────────────────────────
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
    db.add(InventarisAlat(**item, ruangan_id=ruangan.id))
db.commit()
print(f"✓ {len(inventaris_data)} item inventaris dibuat")

db.close()
print("\n✅ Seed selesai!")
print("\nAkun login dashboard:")
print("  Admin    → NIM/NIP: ADMIN001      | Password: admin123")
print("  Teknisi  → NIM/NIP: TEKNISI001    | Password: teknisi123")
print("  Dosen    → NIM/NIP: 197305162002121001 | Password: dosen123")