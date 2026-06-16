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
        ruangan_objs.append(obj)
    
    # Commit once after loop for better performance
    db.commit() 

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

    # Hitung inventaris setelah init
    inventaris_count = db.query(InventarisAlat).count()

    return {
        "status": "berhasil",
        "data": {
            "ruangan":   len(ruangan_objs),
            "users":     len(user_objs),
            "inventaris": inventaris_count
        },
        "akun": [
            {"role": "admin",   "nim_nip": "ADMIN001",             "password": "admin123"},
            {"role": "teknisi", "nim_nip": "TEKNISI001",           "password": "teknisi123"},
            {"role": "dosen",   "nim_nip": "197305162002121001",   "password": "dosen123"},
        ],
        "PENTING": "Segera ganti password setelah login pertama!"
    }


@router.post("/seed-kbm-real")
def seed_kbm_real(key: str, db: Session = Depends(get_db)):
    """Seed data KBM real Lab Multimedia 2 ke production."""
    if not SETUP_KEY or key != SETUP_KEY:
        raise HTTPException(403, "Kunci tidak valid")

    def h(pw): 
        return bcrypt.hashpw(pw.encode(), bcrypt.gensalt()).decode()

    def upsert_user(nim_nip, nama, role, fp_id=None, password=None):
        u = db.query(User).filter(User.nim_nip == nim_nip).first()
        if not u:
            u = User(
                nama=nama, nim_nip=nim_nip, role=role,
                ruangan_id=None, aktif=True, fingerprint_id=fp_id,
                password_hash=h(password) if password else None
            )
            db.add(u); db.flush()
        elif fp_id and not u.fingerprint_id:
            u.fingerprint_id = fp_id
        return u

    def next_wd(d, wd):
        days = (wd - d.weekday()) % 7
        return d + timedelta(days=days)

    def gen_dates(start, wd, n=8):
        dates, d = [], next_wd(start, wd)
        for _ in range(n):
            dates.append(d.strftime("%Y-%m-%d"))
            d += timedelta(weeks=1)
        return dates

    # Ruangan
    ruangan = db.query(Ruangan).filter(
        Ruangan.nama.ilike("%Multimedia 2%")
    ).first()
    if not ruangan:
        raise HTTPException(404, "Ruangan Lab Multimedia 2 tidak ditemukan")

    # Dosen
    chairil = upsert_user("197CHAIRIL01",
        "R. M. Chairil Andri, S.S.T., M.I.T.",
        "dosen", fp_id=5, password="dosen123")
    adi = upsert_user("197ADI01",
        "Adi Sutrisman, S.Kom., M.Kom.",
        "dosen", fp_id=6, password="dosen123")
    db.commit()

    # Mahasiswa 6CC
    data_6cc = [
        ("062330701435","AGUNG DILA UTAMA"),
        ("062330701436","AL-MAN RAFFLI SAPUTRA"),
        ("062330701437","APRILIA DAMAYANTI"),
        ("062330701438","DZIKRY FADILLAH"),
        ("062330701439","FAHREZI ISLAMI PASHA"),
        ("062330701440","FAZA LA AMY"),
        ("062330701441","ILHAM PUTRA PANI"),
        ("062330701442","JERY JULIANSYAH"),
        ("062330701443","M FIQIULUM"),
        ("062330701444","M. ARIF RAHMAN"),
        ("062330701445","M. DZAKY DARMAWAN"),
        ("062330701446","MEILA PUTRI"),
        ("062330701447","MUHAMMAD ABSHORUDDIN"),
        ("062330701448","MUHAMMAD ATHIRA RAMADHAN"),
        ("062330701449","MUHAMMAD REZA PUTRA RAMADHANI"),
        ("062330701450","MUTTIA BELLA MEYSHA"),
        ("062330701451","NADIA SEPTIANA"),
        ("062330701452","NICCO DWI SATRIA"),
        ("062330701453","RIDHO FEBRIAN"),
        ("062330701454","RIZKI ANUGRAH"),
        ("062330701455","SILPI HAIRUNNASA"),
        ("062330701456","TIO SANDIKA"),
        ("062330701457","WINDA MUFIDAH"),
    ]
    users_6cc = [upsert_user(n,nm,"mahasiswa",fp_id=10+i)
                 for i,(n,nm) in enumerate(data_6cc)]

    # Mahasiswa 6CM
    data_6cm = [
        ("062330701530","ADLIN ILHAM"),
        ("062330701531","AMANDA FITRI ZASKIA"),
        ("062330701532","BAGASKARA ADITYA"),
        ("062330701533","FAJAR ALIANSYA"),
        ("062330701534","INTAN MAHDALENA"),
        ("062330701535","M FARIZ YUSUF HABIBIE"),
        ("062330701536","M. AKBAR FADHILAH"),
        ("062330701537","M. RASYID GYMNASTIAR"),
        ("062330701538","M.ETO ATTHOILLAH"),
        ("062330701539","M.WILDAN HABIB"),
        ("062330701540","MUHAMMAD AGAM RAMADHAN"),
        ("062330701541","MUHAMMAD ARROHMAN"),
        ("062330701542","MUHAMMAD FATIH FARHAN"),
        ("062330701543","MUHAMMAD RIZKY ANANDA"),
        ("062330701544","REZA AL GIFFARI"),
        ("062330701545","RIZKY CHAVENESI"),
        ("062330701546","SANJAYA ANDRIAN SYAHPUTRA"),
        ("062330701547","WAHYU GUSTIANSYAH"),
        ("062330701548","YAZID ZINADIN ZIDAN"),
        ("062330701549","ZAKIA PUTRI"),
    ]
    users_6cm = [upsert_user(n,nm,"mahasiswa",fp_id=33+i)
                 for i,(n,nm) in enumerate(data_6cm)]
    db.commit()

    # Jadwal
    today = date.today()
    tgl_6cc = gen_dates(today, 2, 8)  # Rabin
    tgl_6cm = gen_dates(today, 4, 8)  # Jumat

    def buat_jadwal(tgl, kegiatan, kelas, dosen_nama,
                    jam_mulai, jam_selesai, mhs_list):
        ex = db.query(JadwalRuangan).filter(
            JadwalRuangan.ruangan_id == ruangan.id,
            JadwalRuangan.tanggal   == tgl,
            JadwalRuangan.kelas     == kelas
        ).first()
        if ex:
            return ex
        j = JadwalRuangan(
            ruangan_id=ruangan.id, nama_kegiatan=kegiatan,
            kelas=kelas, dosen=dosen_nama, tanggal=tgl,
            jam_mulai=jam_mulai, jam_selesai=jam_selesai
        )
        db.add(j); db.flush()
        for m in mhs_list:
            if m not in j.mahasiswa_diizinkan:
                j.mahasiswa_diizinkan.append(m)
        return j

    j6cc = [buat_jadwal(t,"Praktek Sistem Multimedia","6CC",
                        chairil.nama,"07:00","09:30",users_6cc)
            for t in tgl_6cc]
    j6cm = [buat_jadwal(t,"Praktek Sistem Multimedia","6CM",
                        adi.nama,"18:30","20:30",users_6cm)
            for t in tgl_6cm]
    db.commit()

    return {
        "status": "berhasil",
        "ruangan": ruangan.nama,
        "dosen": 2,
        "mahasiswa": {"6CC": len(users_6cc), "6CM": len(users_6cm)},
        "jadwal": {"6CC": len(j6cc), "6CM": len(j6cm)},
        "fp_ids": {
            "Chairil":  5, "Adi Sutrisman": 6,
            "6CC_range": "10-32", "6CM_range": "33-52"
        },
        "catatan": "Fingerprint ID sudah disiapkan, daftarkan di alat sesuai urutan"
    }

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

@router.get("/status")
def check_status(db: Session = Depends(get_db)):
    return {
        "ruangan":    db.query(Ruangan).count(),
        "users":      db.query(User).count(),
        "inventaris": db.query(InventarisAlat).count(),
        "sudah_init": db.query(Ruangan).count() > 0
    }