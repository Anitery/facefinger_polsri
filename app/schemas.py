from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime


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
    nim_nip: str
    role: Optional[str] = "mahasiswa"
    ruangan_id: Optional[int] = None

class UserCreate(UserBase):
    pass

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