"""
Seed data KBM real — Lab Multimedia 2
Kelas 6CC (Rabu 07:00-09:30) dan 6CM (Jumat 18:30-20:30)
Semester Genap 2025/2026

Jalankan: python seed_real.py
"""
from datetime import date, timedelta
from app.database import SessionLocal, engine, Base
from app.models.models import User, Ruangan, JadwalRuangan
import bcrypt

Base.metadata.create_all(bind=engine)
db = SessionLocal()

def h(pw):
    return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()

def get_or_create_user(nim_nip, nama, role="mahasiswa",
                       fp_id=None, password=None, kelas=None):
    u = db.query(User).filter(User.nim_nip == nim_nip).first()
    if not u:
        u = User(
            nama           = nama,
            nim_nip        = nim_nip,
            role           = role,
            kelas          = kelas,
            ruangan_id     = None,
            aktif          = True,
            id_perangkat   = fp_id,
            password_hash  = h(password) if password else None,
        )
        db.add(u)
        db.flush()
        print(f"  + [{role:10}] {nama} ({nim_nip})"
              + (f" FP:{fp_id}" if fp_id else "")
              + (f" Kelas:{kelas}" if kelas else ""))
    else:
        # Update id_perangkat / kelas jika belum ada
        if fp_id and not u.id_perangkat:
            u.id_perangkat = fp_id
        if kelas and not u.kelas:
            u.kelas = kelas
        print(f"  ~ [{role:10}] {nama} — sudah ada")
    return u

def next_weekday_from(start: date, weekday: int) -> date:
    """Cari tanggal weekday pertama >= start. 0=Sen,2=Rab,4=Jum"""
    days = (weekday - start.weekday()) % 7
    return start + timedelta(days=days)

def generate_meeting_dates(start: date, weekday: int,
                           count: int = 8) -> list:
    """Generate list tanggal pertemuan mingguan."""
    dates = []
    d = next_weekday_from(start, weekday)
    for _ in range(count):
        dates.append(d.strftime("%Y-%m-%d"))
        d += timedelta(weeks=1)
    return dates

# ═══════════════════════════════════════════════════════════
# 1. CARI RUANGAN LAB MULTIMEDIA 2
# ═══════════════════════════════════════════════════════════
print("\n" + "="*55)
print("  Seed Data KBM Real — Lab Multimedia 2")
print("="*55)

ruangan = db.query(Ruangan).filter(
    Ruangan.nama.ilike("%Multimedia 2%")
).first()

if not ruangan:
    print("\n❌ Ruangan 'Lab Multimedia 2' tidak ditemukan!")
    print("   Jalankan seed.py terlebih dahulu.")
    db.close()
    exit(1)

print(f"\n✓ Ruangan : {ruangan.nama} (id={ruangan.id})")

# ═══════════════════════════════════════════════════════════
# 2. DOSEN
# id_perangkat 5 = Chairil, 6 = Adi Sutrisman
# ═══════════════════════════════════════════════════════════
print("\n── Dosen ──────────────────────────────────────────")

dosen_chairil = get_or_create_user(
    nim_nip  = "197CHAIRIL01",
    nama     = "R. M. Chairil Andri, S.S.T., M.I.T.",
    role     = "dosen",
    fp_id    = 5,
    password = "dosen123"
)

dosen_adi = get_or_create_user(
    nim_nip  = "197ADI01",
    nama     = "Adi Sutrisman, S.Kom., M.Kom.",
    role     = "dosen",
    fp_id    = 6,
    password = "dosen123"
)

db.commit()

# ═══════════════════════════════════════════════════════════
# 3. MAHASISWA 6CC
# id_perangkat 10–32 (23 mahasiswa)
# PIN di device akan diisi saat daftar fingerprint/wajah
# ═══════════════════════════════════════════════════════════
print("\n── Mahasiswa 6CC ──────────────────────────────────")

