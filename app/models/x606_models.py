"""
Model tambahan untuk X606-S Smart Lock Lab Multimedia 2
Lokasi: app/models/x606_models.py
"""
import enum
from sqlalchemy import Column, Integer, String, Boolean, DateTime, Text, Time, ForeignKey, Enum, UniqueConstraint
from sqlalchemy.sql import func
from sqlalchemy.orm import relationship
from app.database import Base


class HariEnum(str, enum.Enum):
    SENIN = "Senin"
    SELASA = "Selasa"
    RABU = "Rabu"
    KAMIS = "Kamis"
    JUMAT = "Jumat"
    SABTU = "Sabtu"
    MINGGU = "Minggu"


class StatusAbsensiX606(str, enum.Enum):
    HADIR = "Hadir"
    TERLAMBAT = "Terlambat"
    TIDAK_TERJADWAL = "Tidak Terjadwal"
    IZIN = "Izin"
    ALFA = "Alfa"


class X606Device(Base):
    __tablename__ = "x606_devices"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String(50), unique=True, index=True, nullable=False)
    name = Column(String(100), nullable=False)
    ip_address = Column(String(50), nullable=False)
    com_key = Column(String(10), default="0")
    ruangan_id = Column(Integer, ForeignKey("ruangan.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    last_sync = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    ruangan = relationship("Ruangan", back_populates="x606_devices")
    absensi_x606 = relationship("AbsensiX606", back_populates="device")


class X606JadwalKBM(Base):
    __tablename__ = "x606_jadwal_kbm"

    id = Column(Integer, primary_key=True, index=True)
    ruangan_id = Column(Integer, ForeignKey("ruangan.id"), nullable=False)
    nama_matakuliah = Column(String(100), nullable=False)
    kelas = Column(String(50), nullable=False)
    hari = Column(Enum(HariEnum), nullable=False)
    jam_mulai = Column(Time, nullable=False)
    jam_selesai = Column(Time, nullable=False)
    dosen_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    ruangan = relationship("Ruangan", back_populates="x606_jadwal_kbm")
    peserta = relationship("X606JadwalPeserta", back_populates="jadwal", cascade="all, delete-orphan")
    absensi = relationship("AbsensiX606", back_populates="jadwal")


class X606JadwalPeserta(Base):
    __tablename__ = "x606_jadwal_peserta"

    id = Column(Integer, primary_key=True, index=True)
    jadwal_id = Column(Integer, ForeignKey("x606_jadwal_kbm.id"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    x606_pin = Column(String(20), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())

    jadwal = relationship("X606JadwalKBM", back_populates="peserta")
    user = relationship("User", back_populates="x606_jadwal_peserta")


class AbsensiX606(Base):
    __tablename__ = "absensi_x606"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    ruangan_id = Column(Integer, ForeignKey("ruangan.id"), nullable=False)
    device_id = Column(String(50), ForeignKey("x606_devices.device_id"), nullable=False)
    jadwal_id = Column(Integer, ForeignKey("x606_jadwal_kbm.id"), nullable=True)

    waktu_scan = Column(DateTime(timezone=True), nullable=False)
    verified = Column(String(10))
    status_scan = Column(String(10))
    status_absensi = Column(Enum(StatusAbsensiX606), default=StatusAbsensiX606.HADIR)

    is_valid_jadwal = Column(Boolean, default=True)
    keterangan = Column(Text, nullable=True)

    created_at = Column(DateTime(timezone=True), server_default=func.now())

    user = relationship("User", back_populates="absensi_x606")
    ruangan = relationship("Ruangan", back_populates="absensi_x606")
    device = relationship("X606Device", back_populates="absensi_x606")
    jadwal = relationship("X606JadwalKBM", back_populates="absensi")


class X606UserCache(Base):
    __tablename__ = "x606_user_cache"

    id = Column(Integer, primary_key=True, index=True)
    device_id = Column(String(50), ForeignKey("x606_devices.device_id"), nullable=False)
    pin = Column(String(20), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    name = Column(String(100))
    last_sync = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (UniqueConstraint('device_id', 'pin', name='uix_x606_device_pin'),)
