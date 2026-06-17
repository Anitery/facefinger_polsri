import bcrypt
from itsdangerous import URLSafeTimedSerializer
from fastapi import Request
import os

SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-key-ganti-di-production")
serializer = URLSafeTimedSerializer(SECRET_KEY)

ALLOWED_ROLES = {"admin", "teknisi", "dosen"}


def hash_password(password: str) -> str:
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(password.encode("utf-8"), salt)
    return hashed.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(
            plain.encode("utf-8"),
            hashed.encode("utf-8")
        )
    except Exception:
        return False


def create_session_token(data: dict) -> str:
    return serializer.dumps(data, salt="session")


def decode_session_token(token: str, max_age: int = 86400):
    try:
        return serializer.loads(token, salt="session", max_age=max_age)
    except Exception:
        return None


def get_current_user(request: Request):
    token = request.cookies.get("session_token")
    if not token:
        return None
    return decode_session_token(token)


# --- FUNGSI BARU UNTUK MENGATUR REDIRECT BERDASARKAN ROLE ---
def redirect_default_page(role: str) -> str:
    """Mengembalikan path URL default berdasarkan role user."""
    if role == "admin":
        return "/dashboard"  # Sesuaikan dengan route admin Anda
    elif role == "teknisi":
        return "/dashboard" # Sesuaikan dengan route teknisi Anda
    elif role == "dosen":
        return "/dashboard"   # Sesuaikan dengan route dosen Anda
    
    return "/dashboard" # Fallback default