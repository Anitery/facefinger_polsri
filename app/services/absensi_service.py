"""
Service untuk mengelola absensi otomatis.
Dipanggil dari:
1. auth.py — saat mahasiswa/dosen berhasil scan → catat hadir/terlambat
2. scheduler — saat jadwal selesai → isi tidak hadir untuk yang belum scan
"""
from sqlalchemy.orm import Session, joinedload
from datetime import datetime, timezone
from app.models.models import Absensi, JadwalRuangan, User


TOLERANSI_MENIT = 15  # menit toleransi terlambat


def tentukan_status(jam_mulai_str: str, waktu_scan: datetime) -> str:
    """
    Tentukan status hadir/terlambat berdasarkan waktu scan
    vs jam mulai jadwal.
    """
    # Parse jam mulai jadwal hari ini
    today = waktu_scan.strftime("%Y-%m-%d")
    jam_mulai = datetime.strptime(
        f"{today} {jam_mulai_str}", "%Y-%m-%d %H:%M"
    )
    # Tambah timezone naive untuk konsistensi
    selisih_menit = (waktu_scan.replace(tzinfo=None) - jam_mulai).total_seconds() / 60

    if selisih_menit <= TOLERANSI_MENIT:
        return "hadir"
    else:
        return "terlambat"


def catat_absensi_masuk(
    db: Session,
    jadwal_id: int,
    user_id: int,
    jam_mulai: str
) -> Absensi:
    """
    Catat kehadiran saat user berhasil scan biometrik.
    Dipanggil dari auth.py.
    """
    # Cek apakah sudah pernah absen di jadwal ini
    existing = db.query(Absensi).filter(
        Absensi.jadwal_id == jadwal_id,
        Absensi.user_id   == user_id,
    ).first()

    waktu_sekarang = datetime.now()
    status = tentukan_status(jam_mulai, waktu_sekarang)

    if existing:
        # Sudah pernah scan — update waktu jika belum hadir
        if existing.status == "tidak_hadir":
            existing.waktu_masuk = waktu_sekarang
            existing.status      = status
            db.commit()
        return existing
    else:
        # Buat record baru
        absensi = Absensi(
            jadwal_id   = jadwal_id,
            user_id     = user_id,
            waktu_masuk = waktu_sekarang,
            status      = status,
        )
        db.add(absensi)
        db.commit()
        db.refresh(absensi)
        return absensi


def tutup_absensi_jadwal(db: Session, jadwal_id: int) -> int:
    """
    Isi 'tidak hadir' untuk mahasiswa terdaftar yang belum scan.
    Dosen TIDAK disertakan (kebijakan: absensi hanya untuk mahasiswa).
    """
    jadwal = db.query(JadwalRuangan).options(
        joinedload(JadwalRuangan.mahasiswa_diizinkan)
    ).filter(JadwalRuangan.id == jadwal_id).first()

    if not jadwal:
        return 0

    sudah_absen_ids = {
        a.user_id for a in db.query(Absensi).filter(
            Absensi.jadwal_id == jadwal_id
        ).all()
    }

    user_ids_wajib = {m.id for m in jadwal.mahasiswa_diizinkan}

    if not user_ids_wajib:
        q_mhs = db.query(User).filter(
            User.role == "mahasiswa", User.aktif == True
        )
        if jadwal.kelas:
            q_mhs = q_mhs.filter(User.kelas == jadwal.kelas)
        user_ids_wajib = {m.id for m in q_mhs.all()}

    # Dosen TIDAK ditambahkan ke user_ids_wajib (dihapus dari versi lama)

    tidak_hadir = user_ids_wajib - sudah_absen_ids
    count = 0
    for uid in tidak_hadir:
        db.add(Absensi(
            jadwal_id   = jadwal_id,
            user_id     = uid,
            waktu_masuk = None,
            status      = "tidak_hadir",
        ))
        count += 1

    db.commit()
    return count


def get_rekap_jadwal(db: Session, jadwal_id: int) -> dict:
    """Ambil rekap absensi untuk satu jadwal."""
    jadwal = db.query(JadwalRuangan).filter(
        JadwalRuangan.id == jadwal_id
    ).first()
    if not jadwal:
        return {}

    absensi_list = db.query(Absensi).options(
        joinedload(Absensi.user)
    ).filter(Absensi.jadwal_id == jadwal_id).all()

    return {
        "jadwal_id":    jadwal_id,
        "nama_kegiatan": jadwal.nama_kegiatan,
        "kelas":        jadwal.kelas,
        "tanggal":      jadwal.tanggal,
        "jam_mulai":    jadwal.jam_mulai,
        "jam_selesai":  jadwal.jam_selesai,
        "dosen":        jadwal.dosen,
        "total":        len(absensi_list),
        "hadir":        sum(1 for a in absensi_list if a.status == "hadir"),
        "terlambat":    sum(1 for a in absensi_list if a.status == "terlambat"),
        "tidak_hadir":  sum(1 for a in absensi_list if a.status == "tidak_hadir"),
        "izin":         sum(1 for a in absensi_list if a.status == "izin"),
        "detail": [
            {
                "absensi_id":  a.id,           # ← TAMBAH INI
                "user_id":     a.user_id,
                "nama":        a.user.nama    if a.user else "—",
                "nim_nip":     a.user.nim_nip if a.user else "—",
                "role":        a.user.role    if a.user else "—",
                "status":      a.status,
                "waktu_masuk": a.waktu_masuk.strftime("%H:%M:%S")
                            if a.waktu_masuk else "—",
                "keterangan":  a.keterangan or "",
            }
            for a in sorted(absensi_list, key=lambda x: (
                x.status, x.user.nama if x.user else ""
            ))
        ]
    }