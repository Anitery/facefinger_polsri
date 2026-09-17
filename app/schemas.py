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
    door_service_url: Optional[str] = None
    penanggung_jawab: list[PenanggungJawabInfo] = []
    model_config = {"from_attributes": True}


class RuanganDoorServiceUpdate(BaseModel):
    """Payload untuk mengatur alamat door_service.py milik sebuah ruangan
    (mendukung multi-STB / multi-port tanpa perlu redeploy backend)."""
    door_service_url: Optional[str] = None
    door_service_api_key: Optional[str] = None


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


# ── Pengaturan Sistem ─────────────────────────────────────────
class PengaturanOut(BaseModel):
    wajib_jadwal: bool
    sembunyikan_ip: bool
    mode_pemeliharaan: bool
    toleransi_keterlambatan_menit: int
    toleransi_masuk_awal_menit: int
    model_config = {"from_attributes": True}

class PengaturanUpdate(BaseModel):
    wajib_jadwal: Optional[bool] = None
    sembunyikan_ip: Optional[bool] = None
    mode_pemeliharaan: Optional[bool] = None
    toleransi_keterlambatan_menit: Optional[int] = None
    toleransi_masuk_awal_menit: Optional[int] = None


# ── Inventaris Gudang: Kategori ─────────────────────────────
class KategoriBarangBase(BaseModel):
    nama_kategori: str
    jenis: Optional[str] = None

class KategoriBarangCreate(KategoriBarangBase):
    pass

class KategoriBarangOut(KategoriBarangBase):
    id: int
    model_config = {"from_attributes": True}


# ── Inventaris Gudang: Barang ────────────────────────────────
class BarangBase(BaseModel):
    id_kategori: Optional[int] = None
    kode_barang: str
    nup: Optional[str] = None
    sumber_kode: Optional[str] = "manual"
    nama_barang: str
    merk_type: Optional[str] = None
    kondisi: Optional[str] = "baik"
    lantai: Optional[str] = None
    ruangan: Optional[str] = None
    tahun_perolehan: Optional[int] = None
    penguasaan: Optional[str] = None
    keterangan: Optional[str] = None

class BarangCreate(BarangBase):
    pass

class BarangUpdate(BarangBase):
    kode_barang: Optional[str] = None
    nama_barang: Optional[str] = None

class BarangOut(BarangBase):
    id: int
    status: str
    foto_barang: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    kategori: Optional[KategoriBarangOut] = None
    model_config = {"from_attributes": True}


# ── Inventaris Gudang: Peminjaman ────────────────────────────
class ItemPinjamRequest(BaseModel):
    barang_id: int

class PeminjamanCreate(BaseModel):
    user_id: Optional[int] = None  # admin bisa pilih peminjam lain; user biasa pakai akun sendiri
    nama_dosen_matkul: Optional[str] = None
    kelas: Optional[str] = None
    lokasi_pemakaian: str
    tanggal_pinjam: str
    tanggal_kembali_rencana: str
    keterangan: Optional[str] = None
    barang: List[ItemPinjamRequest]

class PeminjamUserInfo(BaseModel):
    id: int
    nama: str
    nim_nip: Optional[str] = None
    model_config = {"from_attributes": True}

class DetailPeminjamanOut(BaseModel):
    id: int
    barang_id: int
    barang: Optional[BarangOut] = None
    lantai_asal: Optional[str] = None
    ruangan_asal: Optional[str] = None
    jumlah: int
    status_item: str
    kondisi_item: Optional[str] = None
    keterangan: Optional[str] = None
    model_config = {"from_attributes": True}

class PeminjamanOut(BaseModel):
    id: int
    user_id: int
    user: Optional[PeminjamUserInfo] = None
    nama_dosen_matkul: Optional[str] = None
    kelas: Optional[str] = None
    lokasi_pemakaian: str
    tanggal_pinjam: str
    tanggal_kembali_rencana: str
    tanggal_kembali_aktual: Optional[str] = None
    status: str
    keterangan: Optional[str] = None
    detail_peminjaman: List[DetailPeminjamanOut] = []
    model_config = {"from_attributes": True}


# ── Inventaris Gudang: Pengembalian ──────────────────────────
class PengembalianCreate(BaseModel):
    peminjaman_id: int
    tanggal_kembali: str
    kondisi: dict[int, str]  # {barang_id: kondisi} — baik/rusak/hilang
    keterangan: Optional[str] = None

class PengembalianOut(BaseModel):
    id: int
    peminjaman_id: int
    user_id: int
    tanggal_kembali: str
    keterangan: Optional[str] = None
    peminjaman: Optional[PeminjamanOut] = None
    model_config = {"from_attributes": True}


# ── Inventaris Gudang: Mutasi Barang ─────────────────────────
class MutasiBarangCreate(BaseModel):
    barang_id: int
    lantai_tujuan: str
    ruangan_tujuan: str
    tanggal_mutasi: str
    alasan: Optional[str] = None
    keterangan: Optional[str] = None

class MutasiBarangOut(BaseModel):
    id: int
    barang_id: int
    barang: Optional[BarangOut] = None
    lantai_asal: Optional[str] = None
    ruangan_asal: Optional[str] = None
    lantai_tujuan: str
    ruangan_tujuan: str
    tanggal_mutasi: str
    alasan: Optional[str] = None
    keterangan: Optional[str] = None
    model_config = {"from_attributes": True}