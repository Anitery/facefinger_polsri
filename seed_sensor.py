"""
Seed data Lab Sensor & Wireless (ruangan_id=7) — Data FINAL TA
Kelas 2CC (Senin), 2CE (Selasa), 2CF (Selasa)
Jalankan: python seed_lab_sensor.py
"""
import bcrypt
from datetime import date, timedelta
from app.database import SessionLocal
from app.models.models import User, Ruangan, JadwalRuangan

db = SessionLocal()

def h(pw): return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()

# ── Helper ───────────────────────────────────────────────────────────────────

def upsert_user(nama, nim_nip, role, kelas=None, id_perangkat=None, password="polsri123"):
    u = db.query(User).filter(User.nim_nip == nim_nip).first()
    if not u:
        u = User(
            nama=nama, nim_nip=nim_nip, role=role,
            kelas=kelas, id_perangkat=id_perangkat, aktif=True,
            password_hash=h(password),
        )
        db.add(u)
        db.flush()
        print(f"  + [{role:10}] {nama} ({nim_nip})")
    else:
        u.kelas = kelas
        u.aktif = True
        if id_perangkat: u.id_perangkat = id_perangkat
        print(f"  ~ [{role:10}] {nama} — update")
    return u

def next_wd(start: date, wd: int) -> date:
    """Maju ke hari pertama dengan weekday wd (0=Sen,...,6=Min) mulai dari start."""
    d = start
    while d.weekday() != wd:
        d += timedelta(days=1)
    return d

def buat_jadwal(ruangan_id, tgl, kegiatan, kelas, dosen_nama, jm, js):
    ex = db.query(JadwalRuangan).filter(
        JadwalRuangan.ruangan_id == ruangan_id,
        JadwalRuangan.tanggal   == tgl,
        JadwalRuangan.kelas     == kelas,
        JadwalRuangan.jam_mulai == jm,
    ).first()
    if ex:
        print(f"  ~ {kelas} {tgl} {jm} — sudah ada, skip")
        return ex
    j = JadwalRuangan(
        ruangan_id=ruangan_id, nama_kegiatan=kegiatan, kelas=kelas,
        dosen=dosen_nama, tanggal=tgl, jam_mulai=jm, jam_selesai=js,
        is_active=True,
    )
    db.add(j)
    print(f"  + {kelas} | {tgl} | {jm}–{js}")
    return j

# ── Verifikasi Ruangan ────────────────────────────────────────────────────────

print("\n=== Verifikasi Ruangan ===")
ruangan = db.query(Ruangan).filter(Ruangan.id == 7).first()
if not ruangan:
    print("❌ Ruangan id=7 tidak ditemukan! Buat dulu via dashboard.")
    db.close()
    exit(1)
print(f"✓ {ruangan.nama} (id={ruangan.id})")

# ── Dosen & Teknisi ───────────────────────────────────────────────────────────

print("\n=== Dosen & Teknisi ===")
# ID Perangkat 1 = admin, 2-3 = slot cadangan, mulai dari 7 untuk staf
upsert_user("Dr. Slamet Widodo, S.Kom., M.Kom.",                   "197305162002121001", "dosen",   id_perangkat=7)
upsert_user("Ali Firdaus, M. Kom.",                                "197010112001121001", "dosen",   id_perangkat=8)
upsert_user("Indarto, S.T., M.Cs.",                                "197307062005011003", "dosen",   id_perangkat=9)
upsert_user("Herlambang Saputra, M.Kom, Ph.D",                    "198103182008121002", "dosen",   id_perangkat=10)
upsert_user("Ariansyah Saputra, S.Kom. M.Kom",                    "198907122019031012", "dosen",   id_perangkat=11)
upsert_user("Iwan setiawan, S.T.",                                 "197807212008101001", "teknisi", id_perangkat=12)
upsert_user("Muhammad Wahyudi, S.Kom.",                            "199009152010121001", "teknisi", id_perangkat=13)
upsert_user("Willy Andre, S.Kom.",                                 "198501082019031007", "teknisi", id_perangkat=14)
upsert_user("Dr. Ir. Alan Novi Tompunu, S.T., M.T., IPM., ASEAN Eng., APEC Eng",
                                                                   "197611082000031002", "dosen",   id_perangkat=15)
