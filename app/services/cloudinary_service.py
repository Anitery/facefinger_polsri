import cloudinary
import cloudinary.uploader
from dotenv import load_dotenv
import os

load_dotenv()

cloudinary.config(
    cloud_name  = os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key     = os.getenv("CLOUDINARY_API_KEY"),
    api_secret  = os.getenv("CLOUDINARY_API_SECRET"),
    secure      = True
)


def upload_video(file_path: str, public_id: str, ruangan_id: int) -> dict:
    """
    Upload file video ke Cloudinary.
    Returns: dict berisi url, public_id, duration, dll.
    """
    try:
        result = cloudinary.uploader.upload(
            file_path,
            resource_type = "video",
            public_id     = public_id,
            folder        = f"smartdoorlock/ruangan_{ruangan_id}/rekaman",
            overwrite     = True,
            eager = [
                # Generate thumbnail otomatis di detik ke-1
                {"width": 320, "height": 240, "crop": "fill",
                 "format": "jpg", "start_offset": "1"}
            ],
            eager_async = True
        )
        return {
            "success":    True,
            "url":        result.get("secure_url"),
            "public_id":  result.get("public_id"),
            "duration":   result.get("duration"),
            "bytes":      result.get("bytes"),
            "thumbnail":  result.get("eager", [{}])[0].get("secure_url") if result.get("eager") else None
        }
    except Exception as e:
        return {"success": False, "error": str(e)}


def delete_video(public_id: str) -> bool:
    """Hapus video dari Cloudinary."""
    try:
        cloudinary.uploader.destroy(public_id, resource_type="video")
        return True
    except Exception:
        return False


def get_thumbnail_url(public_id: str) -> str:
    """Generate URL thumbnail dari video yang sudah diupload."""
    return cloudinary.CloudinaryImage(public_id).build_url(
        resource_type = "video",
        format        = "jpg",
        transformation = [
            {"width": 320, "height": 240, "crop": "fill", "start_offset": "1"}
        ]
    )