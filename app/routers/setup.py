from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Ruangan, User, InventarisAlat, JadwalRuangan
import bcrypt
import os
from datetime import date, timedelta

router = APIRouter(prefix="/setup", tags=["Setup"])

SETUP_KEY = os.getenv("SETUP_KEY", "")


def hash_pw(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


# ══════════════════════════════════════════════════════════════
# INIT — Inisialisasi database pertama kali
# ══════════════════════════════════════════════════════════════

@router.post("/init")
def init_database(key: str, db: Session = Depends(get_db)):
    """
    Inisialisasi database: 13 ruangan, akun default admin/teknisi/dosen.
    Hanya bisa dijalankan satu kali (cek apakah DB sudah berisi data).
    """
    if not SETUP_KEY or key != SETUP_KEY:
        raise HTTPException(status_code=403, detail="Kunci tidak valid")

    if db.query(Ruangan).first():
        raise HTTPException(
            status_code=400,
            detail="Database sudah berisi data. Gunakan endpoint lain untuk update."
        )

    # ── 13 Ruangan Jurusan Teknik Komputer ────────────────────
    # id=7  → Lab Sensor & Wireless (fokus TA)
    # id=13 → Ruang Ketua Lab (server rack + inventaris)
    ruangan_list = [
        {"nama": "Lab Pemrograman 1",                  "lokasi": "Lantai 1", "lantai": 1},  # id=1
        {"nama": "Lab Pemrograman 2",                  "lokasi": "Lantai 1", "lantai": 1},  # id=2
        {"nama": "Lab Pemrograman 3",                  "lokasi": "Lantai 1", "lantai": 1},  # id=3
        {"nama": "Lab Pemrograman 4",                  "lokasi": "Lantai 1", "lantai": 1},  # id=4
        {"nama": "Lab Multimedia",                     "lokasi": "Lantai 2", "lantai": 2},  # id=5
        {"nama": "Lab Multimedia 2",                   "lokasi": "Lantai 2", "lantai": 2},  # id=6
        {"nama": "Lab Sensor & Wireless",              "lokasi": "Lantai 2", "lantai": 2},  # id=7  ← FOKUS TA
        {"nama": "Lab Video & Audio",                  "lokasi": "Lantai 2", "lantai": 2},  # id=8
        {"nama": "Lab Keamanan & Jaringan",            "lokasi": "Lantai 3", "lantai": 3},  # id=9
        {"nama": "Lab Infrastruktur & Komputasi Awan", "lokasi": "Lantai 3", "lantai": 3},  # id=10
        {"nama": "Lab Elektronika & Sistem Kendali",   "lokasi": "Lantai 1", "lantai": 1},  # id=11
        {"nama": "Perpustakaan Tekkom",                "lokasi": "Lantai 1", "lantai": 1},  # id=12
        {"nama": "Ruang Ketua Lab",                    "lokasi": "Lantai 2", "lantai": 2},  # id=13 ← SERVER RACK
    ]

    ruangan_objs = []
    for r in ruangan_list:
        obj = Ruangan(**r)
        db.add(obj)
        ruangan_objs.append(obj)
    db.commit()

    # ── Akun default ──────────────────────────────────────────
    users_data = [
        {
            "nama": "Administrator", "nim_nip": "ADMIN001",
            "role": "admin", "fingerprint_id": 1, "password": "admin123"
        },
        {
            "nama": "Teknisi Lab", "nim_nip": "TEKNISI001",
            "role": "teknisi", "fingerprint_id": 2, "password": "teknisi123"
        },
        {
            "nama": "Dosen", "nim_nip": "DOSEN001",
            "role": "dosen", "fingerprint_id": 3, "password": "dosen123"
        },
        {
            "nama": "Fatah Alfi Syahri",
            "nim_nip": "062330701514",
            "role": "mahasiswa", "fingerprint_id": 4, "password": None,
            "kelas": "6CF"
        },
    ]

    user_objs = []
    for u in users_data:
        pw    = u.pop("password")
        kelas = u.pop("kelas", None)
        obj   = User(
            **u,
            kelas=kelas,
            ruangan_id=None,
            password_hash=hash_pw(pw) if pw else None
        )
        db.add(obj)
        user_objs.append(obj)
    db.commit()

    return {
        "status": "berhasil",
        "data": {
            "ruangan": len(ruangan_objs),
            "users":   len(user_objs),
        },
        "akun": [
            {"role": "admin",     "nim_nip": "ADMIN001",           "password": "admin123"},
            {"role": "teknisi",   "nim_nip": "TEKNISI001",         "password": "teknisi123"},
            {"role": "dosen",     "nim_nip": "197305162002121001", "password": "dosen123"},
            {"role": "mahasiswa", "nim_nip": "062330701514",       "password": "(tidak ada)"},
        ],
        "PENTING": "Segera ganti password setelah login pertama!"
    }


# ══════════════════════════════════════════════════════════════
# SEED LAB SENSOR & WIRELESS — Data TA Final
# ══════════════════════════════════════════════════════════════

@router.post("/seed-lab-sensor-final")
def seed_lab_sensor_final(key: str, db: Session = Depends(get_db)):
    """
    Seed data final TA:
    - Seluruh staf (dosen + teknisi) Jurusan Teknik Komputer
    - Mahasiswa 2CC, 2CE, 2CF + mahasiswa tambahan TA
    - Jadwal KBM 8 minggu ke depan untuk Lab Sensor & Wireless (id=7)
    """
    if not SETUP_KEY or key != SETUP_KEY:
        raise HTTPException(403, "Kunci tidak valid")

    from datetime import date, timedelta

    def h(pw): return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()

    def upsert_user(nama, nim_nip, role, kelas=None, fp_id=None, password="polsri123"):
        u = db.query(User).filter(User.nim_nip == nim_nip).first()
        if not u:
            u = User(
                nama=nama, nim_nip=nim_nip, role=role,
                kelas=kelas, fingerprint_id=fp_id,
                aktif=True,
                password_hash=h(password) if role != "mahasiswa" else None
            )
            db.add(u)
            db.flush()
        else:
            # Update data yang mungkin berubah
            u.kelas = kelas
            u.aktif = True
            if fp_id and not u.fingerprint_id:
                u.fingerprint_id = fp_id
        return u

    def next_wd(start: date, wd: int) -> date:
        """Maju ke hari pertama dengan weekday wd (0=Sen,…,6=Min)."""
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
            return  # skip duplikat
        db.add(JadwalRuangan(
            ruangan_id=ruangan_id, nama_kegiatan=kegiatan,
            kelas=kelas, dosen=dosen_nama,
            tanggal=tgl, jam_mulai=jm, jam_selesai=js,
            is_active=True,
        ))

    # ── Verifikasi Ruangan ─────────────────────────────────────
    ruangan = db.query(Ruangan).filter(Ruangan.id == 7).first()
    if not ruangan:
        raise HTTPException(404, "Ruangan id=7 (Lab Sensor & Wireless) tidak ditemukan. "
                                 "Jalankan /setup/init terlebih dahulu.")

    # ── Staf Jurusan Teknik Komputer ──────────────────────────
    # FP ID 1–4 sudah dipakai (admin, teknisi default, Slamet, Fatah)
    # FP ID 5–17 untuk staf tambahan
    STAF = [
        # (nim_nip, nama, role, fp_id)
        ("197305162002121001", "Dr. Slamet Widodo, S.Kom., M.Kom.",
         "dosen", 5),   # Ketua Jurusan
        ("197010112001121001", "Ali Firdaus, M. Kom.",
         "dosen", 6),   # Ka. Lab Pemrograman
        ("197307062005011003", "Indarto, S.T., M.Cs.",
         "dosen", 7),   # Ka. Lab Jaringan
        ("198103182008121002", "Herlambang Saputra, M.Kom, Ph.D",
         "dosen", 8),   # Ka. Lab Elektronika
        ("198907122019031012", "Ariansyah Saputra, S.Kom. M.Kom",
         "dosen", 9),   # Ka. Lab Multimedia
        ("197807212008101001", "Iwan setiawan, S.T.",
         "teknisi", 10),
        ("199009152010121001", "Muhammad Wahyudi, S.Kom.",
         "teknisi", 11),
        ("198501082019031007", "Willy Andre, S.Kom.",
         "teknisi", 12),
        ("197611082000031002",
         "Dr. Ir. Alan Novi Tompunu, S.T., M.T., IPM., ASEAN Eng., APEC Eng",
         "dosen", 13),
        ("199105052022031006", "Faris Humam, M.Kom.",
         "dosen", 14),  # Pengajar 2CC
        ("199008122022031004", "Muhammad Agus Triawan, M.T.",
         "dosen", 15),  # Pengajar 2CE & 2CF
    ]
    staf_objs = {}
    for nim, nama, role, fp in STAF:
        obj = upsert_user(nama, nim, role, fp_id=fp, password="polsri123")
        staf_objs[nim] = obj
    db.commit()

    faris = staf_objs["199105052022031006"]
    agus  = staf_objs["199008122022031004"]

    # ── Mahasiswa 2CC ─────────────────────────────────────────
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

    # ── Mahasiswa 2CE ─────────────────────────────────────────
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

    # ── Mahasiswa 2CF ─────────────────────────────────────────
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

    # FP ID mahasiswa mulai dari 20
    fp_counter = 20
    mhs_count  = {"2CC": 0, "2CE": 0, "2CF": 0}

    for nim, nama in DATA_2CC:
        upsert_user(nama, nim, "mahasiswa", kelas="2CC", fp_id=fp_counter)
        fp_counter += 1
        mhs_count["2CC"] += 1

    for nim, nama in DATA_2CE:
        upsert_user(nama, nim, "mahasiswa", kelas="2CE", fp_id=fp_counter)
        fp_counter += 1
        mhs_count["2CE"] += 1

    for nim, nama in DATA_2CF:
        upsert_user(nama, nim, "mahasiswa", kelas="2CF", fp_id=fp_counter)
        fp_counter += 1
        mhs_count["2CF"] += 1

    db.commit()

    # ── Mahasiswa Tambahan TA ─────────────────────────────────
    TAMBAHAN = [
        ("062330701452", "Nicco Dwi Satria",          "6CC"),
        ("062330701511", "Avip Kurniawan Harahap",    "6CF"),
        ("062330701517", "M. Andriano Alfarazy",      "6CF"),
        ("062330701521", "Muhammad Eqsha Azmiansyah", "6CF"),
    ]
    for nim, nama, kelas in TAMBAHAN:
        upsert_user(nama, nim, "mahasiswa", kelas=kelas, fp_id=fp_counter)
        fp_counter += 1

    # Fatah — update kelas saja, jangan timpa FP ID yang sudah ada di device
    u_fatah = db.query(User).filter(User.nim_nip == "062330701514").first()
    if u_fatah:
        u_fatah.kelas = "6CF"

    db.commit()

    # ── Jadwal KBM — 8 minggu ke depan ───────────────────────
    today    = date.today()
    tgl_sen  = next_wd(today, 0)   # Senin  untuk 2CC
    tgl_sel  = next_wd(today, 1)   # Selasa untuk 2CF dan 2CE
    jadwal_count = 0

    for _ in range(8):
        sen_str = tgl_sen.strftime("%Y-%m-%d")
        # 2CC — Senin, dua blok
        buat_jadwal(7, sen_str, "Praktek Routing dan Switching",
                    "2CC", faris.nama, "07:00", "09:30")
        buat_jadwal(7, sen_str, "Praktek Routing dan Switching",
                    "2CC", faris.nama, "10:00", "12:30")
        tgl_sen   += timedelta(weeks=1)
        jadwal_count += 2

        sel_str = tgl_sel.strftime("%Y-%m-%d")
        # 2CF — Selasa siang
        buat_jadwal(7, sel_str, "Praktek Routing dan Switching",
                    "2CF", agus.nama, "12:40", "15:10")
        # 2CE — Selasa sore
        buat_jadwal(7, sel_str, "Praktek Routing dan Switching",
                    "2CE", agus.nama, "15:40", "18:10")
        tgl_sel   += timedelta(weeks=1)
        jadwal_count += 2

    db.commit()

    return {
        "status":  "berhasil",
        "ruangan": ruangan.nama,
        "staf":    len(STAF),
        "mahasiswa": {
            "2CC": mhs_count["2CC"],
            "2CE": mhs_count["2CE"],
            "2CF": mhs_count["2CF"],
            "tambahan_TA": len(TAMBAHAN) + 1,  # +1 untuk Fatah
        },
        "jadwal_dibuat": jadwal_count,
        "fp_terakhir":   fp_counter - 1,
        "langkah_berikut": [
            "1. Buka Dashboard → Jadwal → pilih Lab Sensor & Wireless",
            "2. Per jadwal → Kelola Mahasiswa → Tambah Cepat Berdasarkan Kelas",
            "3. Restart bridge: systemctl restart doorlock-bridge",
        ]
    }


# ══════════════════════════════════════════════════════════════
# SEED INVENTARIS — Ruang Ketua Lab (id=13)
# ══════════════════════════════════════════════════════════════

@router.post("/seed-inventaris-ketua-lab")
def seed_inventaris_ketua_lab(key: str, db: Session = Depends(get_db)):
    """
    Seed data inventaris awal untuk Ruang Ketua Lab (id=13).
    Berisi peralatan server rack dan infrastruktur jaringan kampus.
    """
    if not SETUP_KEY or key != SETUP_KEY:
        raise HTTPException(403, "Kunci tidak valid")

    ruangan = db.query(Ruangan).filter(Ruangan.id == 13).first()
    if not ruangan:
        raise HTTPException(404, "Ruangan id=13 (Ruang Ketua Lab) tidak ditemukan. "
                                 "Jalankan /setup/init terlebih dahulu.")

    INVENTARIS = [
        {"kode_barcode": "RKTL-SRV-001", "nama_alat": "Server Rack 12U",
         "jumlah": 1, "keterangan": "Rack server utama sistem Smart Door Lock"},
        {"kode_barcode": "RKTL-SRV-002", "nama_alat": "Server Debian Linux",
         "jumlah": 1, "keterangan": "Server hosting FastAPI + PostgreSQL"},
        {"kode_barcode": "RKTL-NET-001", "nama_alat": "Managed Switch 24 Port",
         "jumlah": 1, "keterangan": "Switch jaringan utama jurusan"},
        {"kode_barcode": "RKTL-NET-002", "nama_alat": "Router MikroTik",
         "jumlah": 1, "keterangan": "Router distribusi jaringan laboratorium"},
        {"kode_barcode": "RKTL-UPS-001", "nama_alat": "UPS Server 1500VA",
         "jumlah": 1, "keterangan": "Backup power untuk server rack"},
        {"kode_barcode": "RKTL-KBL-001", "nama_alat": "Kabel UTP Cat6 (Box 305m)",
         "jumlah": 2, "keterangan": "Kabel jaringan cadangan"},
        {"kode_barcode": "RKTL-KBL-002", "nama_alat": "Patch Panel 24 Port",
         "jumlah": 1, "keterangan": "Patch panel manajemen kabel"},
        {"kode_barcode": "RKTL-STB-001", "nama_alat": "STB HG680P (Bridge Device)",
         "jumlah": 1, "keterangan": "Bridge SOAP-REST untuk X606-S Lab Sensor & Wireless"},
    ]

    added = 0
    for item in INVENTARIS:
        ex = db.query(InventarisAlat).filter(
            InventarisAlat.kode_barcode == item["kode_barcode"]
        ).first()
        if not ex:
            db.add(InventarisAlat(
                **item,
                ruangan_id=13,
                status="baik"
            ))
            added += 1

    db.commit()

    return {
        "status":  "berhasil",
        "ruangan": ruangan.nama,
        "inventaris_ditambahkan": added,
        "total_inventaris": db.query(InventarisAlat)
                              .filter(InventarisAlat.ruangan_id == 13)
                              .count(),
    }


# ══════════════════════════════════════════════════════════════
# MIGRASI KOLOM — Sekali Pakai
# ══════════════════════════════════════════════════════════════

@router.post("/add-kelas-column")
def add_kelas_column(key: str, db: Session = Depends(get_db)):
    """Tambahkan kolom kelas ke tabel users (jika belum ada)."""
    if not SETUP_KEY or key != SETUP_KEY:
        raise HTTPException(403, "Kunci tidak valid")
    from sqlalchemy import text
    try:
        db.execute(text(
            "ALTER TABLE users ADD COLUMN IF NOT EXISTS kelas VARCHAR(50)"
        ))
        db.commit()
        return {"status": "berhasil", "pesan": "Kolom kelas berhasil ditambahkan"}
    except Exception as e:
        db.rollback()
        return {"status": "gagal", "pesan": str(e)}


@router.post("/add-jadwal-active-column")
def add_jadwal_active_column(key: str, db: Session = Depends(get_db)):
    """Tambahkan kolom is_active ke tabel jadwal_ruangan (jika belum ada)."""
    if not SETUP_KEY or key != SETUP_KEY:
        raise HTTPException(403, "Kunci tidak valid")
    from sqlalchemy import text
    try:
        db.execute(text(
            "ALTER TABLE jadwal_ruangan "
            "ADD COLUMN IF NOT EXISTS is_active BOOLEAN DEFAULT TRUE"
        ))
        db.commit()
        return {"status": "berhasil"}
    except Exception as e:
        db.rollback()
        return {"status": "gagal", "pesan": str(e)}


@router.post("/migrate-heartbeat")
def migrate_heartbeat(key: str, db: Session = Depends(get_db)):
    """Tambahkan kolom yang mungkin belum ada di tabel bridge_heartbeat."""
    if not SETUP_KEY or key != SETUP_KEY:
        raise HTTPException(403, "Kunci tidak valid")
    from sqlalchemy import text
    kolom = [
        ("device_sn",   "VARCHAR(50)"),
        ("device_ip",   "VARCHAR(50)"),
        ("device_time", "VARCHAR(30)"),
        ("total_user",  "INTEGER"),
        ("extra_info",  "TEXT"),
    ]
    hasil = []
    for nama, tipe in kolom:
        try:
            db.execute(text(
                f"ALTER TABLE bridge_heartbeat "
                f"ADD COLUMN IF NOT EXISTS {nama} {tipe}"
            ))
            hasil.append(f"✓ {nama}")
        except Exception as e:
            hasil.append(f"✗ {nama}: {e}")
    db.commit()
    return {"hasil": hasil}


@router.post("/cleanup-old-tables")
def cleanup_old_tables(key: str, db: Session = Depends(get_db)):
    """Hapus tabel sisa arsitektur X606 generasi lama. Sekali pakai."""
    if not SETUP_KEY or key != SETUP_KEY:
        raise HTTPException(403, "Kunci tidak valid")
    from sqlalchemy import text
    tabel_dihapus = [
        "absensi_x606",
        "x606_jadwal_peserta",
        "x606_user_cache",
        "x606_jadwal_kbm",
        "x606_devices",
    ]
    hasil = []
    for tabel in tabel_dihapus:
        try:
            db.execute(text(f"DROP TABLE IF EXISTS {tabel} CASCADE"))
            db.commit()
            hasil.append({"tabel": tabel, "status": "dihapus"})
        except Exception as e:
            db.rollback()
            hasil.append({"tabel": tabel, "status": f"gagal: {e}"})
    return {"status": "selesai", "detail": hasil}


# ══════════════════════════════════════════════════════════════
# STATUS — Cek kondisi database
# ══════════════════════════════════════════════════════════════

@router.get("/status")
def check_status(db: Session = Depends(get_db)):
    """Cek jumlah data di tiap tabel utama."""
    ruangan_aktif = db.query(Ruangan).filter(Ruangan.aktif == True).count()
    return {
        "ruangan_total":  db.query(Ruangan).count(),
        "ruangan_aktif":  ruangan_aktif,
        "users_total":    db.query(User).count(),
        "users_aktif":    db.query(User).filter(User.aktif == True).count(),
        "inventaris":     db.query(InventarisAlat).count(),
        "jadwal":         db.query(JadwalRuangan).count(),
        "sudah_init":     db.query(Ruangan).count() > 0,
        "ruang_ketua_lab": {
            "id": 13,
            "inventaris": db.query(InventarisAlat)
                           .filter(InventarisAlat.ruangan_id == 13).count()
        }
    }