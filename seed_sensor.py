"""
Seed data Lab Sensor & Wireless (ruangan_id=7)
Kelas 2CC (Senin), 2CE (Selasa), 2CF (Selasa)
Mahasiswa BELUM dimasukkan — data NIM diambil menyusul.
Jalankan: python seed_lab_sensor.py
"""
from datetime import date, timedelta
from app.database import SessionLocal
from app.models.models import User, Ruangan, JadwalRuangan
import bcrypt

db = SessionLocal()

def h(pw): return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()

def upsert_dosen(nim_nip, nama, fp_id):
    u = db.query(User).filter(User.nim_nip == nim_nip).first()
    if not u:
        u = User(
            nama=nama, nim_nip=nim_nip, role="dosen",
            fingerprint_id=fp_id, aktif=True,
            password_hash=h("dosen123"),
        )
        db.add(u)
        db.flush()
        print(f"  + Dosen: {nama} (FP:{fp_id})")
    return u

def next_wd(d: date, wd: int) -> date:
    return d + timedelta(days=(wd - d.weekday()) % 7)

def gen_dates(start: date, wd: int, n: int = 8) -> list:
    dates, d = [], next_wd(start, wd)
    for _ in range(n):
        dates.append(d.strftime("%Y-%m-%d"))
        d += timedelta(weeks=1)
    return dates

def buat_jadwal(ruangan_id, tgl, kegiatan, kelas, dosen_nama, jm, js):
    existing = db.query(JadwalRuangan).filter(
        JadwalRuangan.ruangan_id == ruangan_id,
        JadwalRuangan.tanggal   == tgl,
        JadwalRuangan.kelas     == kelas,
        JadwalRuangan.jam_mulai == jm,
    ).first()
    if existing:
        print(f"  ~ {kelas} {tgl} {jm} — sudah ada")
        return existing
    j = JadwalRuangan(
        ruangan_id=ruangan_id, nama_kegiatan=kegiatan, kelas=kelas,
        dosen=dosen_nama, tanggal=tgl, jam_mulai=jm, jam_selesai=js,
        is_active=True,
    )
    db.add(j)
    print(f"  + {kelas} | {tgl} | {jm}-{js}")
    return j

# ── Verifikasi ruangan ───────────────────────────────────
ruangan = db.query(Ruangan).filter(Ruangan.id == 7).first()
if not ruangan:
    print("❌ Ruangan id=7 tidak ditemukan!"); db.close(); exit(1)
print(f"✓ Ruangan: {ruangan.nama} (id={ruangan.id})")

# ── Dosen ────────────────────────────────────────────────
print("\n── Dosen ──")
faris = upsert_dosen("197FARIS01", "Faris Humam, M.Kom.", fp_id=7)
agus  = upsert_dosen("197AGUS01",  "Muhammad Agus Triawan, M.T.", fp_id=8)
db.commit()

today = date.today()

# ── 2CC — Senin, 2 blok (07:00-09:30 & 10:00-12:30) ────────
print("\n── Jadwal 2CC (Senin) ──")
for tgl in gen_dates(today, 0, 8):  # 0 = Senin
    buat_jadwal(7, tgl, "Praktek Routing dan Switching", "2CC",
                faris.nama, "07:00", "09:30")
    buat_jadwal(7, tgl, "Praktek Routing dan Switching", "2CC",
                faris.nama, "10:00", "12:30")
db.commit()

# ── 2CF — Selasa, 12:40-15:10 ────────────────────────────
print("\n── Jadwal 2CF (Selasa) ──")
for tgl in gen_dates(today, 1, 8):  # 1 = Selasa
    buat_jadwal(7, tgl, "Praktek Routing dan Switching", "2CF",
                agus.nama, "12:40", "15:10")
db.commit()

# ── 2CE — Selasa, 15:40-18:10 ─────────────────────────────
print("\n── Jadwal 2CE (Selasa) ──")
for tgl in gen_dates(today, 1, 8):
    buat_jadwal(7, tgl, "Praktek Routing dan Switching", "2CE",
                agus.nama, "15:40", "18:10")
db.commit()

print("\n✅ Selesai. Mahasiswa BELUM ditambahkan — gunakan fitur")
print("   'Tambah Cepat Berdasarkan Kelas' di dashboard setelah data NIM siap.")
db.close()