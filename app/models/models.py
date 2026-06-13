from app.models.x606_models import X606Device, X606JadwalKBM, X606JadwalPeserta, AbsensiX606, X606UserCache
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Float, ForeignKey, Table
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base

# Tabel relasi many-to-many: ruangan ↔ penanggung jawab
penanggung_jawab = Table(
    "penanggung_jawab",
    Base.metadata,
    Column("ruangan_id", Integer, ForeignKey("ruangan.id"), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
)

jadwal_mahasiswa = Table(
    "jadwal_mahasiswa",
    Base.metadata,
    Column("jadwal_id", Integer, ForeignKey("jadwal_ruangan.id"), primary_key=True),
    Column("user_id", Integer, ForeignKey("users.id"), primary_key=True),
)


class Ruangan(Base):
    __tablename__ = "ruangan"

    id = Column(Integer, primary_key=True, index=True)
    nama = Column(String(100), nullable=False)
    lokasi = Column(String(100))
    lantai = Column(Integer)
    aktif = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relasi yang sudah ada
    users = relationship("User", back_populates="ruangan")
    access_logs = relationship("AccessLog", back_populates="ruangan")
    rekaman_kamera = relationship("RekamanKamera", back_populates="ruangan")
    inventaris = relationship("InventarisAlat", back_populates="ruangan")
    jadwal = relationship("JadwalRuangan", back_populates="ruangan")

    # Relasi baru — penanggung jawab (many-to-many)
    penanggung_jawab = relationship(
        "User",
        secondary="penanggung_jawab",
        backref="ruangan_tanggung_jawab"
    )

    # Relasi alat
    x606_devices    = relationship("X606Device",    back_populates="ruangan")
    x606_jadwal_kbm = relationship("X606JadwalKBM", back_populates="ruangan")
    absensi_x606    = relationship("AbsensiX606",   back_populates="ruangan")

class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    nama = Column(String(100), nullable=False)
    nim_nip = Column(String(20), unique=True, index=True)
    role = Column(String(20), default="mahasiswa")
    face_encoding = Column(Text, nullable=True)
    fingerprint_id = Column(Integer, nullable=True)
    password_hash = Column(String(255), nullable=True)
    ruangan_id = Column(Integer, ForeignKey("ruangan.id"), nullable=True)
    aktif = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    ruangan = relationship("Ruangan", back_populates="users")
    access_logs = relationship("AccessLog", back_populates="user")
    # Relasi many-to-many otomatis tersedia via backref="ruangan_tanggung_jawab"

    # Relasi alat
    absensi_x606       = relationship("AbsensiX606",       back_populates="user")
    x606_jadwal_peserta = relationship("X606JadwalPeserta", back_populates="user")

class AccessLog(Base):
    __tablename__ = "access_log"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    ruangan_id = Column(Integer, ForeignKey("ruangan.id"), nullable=False)
    waktu_akses = Column(DateTime(timezone=True), server_default=func.now())
    metode = Column(String(20))  # face / fingerprint / ditolak
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
    kelas          = Column(String(50), nullable=True)
    dosen          = Column(String(100), nullable=True)
    mata_kuliah    = Column(String(100), nullable=True)
    tanggal        = Column(String(20), nullable=False)
    jam_mulai      = Column(String(10), nullable=False)
    jam_selesai    = Column(String(10), nullable=False)
    keterangan     = Column(Text, nullable=True)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    mahasiswa_diizinkan = relationship(
        "User",
        secondary="jadwal_mahasiswa",
        backref="jadwal_diizinkan"
    )

    ruangan = relationship("Ruangan", back_populates="jadwal")


class Absensi(Base):
    __tablename__ = "absensi"

    id          = Column(Integer, primary_key=True, index=True)
    jadwal_id   = Column(Integer, ForeignKey("jadwal_ruangan.id"), nullable=False)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=False)
    waktu_masuk = Column(DateTime(timezone=True), nullable=True)
    status      = Column(String(20), nullable=False)
    keterangan  = Column(Text, nullable=True)
    created_at  = Column(DateTime(timezone=True), server_default=func.now())

    jadwal = relationship("JadwalRuangan", backref="absensi_list")
    user   = relationship("User", backref="absensi_list")

class BridgeHeartbeat(Base):
    __tablename__ = "bridge_heartbeat"

    id         = Column(Integer, primary_key=True)
    device_sn  = Column(String(50), nullable=False)
    device_ip  = Column(String(50), nullable=True)
    ruangan_id = Column(Integer, nullable=True)
    last_seen  = Column(DateTime(timezone=True),
                        server_default=func.now(),
                        onupdate=func.now())
    device_time = Column(String(30), nullable=True)
    total_user  = Column(Integer, default=0)
    extra_info  = Column(Text, nullable=True)  # JSON