data_6cc = [
    ("062330701435", "AGUNG DILA UTAMA"),
    ("062330701436", "AL-MAN RAFFLI SAPUTRA"),
    ("062330701437", "APRILIA DAMAYANTI"),
    ("062330701438", "DZIKRY FADILLAH"),
    ("062330701439", "FAHREZI ISLAMI PASHA"),
    ("062330701440", "FAZA LA AMY"),
    ("062330701441", "ILHAM PUTRA PANI"),
    ("062330701442", "JERY JULIANSYAH"),
    ("062330701443", "M FIQIULUM"),
    ("062330701444", "M. ARIF RAHMAN"),
    ("062330701445", "M. DZAKY DARMAWAN"),
    ("062330701446", "MEILA PUTRI"),
    ("062330701447", "MUHAMMAD ABSHORUDDIN"),
    ("062330701448", "MUHAMMAD ATHIRA RAMADHAN"),
    ("062330701449", "MUHAMMAD REZA PUTRA RAMADHANI"),
    ("062330701450", "MUTTIA BELLA MEYSHA"),
    ("062330701451", "NADIA SEPTIANA"),
    ("062330701452", "NICCO DWI SATRIA"),
    ("062330701453", "RIDHO FEBRIAN"),
    ("062330701454", "RIZKI ANUGRAH"),
    ("062330701455", "SILPI HAIRUNNISA"),
    ("062330701456", "TIO SANDIKA"),
    ("062330701457", "WINDA MUFIDAH"),
]

users_6cc = []
for i, (npm, nama) in enumerate(data_6cc):
    u = get_or_create_user(npm, nama, fp_id=10 + i, kelas="6CC")
    users_6cc.append(u)

db.commit()
print(f"  ✓ Total 6CC: {len(users_6cc)} mahasiswa")

# ═══════════════════════════════════════════════════════════
# 4. MAHASISWA 6CM
# id_perangkat 33–52 (20 mahasiswa)
# ═══════════════════════════════════════════════════════════
print("\n── Mahasiswa 6CM ──────────────────────────────────")

data_6cm = [
    ("062330701530", "ADLIN ILHAM"),
    ("062330701531", "AMANDA FITRI ZASKIA"),
    ("062330701532", "BAGASKARA ADITYA"),
    ("062330701533", "FAJAR ALIANSYA"),
    ("062330701534", "INTAN MAHDALENA"),
    ("062330701535", "M FARIZ YUSUF HABIBIE"),
    ("062330701536", "M. AKBAR FADHILAH"),
    ("062330701537", "M. RASYID GYMNASTIAR"),
    ("062330701538", "M.ETO ATTHOILLAH"),
    ("062330701539", "M.WILDAN HABIB"),
    ("062330701540", "MUHAMMAD AGAM RAMADHAN"),
    ("062330701541", "MUHAMMAD ARROHMAN"),
    ("062330701542", "MUHAMMAD FATIH FARHAN"),
    ("062330701543", "MUHAMMAD RIZKY ANANDA"),
    ("062330701544", "REZA AL GIFFARI"),
    ("062330701545", "RIZKY CHAVENESI"),
    ("062330701546", "SANJAYA ANDRIAN SYAHPUTRA"),
    ("062330701547", "WAHYU GUSTIANSYAH"),
    ("062330701548", "YAZID ZINADIN ZIDAN"),
    ("062330701549", "ZAKIA PUTRI"),
]

users_6cm = []
for i, (nim, nama) in enumerate(data_6cm):
    u = get_or_create_user(nim, nama, fp_id=33 + i, kelas="6CM")
    users_6cm.append(u)

db.commit()
print(f"  ✓ Total 6CM: {len(users_6cm)} mahasiswa")

# ═══════════════════════════════════════════════════════════
# 5. JADWAL KBM
# 6CC : Rabu (weekday=2), 07:00 - 09:30, 8 pertemuan
# 6CM : Jumat (weekday=4), 18:30 - 20:30, 8 pertemuan
# Mulai dari hari ini ke depan
# ═══════════════════════════════════════════════════════════
print("\n── Jadwal KBM ─────────────────────────────────────")

today          = date.today()
# 2 = Rabu, 4 = Jumat
tanggal_6cc    = generate_meeting_dates(today, 2, count=8)
tanggal_6cm    = generate_meeting_dates(today, 4, count=8)

print(f"\n  6CC Rabu   : {tanggal_6cc[0]} s/d {tanggal_6cc[-1]}")
print(f"  6CM Jumat  : {tanggal_6cm[0]} s/d {tanggal_6cm[-1]}")

