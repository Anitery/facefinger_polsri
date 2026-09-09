"""
Router Inventaris Gudang — digabung jadi satu file (dari sebelumnya
5 file terpisah: kategori.py, barang.py, peminjaman.py, pengembalian.py,
mutasi.py) supaya lebih ringkas dikelola. URL endpoint TIDAK berubah,
jadi tidak mempengaruhi kode frontend yang sudah ada.

Diadaptasi dari project "inventaris-lab" (Laravel) milik rekan satu
kelompok TA — device X606-S yang sama, ruangan Gudang.
"""

import os
import tempfile
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy.orm import Session, joinedload
from sqlalchemy.exc import IntegrityError

from app.database import get_db
from app.models.models import (
    KategoriBarang, Barang, Peminjaman, DetailPeminjaman, Pengembalian,
    MutasiBarang, User,
)
from app.schemas import (
    KategoriBarangCreate, KategoriBarangOut,
    BarangCreate, BarangUpdate, BarangOut,
    PeminjamanCreate, PeminjamanOut,
    PengembalianCreate, PengembalianOut,
    MutasiBarangCreate, MutasiBarangOut,
)
from app.services.auth_service import get_current_user_session
from app.services.cloudinary_service import upload_image, delete_image


# ═══════════════════════════════════════════════════════════════════════
# ── Kategori Barang ───────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════
kategori_router = APIRouter(prefix="/kategori-barang", tags=["Inventaris Gudang"])


@kategori_router.get("/", response_model=list[KategoriBarangOut])
def list_kategori(db: Session = Depends(get_db)):
    return db.query(KategoriBarang).order_by(KategoriBarang.nama_kategori).all()


@kategori_router.post("/", response_model=KategoriBarangOut)
def create_kategori(payload: KategoriBarangCreate, db: Session = Depends(get_db), user=Depends(get_current_user_session)):
    k = KategoriBarang(**payload.model_dump())
    db.add(k)
    db.commit()
    db.refresh(k)
    return k


@kategori_router.put("/{kategori_id}", response_model=KategoriBarangOut)
def update_kategori(kategori_id: int, payload: KategoriBarangCreate, db: Session = Depends(get_db), user=Depends(get_current_user_session)):
    k = db.query(KategoriBarang).filter(KategoriBarang.id == kategori_id).first()
    if not k:
        raise HTTPException(status_code=404, detail="Kategori tidak ditemukan")
    k.nama_kategori = payload.nama_kategori
    k.jenis = payload.jenis
    db.commit()
    db.refresh(k)
    return k


@kategori_router.delete("/{kategori_id}")
def delete_kategori(kategori_id: int, db: Session = Depends(get_db), user=Depends(get_current_user_session)):
    k = db.query(KategoriBarang).filter(KategoriBarang.id == kategori_id).first()
    if not k:
        raise HTTPException(status_code=404, detail="Kategori tidak ditemukan")
    try:
        db.delete(k)
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=400, detail="Kategori tidak bisa dihapus karena masih dipakai oleh barang.")
    return {"pesan": "Kategori dihapus"}


# ═══════════════════════════════════════════════════════════════════════
# ── Barang ─────────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════
barang_router = APIRouter(prefix="/barang", tags=["Inventaris Gudang"])


@barang_router.get("/", response_model=list[BarangOut])
def list_barang(
    search: Optional[str] = Query(None), lantai: Optional[str] = Query(None),
    ruangan: Optional[str] = Query(None), kondisi: Optional[str] = Query(None),
    status: Optional[str] = Query(None), id_kategori: Optional[int] = Query(None),
    db: Session = Depends(get_db),
):
    q = db.query(Barang).options(joinedload(Barang.kategori))
    if search:
        like = f"%{search}%"
        q = q.filter((Barang.nama_barang.ilike(like)) | (Barang.kode_barang.ilike(like)) | (Barang.nup.ilike(like)))
    if lantai:
        q = q.filter(Barang.lantai == lantai)
    if ruangan:
        q = q.filter(Barang.ruangan == ruangan)
    if kondisi:
        q = q.filter(Barang.kondisi == kondisi)
    if status:
        q = q.filter(Barang.status == status)
    if id_kategori:
        q = q.filter(Barang.id_kategori == id_kategori)
    return q.order_by(Barang.nama_barang).all()


