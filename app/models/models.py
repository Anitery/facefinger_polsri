from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Float, ForeignKey
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func
from app.database import Base


class Ruangan(Base):
    __tablename__ = "ruangan"

    id = Column(Integer, primary_key=True, index=True)
    nama = Column(String(100), nullable=False)
    lokasi = Column(String(100))
    lantai = Column(Integer)
    aktif = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    # Relasi
    users = relationship("User", back_populates="ruangan")
    access_logs = relationship("AccessLog", back_populates="ruangan")
    rekaman_kamera = relationship("RekamanKamera", back_populates="ruangan")
    inventaris = relationship("InventarisAlat", back_populates="ruangan")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    nama = Column(String(100), nullable=False)
    nim_nip = Column(String(20), unique=True, index=True)
    role = Column(String(20), default="mahasiswa")  # mahasiswa/dosen/teknisi/admin
    face_encoding = Column(Text, nullable=True)       # JSON string vektor 128-dim
    fingerprint_id = Column(Integer, nullable=True)   # ID di perangkat fingerprint
    ruangan_id = Column(Integer, ForeignKey("ruangan.id"), nullable=True)
    aktif = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    ruangan = relationship("Ruangan", back_populates="users")
    access_logs = relationship("AccessLog", back_populates="user")


class AccessLog(Base):
    __tablename__ = "access_log"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    ruangan_id = Column(Integer, ForeignKey("ruangan.id"), nullable=False)
    waktu_akses = Column(DateTime(timezone=True), server_default=func.now())
    metode = Column(String(20))   # face / fingerprint / ditolak
    foto_url = Column(Text, nullable=True)
    status = Column(String(10))   # berhasil / ditolak
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