# ── Helper: buat jadwal 1 pertemuan ─────────────────────
def buat_jadwal(tanggal, nama_kegiatan, kelas, dosen_nama,
                jam_mulai, jam_selesai, mahasiswa_list):
    # Cek duplikat
    existing = db.query(JadwalRuangan).filter(
        JadwalRuangan.ruangan_id    == ruangan.id,
        JadwalRuangan.tanggal       == tanggal,
        JadwalRuangan.kelas         == kelas,
    ).first()
    if existing:
        print(f"  ~ {kelas} {tanggal} — sudah ada")
        return existing

    j = JadwalRuangan(
        ruangan_id    = ruangan.id,
        nama_kegiatan = nama_kegiatan,
        kelas         = kelas,
        dosen         = dosen_nama,
        tanggal       = tanggal,
        jam_mulai     = jam_mulai,
        jam_selesai   = jam_selesai,
    )
    db.add(j)
    db.flush()

    # Daftarkan mahasiswa ke jadwal
    for mhs in mahasiswa_list:
        if mhs not in j.mahasiswa_diizinkan:
            j.mahasiswa_diizinkan.append(mhs)

    print(f"  + {kelas} | {tanggal} | "
          f"{jam_mulai}-{jam_selesai} | "
          f"{len(mahasiswa_list)} mahasiswa")
    return j

# ── Buat jadwal 6CC ──────────────────────────────────────
print("\n  Membuat jadwal 6CC (Rabu, 07:00-09:30)...")
jadwal_6cc = []
for i, tgl in enumerate(tanggal_6cc):
    j = buat_jadwal(
        tanggal       = tgl,
        nama_kegiatan = "Praktek Sistem Multimedia",
        kelas         = "6CC",
        dosen_nama    = dosen_chairil.nama,
        jam_mulai     = "07:00",
        jam_selesai   = "09:30",
        mahasiswa_list = users_6cc
    )
    jadwal_6cc.append(j)

db.commit()

# ── Buat jadwal 6CM ──────────────────────────────────────
print("\n  Membuat jadwal 6CM (Jumat, 18:30-20:30)...")
jadwal_6cm = []
for i, tgl in enumerate(tanggal_6cm):
    j = buat_jadwal(
        tanggal       = tgl,
        nama_kegiatan = "Praktek Sistem Multimedia",
        kelas         = "6CM",
        dosen_nama    = dosen_adi.nama,
        jam_mulai     = "18:30",
        jam_selesai   = "20:30",
        mahasiswa_list = users_6cm
    )
    jadwal_6cm.append(j)

db.commit()

# ═══════════════════════════════════════════════════════════
# 6. RINGKASAN
# ═══════════════════════════════════════════════════════════
print("\n" + "="*55)
print("  ✅ Seed Data Real Selesai!")
print("="*55)
print(f"\n  Ruangan    : {ruangan.nama} (id={ruangan.id})")
print(f"  Dosen      : 2 (Chairil FP:5, Adi S. FP:6)")
print(f"  Mahasiswa  : 23 (6CC, FP:10-32) + 20 (6CM, FP:33-52)")
print(f"  Jadwal     : {len(jadwal_6cc)+len(jadwal_6cm)} pertemuan")
print(f"               6CC: {len(jadwal_6cc)}x Rabu 07:00-09:30")
print(f"               6CM: {len(jadwal_6cm)}x Jumat 18:30-20:30")

print("\n  ⚠ id_perangkat (PIN device) yang disiapkan di sini:")
print("  Chairil   : FP 5  | Adi S.   : FP 6")
print("  6CC       : FP 10-32 (sesuai urutan daftar)")
print("  6CM       : FP 33-52 (sesuai urutan daftar)")
print("  (Admin/Teknisi/user dasar lain diasumsikan sudah dibuat oleh seed.py)")

print("\n  Langkah selanjutnya:")
print("  1. Daftarkan wajah/fingerprint mahasiswa di alat X606-S")
print("     sesuai urutan id_perangkat di atas")
print("  2. Atau edit id_perangkat via dashboard → Pengguna")
print("     setelah mahasiswa mendaftar di alat")
print("  3. Jalankan bridge: python x606_bridge.py")
print("="*55 + "\n")

db.close()