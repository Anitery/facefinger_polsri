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
    fingerprint_id: Optional[int] = None
    password: Optional[str] = None

class UserUpdate(BaseModel):
    nama: Optional[str] = None
    nim_nip: Optional[str] = None
    role: Optional[str] = None
    kelas: Optional[str] = None  # ← FIX: Tambahan agar bisa update kelas
    aktif: Optional[bool] = None
    fingerprint_id: Optional[int] = None

class UserOut(UserBase):
    id: int
    aktif: bool
    fingerprint_id: Optional[int] = None
    face_encoding: Optional[str] = None
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

# ══════════════════════════════════════════════════════
# X606-S Device Schemas
# ══════════════════════════════════════════════════════

class X606DeviceBase(BaseModel):
    device_id:  str
    name:       str
    ip_address: str
    com_key:    str = "0"
    ruangan_id: Optional[int] = None
    is_active:  bool = True


class X606DeviceCreate(X606DeviceBase):
    pass


class X606DeviceUpdate(BaseModel):
    name:       Optional[str] = None
    ip_address: Optional[str] = None
    com_key:    Optional[str] = None
    ruangan_id: Optional[int] = None
    is_active:  Optional[bool] = None


class X606DeviceOut(X606DeviceBase):
    id:         int
    last_sync:  Optional[datetime] = None
    created_at: datetime
    model_config = {"from_attributes": True}


class X606TestResponse(BaseModel):
    success:     bool
    message:     str
    device_time: Optional[dict] = None


# ── Jadwal KBM X606 ──────────────────────────────────

class X606JadwalKBMBase(BaseModel):
    ruangan_id:      int
    nama_matakuliah: str
    kelas:           str
    hari:            str
    jam_mulai:       str   # format "HH:MM"
    jam_selesai:     str   # format "HH:MM"
    dosen_id:        Optional[int] = None
    is_active:       bool = True


class X606JadwalKBMCreate(X606JadwalKBMBase):
    peserta_ids: List[int] = []


class X606JadwalKBMUpdate(BaseModel):
    nama_matakuliah: Optional[str]  = None
    kelas:           Optional[str]  = None
    hari:            Optional[str]  = None
    jam_mulai:       Optional[str]  = None
    jam_selesai:     Optional[str]  = None
    dosen_id:        Optional[int]  = None
    is_active:       Optional[bool] = None
    peserta_ids:     Optional[List[int]] = None


class X606JadwalKBMOut(X606JadwalKBMBase):
    id:         int
    created_at: datetime
    model_config = {"from_attributes": True}


# ── Absensi X606 ─────────────────────────────────────

class AbsensiX606Out(BaseModel):
    id:              int
    user_id:         int
    ruangan_id:      int
    device_id:       str
    jadwal_id:       Optional[int]  = None
    waktu_scan:      datetime
    verified:        Optional[str]  = None
    status_scan:     Optional[str]  = None
    status_absensi:  str
    is_valid_jadwal: bool
    keterangan:      Optional[str]  = None
    model_config = {"from_attributes": True}


class PullLogResponse(BaseModel):
    success:       bool
    device_id:     str
    new_records:   int
    invalid_scans: int
    message:       str


class LabAccessCheck(BaseModel):
    user_id:      int
    user_name:    str
    can_access:   bool
    reason:       str
    jadwal_aktif: Optional[Any] = None


class X606UserCacheCreate(BaseModel):
    pin:     str
    user_id: int
    name:    str