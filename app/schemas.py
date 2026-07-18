from pydantic import BaseModel
from typing import Optional, List, Any
from datetime import datetime
from enum import Enum as PyEnum

# ── Ruangan ────────────────────────────────────────────────
class RuanganBase(BaseModel):
    nama: str
    lokasi: Optional[str] = None
    lantai: Optional[int] = None

class RuanganCreate(RuanganBase):
    pass

class PenanggungJawabInfo(BaseModel):
    id:     int
    nama:   str
    nim_nip: str
    role:   str
    model_config = {"from_attributes": True}

class RuanganOut(RuanganBase):
    id:    int
    aktif: bool
    penanggung_jawab: list[PenanggungJawabInfo] = []
    model_config = {"from_attributes": True}


# ── User ───────────────────────────────────────────────────
class UserBase(BaseModel):
    nama: str
    nim_nip: Optional[str] = None
    role: Optional[str] = "mahasiswa"
    kelas: Optional[str] = None  # ← TAMBAH
    ruangan_id: Optional[int] = None

class UserCreate(UserBase):
    id_perangkat: Optional[int] = None
    password: Optional[str] = None

class UserUpdate(BaseModel):
    nama: Optional[str] = None
    nim_nip: Optional[str] = None
    role: Optional[str] = None
    kelas: Optional[str] = None  # ← FIX: Tambahan agar bisa update kelas
    aktif: Optional[bool] = None
    id_perangkat: Optional[int] = None

class UserOut(UserBase):
    id: int
    aktif: bool
    id_perangkat: Optional[int] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ── Auth ───────────────────────────────────────────────────
class AuthFaceRequest(BaseModel):
    ruangan_id: int
    face_encoding: List[float]
    foto_base64: Optional[str] = None

class AuthFingerprintRequest(BaseModel):
    ruangan_id: int
    fingerprint_id: int

class AuthResponse(BaseModel):
    status: str
    user_id: Optional[int] = None
    nama: Optional[str] = None
    pesan: str


# ── Access Log ─────────────────────────────────────────────
class AccessLogOut(BaseModel):
    id: int
    user_id: Optional[int] = None
    ruangan_id: int
    waktu_akses: datetime
    metode: str
    foto_url: Optional[str] = None
    status: str
    keterangan: Optional[str] = None

    model_config = {"from_attributes": True}


# ── Inventaris ─────────────────────────────────────────────
class InventarisBase(BaseModel):
    kode_barcode: str
    nama_alat: str
    jumlah: Optional[int] = 1
    ruangan_id: int
    keterangan: Optional[str] = None

class InventarisCreate(InventarisBase):
    pass

class InventarisOut(InventarisBase):
    id: int
    status: str
    updated_at: datetime

    model_config = {"from_attributes": True}


# ── Jadwal Ruangan ───────────────────────────────────────────
class MahasiswaInfo(BaseModel):
    id: int
    nama: str
    nim_nip: Optional[str] = None
    model_config = {"from_attributes": True}

class JadwalCreate(BaseModel):
    ruangan_id:    int
    nama_kegiatan: str
    kelas:         Optional[str] = None
    dosen:         Optional[str] = None
    mata_kuliah:   Optional[str] = None
    tanggal:       str
    jam_mulai:     str
    jam_selesai:   str
    keterangan:    Optional[str] = None

class JadwalOut(JadwalCreate):
    id: int
    is_active: bool
    mahasiswa_diizinkan: List[MahasiswaInfo] = []
    model_config = {"from_attributes": True}