faris = upsert_user("Faris Humam, M.Kom.",                        "199105052022031006", "dosen",   id_perangkat=16)
agus  = upsert_user("Muhammad Agus Triawan, M.T.",                "199008122022031004", "dosen",   id_perangkat=17)
db.commit()

# ── Mahasiswa 2CC ─────────────────────────────────────────────────────────────

print("\n=== Mahasiswa 2CC ===")
DATA_2CC = [
    ("062530701415", "Airin Febriyanti"),
    ("062530701416", "Alfin Aditri"),
    ("062530701417", "Annisa Akhsan"),
    ("062530701418", "Bima Praja"),
    ("062530701419", "Fakhriah Nissa Aslamiyah"),
    ("062530701420", "Gustria Amanda"),
    ("062530701421", "Ibnu Prabu Bintang"),
    ("062530701422", "Iyyara Dwi Indira Pramesti"),
    ("062530701423", "Lutfiyah Bahira Balqis Dar"),
    ("062530701424", "M. Aldi Pratama"),
    ("062530701425", "M. Fariz Alfahreza"),
    ("062530701426", "M. Rizki Al Muyassar"),
    ("062530701427", "Milza Agnesia"),
    ("062530701428", "Muhammad Fauzan"),
    ("062530701429", "Muhammad Rizki Ihwani Riant"),
    ("062530701430", "Nur Septiani"),
    ("062530701431", "R. Islami Al-Bariq Pasyah"),
    ("062530701432", "Rafa Atsaal Ramadhan Kamal"),
    ("062530701433", "Raisyah Putri"),
    ("062530701434", "Rizma Muzdalifah"),
    ("062530701435", "Tri Mawarni"),
]
perangkat_counter = 20  # mulai ID perangkat 20 untuk mahasiswa baru
for nim, nama in DATA_2CC:
    upsert_user(nama, nim, "mahasiswa", kelas="2CC", id_perangkat=perangkat_counter)
    perangkat_counter += 1
db.commit()

# ── Mahasiswa 2CE ─────────────────────────────────────────────────────────────

print("\n=== Mahasiswa 2CE ===")
DATA_2CE = [
    ("062530701458", "Adhitia Ksatria Seroja"),
    ("062530701459", "Ariya Damar Hartanta Utama"),
    ("062530701460", "Chika Aulia Agustin"),
    ("062530701461", "Danu"),
    ("062530701462", "Dwi Prayoga"),
    ("062530701463", "Fawaid As'ad Sama'ullah"),
    ("062530701464", "Fitri Nur Okta Viani"),
    ("062530701465", "Jogi Adlu Hakim Siregar"),
    ("062530701466", "Kesya Laura Sabrina"),
    ("062530701467", "M. Fadhil Chaniago"),
    ("062530701468", "M. Ghazi Napoleon"),
    ("062530701469", "M. Rega Syaputra"),
    ("062530701470", "Much Ridha"),
    ("062530701471", "Muhammad Ahlul Sidiq"),
    ("062530701472", "Muhammad Azki"),
    ("062530701473", "Muhammad Faiz Aziz Sulaiman"),
    ("062530701475", "Nur Salsabila"),
    ("062530701477", "Raihan Ramadani"),
    ("062530701478", "Sana"),
    ("062530701479", "Sandy Aryanto"),
]
for nim, nama in DATA_2CE:
    upsert_user(nama, nim, "mahasiswa", kelas="2CE", id_perangkat=perangkat_counter)
    perangkat_counter += 1
db.commit()

# ── Mahasiswa 2CF ─────────────────────────────────────────────────────────────

