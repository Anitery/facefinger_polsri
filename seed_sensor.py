"""
Seed 100 dummy user untuk testing lokal.

Jalankan:
    python seed_users.py

Komposisi (total 100):
    - 2  teknisi   (password: teknisi123)
    - 8  dosen     (password: dosen123)
    - 90 mahasiswa (tanpa password, sama seperti seed.py)

Aman dijalankan berulang: user dengan nim_nip yang sudah ada akan dilewati.
"""
import random
import bcrypt
from sqlalchemy import func

from app.database import engine, SessionLocal, Base
from app.models.models import User

random.seed(42)  # hasil selalu sama tiap dijalankan

Base.metadata.create_all(bind=engine)
db = SessionLocal()

# rounds=4 supaya hashing cepat (cukup untuk data dummy lokal)
def hash_pw(pw: str) -> str:
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt(rounds=4)).decode()

NAMA_DEPAN = [
    "Ahmad", "Budi", "Citra", "Dewi", "Eko", "Fajar", "Gita", "Hendra",
    "Indah", "Joko", "Kartika", "Lestari", "Muhammad", "Nur", "Putri",
    "Rizky", "Sari", "Tri", "Wahyu", "Yoga", "Aditya", "Bayu", "Dian",
    "Fitri", "Rani", "Andi", "Siti", "Reza", "Nadia", "Dimas",
]
NAMA_BELAKANG = [
    "Pratama", "Saputra", "Wijaya", "Kusuma", "Hidayat", "Ramadhan",
    "Santoso", "Permata", "Lestari", "Firmansyah", "Nugroho", "Setiawan",
    "Anggraini", "Purnama", "Maulana", "Hakim", "Syahputra", "Utami",
    "Rahmawati", "Kurniawan",
]

def random_nama(used: set) -> str:
    while True:
        nama = f"{random.choice(NAMA_DEPAN)} {random.choice(NAMA_BELAKANG)}"
        if nama not in used:
            used.add(nama)
            return nama

# ── Ambil data yang sudah ada di DB ──────────────────────
existing_nim = {row[0] for row in db.query(User.nim_nip).all()}
max_perangkat = db.query(func.max(User.id_perangkat)).scalar() or 0
next_perangkat = max_perangkat + 1

used_names: set = set()
users_data = []

# ── Teknisi (2) ──────────────────────────────────────────
for i in range(1, 3):
    users_data.append({
        "nama": random_nama(used_names),
        "nim_nip": f"TEKNISI{100 + i}",
        "role": "teknisi",
        "password": "teknisi123",
    })

# ── Dosen (8) ────────────────────────────────────────────
for i in range(1, 9):
    users_data.append({
        "nama": "Dr. " + random_nama(used_names),
        "nim_nip": f"DOSEN{100 + i}",
        "role": "dosen",
        "password": "dosen123",
    })

# ── Mahasiswa (90) ───────────────────────────────────────
# NIM berurutan mulai dari 062330701501 (12 digit).
# NIM yang sudah dipakai user asli di seed.py dicadangkan agar tidak bentrok.
NIM_AWAL = 62330701501
NIM_DICADANGKAN = {"062330701514"}  # Fatah Alfi Syahri (seed.py)

nim_mahasiswa = []
n = NIM_AWAL
while len(nim_mahasiswa) < 90:
    nim = str(n).zfill(12)  # zfill menjaga angka 0 di depan
    if nim not in NIM_DICADANGKAN:
        nim_mahasiswa.append(nim)
    n += 1

for nim in nim_mahasiswa:
    users_data.append({
        "nama": random_nama(used_names),
        "nim_nip": nim,
        "role": "mahasiswa",
        "password": None,
    })

# ── Insert ───────────────────────────────────────────────
dibuat, dilewati = 0, 0
for u in users_data:
    if u["nim_nip"] in existing_nim:
        dilewati += 1
        continue

    pw = u.pop("password")
    user = User(
        **u,
        id_perangkat=next_perangkat,
        ruangan_id=None,  # akses semua ruangan
        password_hash=hash_pw(pw) if pw else None,
    )
    db.add(user)
    next_perangkat += 1
    dibuat += 1

db.commit()
db.close()

print(f"✓ {dibuat} user dibuat, {dilewati} dilewati (sudah ada)")
print("\n✅ Seed user selesai!")
print("\nContoh akun login:")
print("  Teknisi   → TEKNISI101   | teknisi123")
print("  Dosen     → DOSEN101     | dosen123")
print("  Mahasiswa → 062330700001 | (tanpa password)")