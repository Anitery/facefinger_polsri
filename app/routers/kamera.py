from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from typing import Optional
from datetime import datetime
from pydantic import BaseModel
from app.database import get_db
from app.models.models import RekamanKamera
from app.services.cloudinary_service import upload_video, delete_video
import tempfile, os, shutil

router = APIRouter(prefix="/kamera", tags=["Kamera Monitoring"])


class RekamanOut(BaseModel):
    id: int
    ruangan_id: int
    nama_file: str
    waktu_mulai: datetime
    waktu_selesai: Optional[datetime] = None
    url_video: Optional[str] = None
    thumbnail_url: Optional[str] = None
    ukuran_mb: Optional[float] = None

    model_config = {"from_attributes": True}


@router.get("/rekaman", response_model=list[RekamanOut])
def get_rekaman(
    ruangan_id: Optional[int] = None,
    limit: int = 20,
    db: Session = Depends(get_db)
):
    """Ambil daftar rekaman video."""
    q = db.query(RekamanKamera)
    if ruangan_id:
        q = q.filter(RekamanKamera.ruangan_id == ruangan_id)
    return q.order_by(RekamanKamera.waktu_mulai.desc()).limit(limit).all()


@router.post("/upload")
async def upload_rekaman(
    ruangan_id: int        = Form(...),
    waktu_mulai: str       = Form(...),   # ISO format: 2025-04-01T08:00:00
    waktu_selesai: str     = Form(...),
    video: UploadFile      = File(...),
    db: Session            = Depends(get_db)
):
    """
    Endpoint dipanggil oleh script kamera (laptop/Raspberry Pi).
    Menerima file video, upload ke Cloudinary, simpan metadata ke DB.
    """
    # Validasi tipe file
    allowed = ["video/mp4", "video/avi", "video/x-msvideo",
               "video/quicktime", "video/x-matroska"]
    if video.content_type not in allowed:
        raise HTTPException(
            status_code=400,
            detail=f"Tipe file tidak didukung: {video.content_type}"
        )

    # Simpan ke file temp
    suffix    = os.path.splitext(video.filename)[1] or ".mp4"
    tmp_path  = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            shutil.copyfileobj(video.file, tmp)
            tmp_path = tmp.name

        ukuran_mb = os.path.getsize(tmp_path) / (1024 * 1024)

        # Buat public_id unik
        ts        = datetime.now().strftime("%Y%m%d_%H%M%S")
        public_id = f"rekaman_{ruangan_id}_{ts}"

        # Upload ke Cloudinary
        result = upload_video(tmp_path, public_id, ruangan_id)

        if not result["success"]:
            raise HTTPException(
                status_code=500,
                detail=f"Gagal upload ke Cloudinary: {result.get('error')}"
            )

        # Simpan metadata ke database
        rekaman = RekamanKamera(
            ruangan_id    = ruangan_id,
            nama_file     = video.filename,
            waktu_mulai   = datetime.fromisoformat(waktu_mulai),
            waktu_selesai = datetime.fromisoformat(waktu_selesai),
            url_video     = result["secure_url"],
            thumbnail_url = result.get("thumbnail"),
            ukuran_mb     = round(ukuran_mb, 2)
        )
        db.add(rekaman)
        db.commit()
        db.refresh(rekaman)

        return {
            "status":     "berhasil",
            "rekaman_id": rekaman.id,
            "url_video":  result["url"],
            "ukuran_mb":  round(ukuran_mb, 2)
        }

    finally:
        # Hapus file temp
        if tmp_path and os.path.exists(tmp_path):
            os.unlink(tmp_path)


@router.delete("/rekaman/{rekaman_id}")
def hapus_rekaman(rekaman_id: int, db: Session = Depends(get_db)):
    """Hapus rekaman dari database dan Cloudinary."""
    rekaman = db.query(RekamanKamera).filter(
        RekamanKamera.id == rekaman_id
    ).first()
    if not rekaman:
        raise HTTPException(status_code=404, detail="Rekaman tidak ditemukan")

    # Hapus dari Cloudinary jika ada public_id
    if rekaman.url_video:
        # Ekstrak public_id dari URL Cloudinary
        parts     = rekaman.url_video.split("/upload/")
        if len(parts) > 1:
            public_id = parts[1].rsplit(".", 1)[0]
            delete_video(public_id)

    db.delete(rekaman)
    db.commit()
    return {"pesan": "Rekaman berhasil dihapus"}