@barang_router.get("/lokasi")
def list_lokasi(db: Session = Depends(get_db)):
    lantai = [r[0] for r in db.query(Barang.lantai).filter(Barang.lantai.isnot(None)).distinct().order_by(Barang.lantai).all()]
    ruangan = [r[0] for r in db.query(Barang.ruangan).filter(Barang.ruangan.isnot(None)).distinct().order_by(Barang.ruangan).all()]
    return {"lantai": lantai, "ruangan": ruangan}


@barang_router.get("/barcode/{kode}", response_model=BarangOut)
def get_by_barcode(kode: str, db: Session = Depends(get_db)):
    b = db.query(Barang).options(joinedload(Barang.kategori)).filter(Barang.kode_barang == kode).first()
    if not b:
        raise HTTPException(status_code=404, detail="Barang tidak ditemukan")
    return b


@barang_router.get("/{barang_id}", response_model=BarangOut)
def get_barang(barang_id: int, db: Session = Depends(get_db)):
    b = db.query(Barang).options(joinedload(Barang.kategori)).filter(Barang.id == barang_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="Barang tidak ditemukan")
    return b


@barang_router.post("/", response_model=BarangOut)
def create_barang(payload: BarangCreate, db: Session = Depends(get_db), user=Depends(get_current_user_session)):
    if db.query(Barang).filter(Barang.kode_barang == payload.kode_barang).first():
        raise HTTPException(status_code=400, detail="Kode barang sudah dipakai")
    if payload.id_kategori and not db.query(KategoriBarang).filter(KategoriBarang.id == payload.id_kategori).first():
        raise HTTPException(status_code=400, detail="Kategori tidak ditemukan")
    b = Barang(**payload.model_dump(), status="tersedia")
    db.add(b)
    db.commit()
    db.refresh(b)
    return b


@barang_router.put("/{barang_id}", response_model=BarangOut)
def update_barang(barang_id: int, payload: BarangUpdate, db: Session = Depends(get_db), user=Depends(get_current_user_session)):
    b = db.query(Barang).filter(Barang.id == barang_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="Barang tidak ditemukan")
    data = payload.model_dump(exclude_unset=True)
    if "kode_barang" in data and data["kode_barang"] and data["kode_barang"] != b.kode_barang:
        if db.query(Barang).filter(Barang.kode_barang == data["kode_barang"]).first():
            raise HTTPException(status_code=400, detail="Kode barang sudah dipakai")
    for field, value in data.items():
        setattr(b, field, value)
    db.commit()
    db.refresh(b)
    return b


@barang_router.post("/{barang_id}/foto", response_model=BarangOut)
async def upload_foto_barang(barang_id: int, foto: UploadFile = File(...), db: Session = Depends(get_db), user=Depends(get_current_user_session)):
    b = db.query(Barang).filter(Barang.id == barang_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="Barang tidak ditemukan")
    suffix = os.path.splitext(foto.filename or "")[1] or ".jpg"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp.write(await foto.read())
        tmp_path = tmp.name
    try:
        result = upload_image(tmp_path, public_id=f"barang_{b.id}", folder="facefinger_polsri/inventaris_gudang")
    finally:
        os.unlink(tmp_path)
    if not result.get("success"):
        raise HTTPException(status_code=500, detail=f"Upload foto gagal: {result.get('error')}")
    b.foto_barang = result["url"]
    db.commit()
    db.refresh(b)
    return b


@barang_router.delete("/{barang_id}")
def delete_barang(barang_id: int, db: Session = Depends(get_db), user=Depends(get_current_user_session)):
    b = db.query(Barang).filter(Barang.id == barang_id).first()
    if not b:
        raise HTTPException(status_code=404, detail="Barang tidak ditemukan")
    if b.status == "dipinjam":
        raise HTTPException(status_code=400, detail="Barang sedang dipinjam, tidak bisa dihapus")
    if b.foto_barang:
        delete_image(f"facefinger_polsri/inventaris_gudang/barang_{b.id}")
    db.delete(b)
    db.commit()
    return {"pesan": "Barang dihapus"}


# ═══════════════════════════════════════════════════════════════════════
# ── Peminjaman ─────────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════
peminjaman_router = APIRouter(prefix="/peminjaman", tags=["Inventaris Gudang"])