print("\n=== Mahasiswa 2CF ===")
DATA_2CF = [
    ("062530701480", "Ahmad Soramaryo Siregar"),
    ("062530701481", "Alfito Yudi Alghifari"),
    ("062530701482", "Bimasakti Raihan Saputra"),
    ("062530701484", "Desti Dwi Anggaraini"),
    ("062530701485", "Faqih Yoda Azhada"),
    ("062530701486", "Hendri Akbar Roka"),
    ("062530701487", "Iswatun Hasanah"),
    ("062530701488", "Klara Anjani"),
    ("062530701490", "M. Faiz Khairul Bashar"),
    ("062530701492", "M. Affan Alrahman"),
    ("062530701493", "Muhammad Alfarazil Falaaakh"),
    ("062530701494", "Muhammad Daffa Pratama"),
    ("062530701495", "Muhammad Faris Alfarizy"),
    ("062530701496", "Mustofa Al Hamid"),
    ("062530701497", "Osyabila Magfiro"),
    ("062530701498", "Revaldi Surya Pratama"),
    ("062530701499", "Sutra Anggara"),
    ("062530701500", "Syalwa Meidini Putri"),
]
for nim, nama in DATA_2CF:
    upsert_user(nama, nim, "mahasiswa", kelas="2CF", id_perangkat=perangkat_counter)
    perangkat_counter += 1
db.commit()

# ── Mahasiswa Tambahan (TA Kelompok) ─────────────────────────────────────────

print("\n=== Mahasiswa Tambahan ===")
DATA_TAMBAHAN = [
    ("062330701452", "Nicco Dwi Satria",           "6CC", None),
    ("062330701514", "Fatah Alfi Syahri",           "6CF", 4),   # id_perangkat sudah ada
    ("062330701511", "Avip Kurniawan Harahap",      "6CF", None),
    ("062330701517", "M. Andriano Alfarazy",        "6CF", None),
    ("062330701521", "Muhammad Eqsha Azmiansyah",   "6CF", None),
]
for nim, nama, kelas, id_prk in DATA_TAMBAHAN:
    u = upsert_user(nama, nim, "mahasiswa", kelas=kelas, id_perangkat=id_prk)
    if not id_prk:  # assign ID Perangkat kalau belum ada
        u.id_perangkat = perangkat_counter
        perangkat_counter += 1
db.commit()

# ── Jadwal KBM ────────────────────────────────────────────────────────────────
# 2CC: Senin, dua blok (07:00–09:30 dan 10:00–12:30)
# 2CE: Selasa, blok sore (15:40–18:10)
# 2CF: Selasa, blok siang (12:40–15:10)
# Generate 8 minggu ke depan dari hari ini

print("\n=== Jadwal KBM ===")
today = date.today()

# 2CC — Senin (weekday 0)
print("\n  2CC (Senin):")
d = next_wd(today, 0)
for _ in range(8):
    tgl = d.strftime("%Y-%m-%d")
    buat_jadwal(7, tgl, "Praktek Routing dan Switching", "2CC", faris.nama, "07:00", "09:30")
    buat_jadwal(7, tgl, "Praktek Routing dan Switching", "2CC", faris.nama, "10:00", "12:30")
    d += timedelta(weeks=1)
db.commit()

# 2CF — Selasa (weekday 1), blok siang DULU (jam lebih awal)
print("\n  2CF (Selasa siang):")
d = next_wd(today, 1)
for _ in range(8):
    tgl = d.strftime("%Y-%m-%d")
    buat_jadwal(7, tgl, "Praktek Routing dan Switching", "2CF", agus.nama, "12:40", "15:10")
    d += timedelta(weeks=1)
db.commit()

# 2CE — Selasa (weekday 1), blok sore
print("\n  2CE (Selasa sore):")
d = next_wd(today, 1)
for _ in range(8):
    tgl = d.strftime("%Y-%m-%d")
    buat_jadwal(7, tgl, "Praktek Routing dan Switching", "2CE", agus.nama, "15:40", "18:10")
    d += timedelta(weeks=1)
db.commit()

print(f"\n✅ Selesai. ID Perangkat terakhir dipakai: {perangkat_counter - 1}")
print("   Langkah berikutnya:")
print("   1. python seed_lab_sensor.py (sudah selesai)")
print("   2. Buka dashboard → Jadwal → Kelola Mahasiswa per jadwal")
print("      → 'Tambah Cepat Berdasarkan Kelas' (2CC / 2CE / 2CF)")
print("   3. Sync ke device: systemctl restart doorlock-bridge")
db.close()