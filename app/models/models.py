from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Float, ForeignKey, Table
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base

# ── Tabel Relasi Many-to-Many ───────────────────────────────────────────

# Relasi: Ruangan ↔ Penanggung Jawab (User)
penanggung_jawab = Table(
    "penanggung_jawab",
    Base.metadata,
    Column("ruangan_id", Integer, ForeignKey("ruangan.id"), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
)

# Relasi: Jadwal Ruangan ↔ Mahasiswa (User) yang Diizinkan
jadwal_mahasiswa = Table(
    "jadwal_mahasiswa",
    Base.metadata,
    Column("jadwal_id", Integer, ForeignKey("jadwal_ruangan.id"), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
)


# ── Model Tabel ─────────────────────────────────────────────────────────

class Ruangan(Base):
    __tablename__ = "ruangan"

    id = Column(Integer, primary_key=True, index=True)
    nama = Column(String(100), nullable=False)
    lokasi = Column(String(100))
    lantai = Column(Integer)
    aktif = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relasi standard
    users = relationship("User", back_populates="ruangan")
    access_logs = relationship("AccessLog", back_populates="ruangan")
    rekaman_kamera = relationship("RekamanKamera", back_populates="ruangan")
    inventaris = relationship("InventarisAlat", back_populates="ruangan")
    
    # Hubungan dua arah dengan JadwalRuangan menggunakan back_populates
    jadwal = relationship("JadwalRuangan", back_populates="ruangan")

    # Relasi many-to-many penanggung jawab
    penanggung_jawab = relationship(
        "User",
        secondary="penanggung_jawab",
        backref="ruangan_tanggung_jawab"
    )


class User(Base):
    __tablename__ = "users"

    id            = Column(Integer, primary_key=True, index=True)
    nama          = Column(String(100), nullable=False)
    nim_nip       = Column(String(30),  unique=True, index=True)
    kelas         = Column(String(50),  nullable=True)  # khusus mahasiswa (contoh: "6CC")
    role          = Column(String(20),  default="mahasiswa")
    password_hash = Column(String(255), nullable=True)
    
    # Digunakan sebagai PIN di perangkat X606-S saat sinkronisasi SOAP
    # Nilai ini = User ID (PIN) yang didaftarkan ke device
    id_perangkat  = Column(Integer, nullable=True)   # ← GANTI NAMA dari fingerprint_id
    
    # face_encoding DIHAPUS — enrollment wajah dilakukan langsung di device X606-S
    # Tidak disimpan di server (sesuai arsitektur on-device Face VX7.0)
    
    ruangan_id    = Column(Integer, ForeignKey("ruangan.id"), nullable=True)
    aktif         = Column(Boolean, default=True)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())

    ruangan = relationship("Ruangan", back_populates="users")
    access_logs = relationship("AccessLog", back_populates="user")
    # Relasi many-to-many penanggung jawab otomatis via backref="ruangan_tanggung_jawab"
    # Relasi jadwal otomatis via backref="jadwal_diizinkan"


class AccessLog(Base):
    __tablename__ = "access_log"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    ruangan_id = Column(Integer, ForeignKey("ruangan.id"), nullable=False)
    waktu_akses = Column(DateTime(timezone=True), server_default=func.now())
    metode = Column(String(20))  # face / fingerprint / card / pin
    foto_url = Column(Text, nullable=True)
    status = Column(String(10))  # berhasil / ditolak
    keterangan = Column(String(200), nullable=True)

    user = relationship("User", back_populates="access_logs")
    ruangan = relationship("Ruangan", back_populates="access_logs")


class RekamanKamera(Base):
    __tablename__ = "rekaman_kamera"

    id = Column(Integer, primary_key=True, index=True)
    ruangan_id = Column(Integer, ForeignKey("ruangan.id"), nullable=False)
    nama_file = Column(String(100))
    waktu_mulai = Column(DateTime(timezone=True))
    waktu_selesai = Column(DateTime(timezone=True), nullable=True)
    url_video = Column(Text, nullable=True)
    thumbnail_url = Column(Text, nullable=True)
    ukuran_mb = Column(Float, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    ruangan = relationship("Ruangan", back_populates="rekaman_kamera")


class InventarisAlat(Base):
    __tablename__ = "inventaris_alat"

    id = Column(Integer, primary_key=True, index=True)
    ruangan_id = Column(Integer, ForeignKey("ruangan.id"), nullable=False)
    kode_barcode = Column(String(50), unique=True, index=True)
    nama_alat = Column(String(100), nullable=False)
    jumlah = Column(Integer, default=1)
    status = Column(String(20), default="tersedia")  # tersedia/dipinjam/rusak
    keterangan = Column(Text, nullable=True)
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    ruangan = relationship("Ruangan", back_populates="inventaris")


class JadwalRuangan(Base):
    __tablename__ = "jadwal_ruangan"

    id             = Column(Integer, primary_key=True, index=True)
    ruangan_id     = Column(Integer, ForeignKey("ruangan.id"), nullable=False)
    nama_kegiatan  = Column(String(150), nullable=False)
    kelas          = Column(String(50),  nullable=True)
    dosen          = Column(String(100), nullable=True)
    mata_kuliah    = Column(String(100), nullable=True)
    tanggal        = Column(String(20),  nullable=False)
    jam_mulai      = Column(String(10),  nullable=False)
    jam_selesai    = Column(String(10),  nullable=False)
    keterangan     = Column(Text,        nullable=True)
    is_active      = Column(Boolean, default=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    # PERBAIKAN: Diubah dari backref="jadwal" menjadi back_populates="jadwal"
    ruangan = relationship("Ruangan", back_populates="jadwal")
    
    mahasiswa_diizinkan = relationship(
        "User", secondary="jadwal_mahasiswa", backref="jadwal_diizinkan"
    )


class Absensi(Base):
    __tablename__ = "absensi"

    id          = Column(Integer, primary_key=True, index=True)
    jadwal_id   = Column(Integer, ForeignKey("jadwal_ruangan.id"), nullable=False)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=False)
    waktu_masuk = Column(DateTime(timezone=True), nullable=True)
    status      = Column(String(20), nullable=False)  # hadir / tidak hadir / terlambat
    keterangan  = Column(Text, nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    jadwal = relationship("JadwalRuangan", backref="absensi_list")
    user   = relationship("User", backref="absensi_list")


class BridgeHeartbeat(Base):
    __tablename__ = "bridge_heartbeat"
    id         = Column(Integer, primary_key=True)
    ruangan_id = Column(Integer, ForeignKey("ruangan.id"))
    device_sn  = Column(String(50),  nullable=True)  
    device_ip  = Column(String(50),  nullable=True)
    device_time= Column(String(30),  nullable=True)  
    last_seen  = Column(DateTime,    nullable=True)
    total_user = Column(Integer,     nullable=True)
    extra_info = Column(Text,        nullable=True)


class BiometricTemplate(Base):
    """
    Template fingerprint user, diambil SEKALI dari device tempat dia
    pertama enroll, disimpan di sini supaya bisa diduplikasi ke device
    lain tanpa perlu registrasi ulang.

    Mekanisme akses: user hanya bisa akses di ruangan yang device-nya
    PUNYA data user itu (di-push saat user MULAI punya jadwal di sana,
    dihapus saat jadwal berakhir/tidak ada lagi) — jadi TIDAK bergantung
    pada Group/TimeZone device yang terbukti tidak reliable.
    """
    __tablename__ = "biometric_template"

    id         = Column(Integer, primary_key=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    finger_id  = Column(Integer, nullable=False)   # 0-9, jari mana yang didaftarkan
    size       = Column(String(20), nullable=True)
    template   = Column(Text, nullable=False)       # data template (string panjang)
    valid      = Column(String(5), default="1")
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    user = relationship("User")


class UserDeviceSync(Base):
    """
    Status sinkronisasi user per device — melacak device mana saja yang
    SAAT INI punya data user ini di memorinya (hasil push/delete
    otomatis berdasar jadwal). Dipakai sync job untuk tahu perlu
    push/delete apa saja tanpa harus query ulang device tiap kali.
    """
    __tablename__ = "user_device_sync"

    id         = Column(Integer, primary_key=True)
    user_id    = Column(Integer, ForeignKey("users.id"), nullable=False)
    ruangan_id = Column(Integer, ForeignKey("ruangan.id"), nullable=False)
    status     = Column(String(20), default="pending")  # pending / synced / removed / gagal
    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    user    = relationship("User")
    ruangan = relationship("Ruangan")


class PengaturanSistem(Base):
    """
    Pengaturan sistem global — single-row table (selalu id=1).
    Dibaca oleh device_bridge.py saat memvalidasi akses biometrik,
    dan oleh dashboard status perangkat untuk menentukan apa yang
    ditampilkan ke pengguna.
    """
    __tablename__ = "pengaturan_sistem"

    id = Column(Integer, primary_key=True, default=1)

    # a. Wajib jadwal aktif untuk validasi akses. Kalau False, semua
    #    scan biometrik langsung "berhasil" tanpa cek jadwal KBM.
    wajib_jadwal = Column(Boolean, default=True, nullable=False)

    # b. Sembunyikan IP address perangkat di dashboard (untuk role
    #    selain admin/teknisi — mereka tetap lihat IP asli untuk troubleshooting).
    sembunyikan_ip = Column(Boolean, default=False, nullable=False)

    # c. Mode pemeliharaan — semua akses ditolak KECUALI admin/teknisi,
    #    supaya mereka tetap bisa masuk untuk perbaikan.
    mode_pemeliharaan = Column(Boolean, default=False, nullable=False)

    # d. Toleransi keterlambatan presensi (menit) sebelum status
    #    berubah dari "hadir" jadi "terlambat". Sebelumnya di-hardcode 15.
    toleransi_keterlambatan_menit = Column(Integer, default=15, nullable=False)

    updated_at = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())


# ═══════════════════════════════════════════════════════════════════════
# ── Modul Inventaris Gudang ──────────────────────────────────────────────
# Diadaptasi dari project "inventaris-lab" (Laravel) milik rekan satu
# kelompok TA — device X606-S yang sama, ruangan Gudang.
# Sengaja terpisah dari InventarisAlat (quick-scan per ruangan) di atas,
# karena tujuannya beda: modul ini untuk manajemen aset lintas
# lantai/ruangan dengan alur peminjaman & pengembalian formal.
# Pengguna memakai tabel `users` yang sudah ada (bukan tabel terpisah),
# supaya satu akun & satu database untuk seluruh sistem.
# ═══════════════════════════════════════════════════════════════════════

class KategoriBarang(Base):
    __tablename__ = "kategori_barang"

    id            = Column(Integer, primary_key=True, index=True)
    nama_kategori = Column(String(100), nullable=False)
    jenis         = Column(String(50), nullable=True)  # contoh: elektronik, furnitur, dst
    created_at    = Column(DateTime(timezone=True), server_default=func.now())

    barang = relationship("Barang", back_populates="kategori")


class Barang(Base):
    __tablename__ = "barang_gudang"

    id               = Column(Integer, primary_key=True, index=True)
    id_kategori      = Column(Integer, ForeignKey("kategori_barang.id"), nullable=True)
    kode_barang      = Column(String(50), unique=True, index=True, nullable=False)
    nup              = Column(String(20), nullable=True)  # Nomor Urut Pendaftaran (aset BMN)
    sumber_kode      = Column(String(20), default="manual")  # barcode / manual
    nama_barang      = Column(String(100), nullable=False)
    merk_type        = Column(String(100), nullable=True)
    kondisi          = Column(String(20), default="baik")     # baik / rusak / hilang
    status           = Column(String(20), default="tersedia")  # tersedia / dipinjam
    lantai           = Column(String(50), nullable=True)
    ruangan          = Column(String(100), nullable=True)   # lokasi fisik saat ini (teks bebas)
    tahun_perolehan  = Column(Integer, nullable=True)
    foto_barang      = Column(String(255), nullable=True)
    penguasaan       = Column(String(100), nullable=True)   # unit/pihak yang menguasai aset
    keterangan       = Column(Text, nullable=True)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
    updated_at       = Column(DateTime(timezone=True), onupdate=func.now(), server_default=func.now())

    kategori           = relationship("KategoriBarang", back_populates="barang")
    detail_peminjaman  = relationship("DetailPeminjaman", back_populates="barang")
    mutasi             = relationship("MutasiBarang", back_populates="barang")

    def is_available(self) -> bool:
        return self.status == "tersedia"


class Peminjaman(Base):
    __tablename__ = "peminjaman"

    id                       = Column(Integer, primary_key=True, index=True)
    user_id                  = Column(Integer, ForeignKey("users.id"), nullable=False)  # peminjam
    nama_dosen_matkul        = Column(String(150), nullable=True)
    kelas                    = Column(String(50), nullable=True)
    lokasi_pemakaian         = Column(String(150), nullable=False)
    tanggal_pinjam           = Column(String(20), nullable=False)   # format YYYY-MM-DD
    tanggal_kembali_rencana  = Column(String(20), nullable=False)
    tanggal_kembali_aktual   = Column(String(20), nullable=True)
    status                   = Column(String(20), default="dipinjam")  # dipinjam / dikembalikan / dibatalkan
    keterangan               = Column(Text, nullable=True)
    created_at               = Column(DateTime(timezone=True), server_default=func.now())

    user               = relationship("User", foreign_keys=[user_id])
    detail_peminjaman  = relationship("DetailPeminjaman", back_populates="peminjaman", cascade="all, delete-orphan")
    pengembalian        = relationship("Pengembalian", back_populates="peminjaman", uselist=False)


class DetailPeminjaman(Base):
    __tablename__ = "detail_peminjaman"

    id             = Column(Integer, primary_key=True, index=True)
    peminjaman_id  = Column(Integer, ForeignKey("peminjaman.id"), nullable=False)
    barang_id      = Column(Integer, ForeignKey("barang_gudang.id"), nullable=False)
    lantai_asal    = Column(String(50), nullable=True)
    ruangan_asal   = Column(String(100), nullable=True)
    jumlah         = Column(Integer, default=1)
    status_item    = Column(String(20), default="dipinjam")  # dipinjam / dikembalikan / dibatalkan
    kondisi_item   = Column(String(20), nullable=True)        # diisi saat pengembalian
    keterangan     = Column(Text, nullable=True)

    peminjaman = relationship("Peminjaman", back_populates="detail_peminjaman")
    barang     = relationship("Barang", back_populates="detail_peminjaman")


class Pengembalian(Base):
    __tablename__ = "pengembalian"

    id             = Column(Integer, primary_key=True, index=True)
    peminjaman_id  = Column(Integer, ForeignKey("peminjaman.id"), nullable=False)
    user_id        = Column(Integer, ForeignKey("users.id"), nullable=False)  # yang memproses pengembalian
    tanggal_kembali = Column(String(20), nullable=False)
    keterangan     = Column(Text, nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    peminjaman = relationship("Peminjaman", back_populates="pengembalian")
    user       = relationship("User", foreign_keys=[user_id])


class MutasiBarang(Base):
    __tablename__ = "mutasi_barang"

    id              = Column(Integer, primary_key=True, index=True)
    barang_id       = Column(Integer, ForeignKey("barang_gudang.id"), nullable=False)
    user_id         = Column(Integer, ForeignKey("users.id"), nullable=False)  # yang mencatat mutasi
    lantai_asal     = Column(String(50), nullable=True)
    ruangan_asal    = Column(String(100), nullable=True)
    lantai_tujuan   = Column(String(50), nullable=False)
    ruangan_tujuan  = Column(String(100), nullable=False)
    tanggal_mutasi  = Column(String(20), nullable=False)
    alasan          = Column(String(150), nullable=True)
    keterangan      = Column(Text, nullable=True)
    created_at      = Column(DateTime(timezone=True), server_default=func.now())

    barang = relationship("Barang", back_populates="mutasi")
    user   = relationship("User", foreign_keys=[user_id])