def _peminjaman_query(db: Session):
    return db.query(Peminjaman).options(
        joinedload(Peminjaman.user),
        joinedload(Peminjaman.detail_peminjaman).joinedload(DetailPeminjaman.barang),
    )


@peminjaman_router.get("/", response_model=list[PeminjamanOut])
def list_peminjaman(status: Optional[str] = Query(None), search: Optional[str] = Query(None), db: Session = Depends(get_db), user=Depends(get_current_user_session)):
    q = _peminjaman_query(db)
    if status:
        q = q.filter(Peminjaman.status == status)
    if search:
        q = q.join(User, Peminjaman.user_id == User.id).filter(User.nama.ilike(f"%{search}%"))
    return q.order_by(Peminjaman.created_at.desc()).all()


@peminjaman_router.get("/available-barang")
def list_barang_tersedia(db: Session = Depends(get_db)):
    rows = db.query(Barang).filter(Barang.kondisi == "baik", Barang.status == "tersedia").order_by(Barang.nama_barang).all()
    return [{"id": b.id, "kode_barang": b.kode_barang, "nup": b.nup, "nama_barang": b.nama_barang, "lantai": b.lantai, "ruangan": b.ruangan} for b in rows]


@peminjaman_router.get("/{peminjaman_id}", response_model=PeminjamanOut)
def get_peminjaman(peminjaman_id: int, db: Session = Depends(get_db), user=Depends(get_current_user_session)):
    p = _peminjaman_query(db).filter(Peminjaman.id == peminjaman_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Peminjaman tidak ditemukan")
    return p


@peminjaman_router.post("/", response_model=PeminjamanOut)
def create_peminjaman(payload: PeminjamanCreate, db: Session = Depends(get_db), user=Depends(get_current_user_session)):
    if not payload.barang:
        raise HTTPException(status_code=400, detail="Minimal satu barang harus dipilih")
    if payload.tanggal_kembali_rencana < payload.tanggal_pinjam:
        raise HTTPException(status_code=400, detail="Tanggal kembali harus setelah tanggal pinjam")

    peminjam_id = payload.user_id or user["user_id"]
    peminjam = db.query(User).filter(User.id == peminjam_id).first()
    if not peminjam:
        raise HTTPException(status_code=400, detail="Peminjam tidak ditemukan")

    barang_list = []
    for item in payload.barang:
        b = db.query(Barang).filter(Barang.id == item.barang_id).first()
        if not b or b.status != "tersedia":
            nama = b.nama_barang if b else f"ID {item.barang_id}"
            raise HTTPException(status_code=400, detail=f"{nama} tidak tersedia")
        barang_list.append(b)

    try:
        peminjaman = Peminjaman(
            user_id=peminjam_id, nama_dosen_matkul=payload.nama_dosen_matkul, kelas=payload.kelas,
            lokasi_pemakaian=payload.lokasi_pemakaian, tanggal_pinjam=payload.tanggal_pinjam,
            tanggal_kembali_rencana=payload.tanggal_kembali_rencana, status="dipinjam", keterangan=payload.keterangan,
        )
        db.add(peminjaman)
        db.flush()
        for b in barang_list:
            db.add(DetailPeminjaman(peminjaman_id=peminjaman.id, barang_id=b.id, jumlah=1, status_item="dipinjam", lantai_asal=b.lantai, ruangan_asal=b.ruangan))
            b.status = "dipinjam"
            b.ruangan = payload.lokasi_pemakaian
            b.lantai = None
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(peminjaman)
    return _peminjaman_query(db).filter(Peminjaman.id == peminjaman.id).first()


@peminjaman_router.patch("/{peminjaman_id}/batalkan", response_model=PeminjamanOut)
def batalkan_peminjaman(peminjaman_id: int, db: Session = Depends(get_db), user=Depends(get_current_user_session)):
    p = db.query(Peminjaman).options(joinedload(Peminjaman.detail_peminjaman).joinedload(DetailPeminjaman.barang)).filter(Peminjaman.id == peminjaman_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Peminjaman tidak ditemukan")
    if p.status != "dipinjam":
        raise HTTPException(status_code=400, detail="Peminjaman tidak dapat dibatalkan")
    try:
        for detail in p.detail_peminjaman:
            detail.barang.status = "tersedia"
            detail.barang.lantai = detail.lantai_asal
            detail.barang.ruangan = detail.ruangan_asal
            detail.status_item = "dibatalkan"
        p.status = "dibatalkan"
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(p)
    return _peminjaman_query(db).filter(Peminjaman.id == p.id).first()


@peminjaman_router.delete("/{peminjaman_id}")
def delete_peminjaman(peminjaman_id: int, db: Session = Depends(get_db), user=Depends(get_current_user_session)):
    p = db.query(Peminjaman).filter(Peminjaman.id == peminjaman_id).first()
    if not p:
        raise HTTPException(status_code=404, detail="Peminjaman tidak ditemukan")
    if p.status == "dipinjam":
        raise HTTPException(status_code=400, detail="Peminjaman yang sedang aktif tidak dapat dihapus")
    db.delete(p)
    db.commit()
    return {"pesan": "Data peminjaman dihapus"}


# ═══════════════════════════════════════════════════════════════════════
# ── Pengembalian ───────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════
pengembalian_router = APIRouter(prefix="/pengembalian", tags=["Inventaris Gudang"])
KONDISI_VALID = {"baik", "rusak", "hilang"}


@pengembalian_router.get("/", response_model=list[PengembalianOut])
def list_pengembalian(search: Optional[str] = Query(None), db: Session = Depends(get_db), user=Depends(get_current_user_session)):
    q = db.query(Pengembalian).options(
        joinedload(Pengembalian.peminjaman).joinedload(Peminjaman.user),
        joinedload(Pengembalian.peminjaman).joinedload(Peminjaman.detail_peminjaman),
    )
    if search:
        q = q.join(Peminjaman, Pengembalian.peminjaman_id == Peminjaman.id).join(User, Peminjaman.user_id == User.id).filter(User.nama.ilike(f"%{search}%"))
    return q.order_by(Pengembalian.created_at.desc()).all()


@pengembalian_router.get("/peminjaman-aktif")
def list_peminjaman_aktif(db: Session = Depends(get_db), user=Depends(get_current_user_session)):
    rows = db.query(Peminjaman).options(joinedload(Peminjaman.user), joinedload(Peminjaman.detail_peminjaman).joinedload(DetailPeminjaman.barang)).filter(Peminjaman.status == "dipinjam").order_by(Peminjaman.tanggal_kembali_rencana).all()
    return [
        {
            "id": p.id, "peminjam": p.user.nama if p.user else "-", "lokasi_pemakaian": p.lokasi_pemakaian,
            "tanggal_pinjam": p.tanggal_pinjam, "tanggal_kembali_rencana": p.tanggal_kembali_rencana,
            "barang": [{"barang_id": d.barang_id, "nama_barang": d.barang.nama_barang, "kode_barang": d.barang.kode_barang} for d in p.detail_peminjaman if d.status_item == "dipinjam"],
        }
        for p in rows
    ]


@pengembalian_router.get("/{pengembalian_id}", response_model=PengembalianOut)
def get_pengembalian(pengembalian_id: int, db: Session = Depends(get_db), user=Depends(get_current_user_session)):
    row = db.query(Pengembalian).options(
        joinedload(Pengembalian.peminjaman).joinedload(Peminjaman.user),
        joinedload(Pengembalian.peminjaman).joinedload(Peminjaman.detail_peminjaman).joinedload(DetailPeminjaman.barang),
    ).filter(Pengembalian.id == pengembalian_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Data pengembalian tidak ditemukan")
    return row


@pengembalian_router.post("/", response_model=PengembalianOut)
def create_pengembalian(payload: PengembalianCreate, db: Session = Depends(get_db), user=Depends(get_current_user_session)):
    peminjaman = db.query(Peminjaman).options(joinedload(Peminjaman.detail_peminjaman).joinedload(DetailPeminjaman.barang)).filter(Peminjaman.id == payload.peminjaman_id).first()
    if not peminjaman:
        raise HTTPException(status_code=404, detail="Peminjaman tidak ditemukan")
    if peminjaman.status != "dipinjam":
        raise HTTPException(status_code=400, detail="Peminjaman ini sudah diproses sebelumnya")

    detail_aktif = [d for d in peminjaman.detail_peminjaman if d.status_item == "dipinjam"]
    if not detail_aktif:
        raise HTTPException(status_code=400, detail="Tidak ada barang aktif pada peminjaman ini")
    for d in detail_aktif:
        kondisi = payload.kondisi.get(d.barang_id)
        if kondisi not in KONDISI_VALID:
            raise HTTPException(status_code=400, detail=f"Kondisi untuk '{d.barang.nama_barang}' wajib diisi (baik/rusak/hilang)")

    try:
        pengembalian = Pengembalian(peminjaman_id=peminjaman.id, user_id=user["user_id"], tanggal_kembali=payload.tanggal_kembali, keterangan=payload.keterangan)
        db.add(pengembalian)
        for d in detail_aktif:
            kondisi = payload.kondisi[d.barang_id]
            d.status_item = "dikembalikan"
            d.kondisi_item = kondisi
            if kondisi == "baik":
                d.barang.status = "tersedia"
                d.barang.kondisi = "baik"
                d.barang.lantai = d.lantai_asal
                d.barang.ruangan = d.ruangan_asal
            else:
                d.barang.kondisi = kondisi
        peminjaman.status = "dikembalikan"
        peminjaman.tanggal_kembali_aktual = payload.tanggal_kembali
        db.commit()
    except Exception:
        db.rollback()
        raise

    db.refresh(pengembalian)
    return db.query(Pengembalian).options(
        joinedload(Pengembalian.peminjaman).joinedload(Peminjaman.user),
        joinedload(Pengembalian.peminjaman).joinedload(Peminjaman.detail_peminjaman).joinedload(DetailPeminjaman.barang),
    ).filter(Pengembalian.id == pengembalian.id).first()


# ═══════════════════════════════════════════════════════════════════════
# ── Mutasi Barang ──────────────────────────────────────────────────────
# ═══════════════════════════════════════════════════════════════════════
mutasi_router = APIRouter(prefix="/mutasi-barang", tags=["Inventaris Gudang"])


@mutasi_router.get("/", response_model=list[MutasiBarangOut])
def list_mutasi(search: Optional[str] = Query(None), db: Session = Depends(get_db), user=Depends(get_current_user_session)):
    q = db.query(MutasiBarang).options(joinedload(MutasiBarang.barang))
    if search:
        q = q.join(Barang, MutasiBarang.barang_id == Barang.id).filter((Barang.nama_barang.ilike(f"%{search}%")) | (Barang.kode_barang.ilike(f"%{search}%")))
    return q.order_by(MutasiBarang.created_at.desc()).all()


@mutasi_router.get("/{mutasi_id}", response_model=MutasiBarangOut)
def get_mutasi(mutasi_id: int, db: Session = Depends(get_db), user=Depends(get_current_user_session)):
    row = db.query(MutasiBarang).options(joinedload(MutasiBarang.barang)).filter(MutasiBarang.id == mutasi_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="Data mutasi tidak ditemukan")
    return row


@mutasi_router.post("/", response_model=MutasiBarangOut)
def create_mutasi(payload: MutasiBarangCreate, db: Session = Depends(get_db), user=Depends(get_current_user_session)):
    barang = db.query(Barang).filter(Barang.id == payload.barang_id).first()
    if not barang:
        raise HTTPException(status_code=404, detail="Barang tidak ditemukan")
    if barang.status == "dipinjam":
        raise HTTPException(status_code=400, detail="Barang sedang dipinjam, tidak bisa dimutasi")
    try:
        mutasi = MutasiBarang(
            barang_id=barang.id, user_id=user["user_id"], lantai_asal=barang.lantai, ruangan_asal=barang.ruangan,
            lantai_tujuan=payload.lantai_tujuan, ruangan_tujuan=payload.ruangan_tujuan,
            tanggal_mutasi=payload.tanggal_mutasi, alasan=payload.alasan, keterangan=payload.keterangan,
        )
        db.add(mutasi)
        barang.lantai = payload.lantai_tujuan
        barang.ruangan = payload.ruangan_tujuan
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(mutasi)
    return db.query(MutasiBarang).options(joinedload(MutasiBarang.barang)).filter(MutasiBarang.id == mutasi.id).first()


# Riwayat mutasi bersifat permanen — tidak ada endpoint delete, sengaja.


# Daftar semua router di modul ini, supaya main.py cukup 1 baris loop
# untuk mendaftarkan semuanya.
routers = [kategori_router, barang_router, peminjaman_router, pengembalian_router, mutasi_router]