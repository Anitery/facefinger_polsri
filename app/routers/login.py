from fastapi import APIRouter, Request, Depends, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import User
from app.services.auth_service import (
    verify_password, create_session_token,
    decode_session_token, ALLOWED_ROLES, 
    redirect_default_page # <- Impor fungsi baru
)

router = APIRouter(tags=["Login"])
templates = Jinja2Templates(directory="app/templates")

ROLE_LABEL = {
    "admin":    "Administrator",
    "teknisi":  "Teknisi Lab",
    "dosen":    "Dosen",
    "mahasiswa":"Mahasiswa",
}


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request):
    # Kalau sudah login, redirect ke halaman default sesuai role
    token = request.cookies.get("session_token")
    if token:
        user_data = decode_session_token(token)
        if user_data:
            # Ambil role dari data token untuk redirect
            redirect_url = redirect_default_page(user_data.get("role"))
            return RedirectResponse(redirect_url, status_code=302)
            
    return templates.TemplateResponse(
        request=request,
        name="pages/login.html",
        context={"error": None}
    )


@router.post("/login")
def login_post(
    request: Request,
    nim_nip: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db)
):
    # Cari user
    user = db.query(User).filter(
        User.nim_nip == nim_nip,
        User.aktif == True
    ).first()

    # Validasi user dan password
    if not user or not user.password_hash:
        return templates.TemplateResponse(
            request=request,
            name="pages/login.html",
            context={"error": "NIM/NIP atau password salah"}
        )

    if not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            request=request,
            name="pages/login.html",
            context={"error": "NIM/NIP atau password salah"}
        )

    # Cek role — hanya admin, teknisi, dosen yang boleh masuk dashboard
    if user.role not in ALLOWED_ROLES:
        return templates.TemplateResponse(
            request=request,
            name="pages/login.html",
            context={"error": "Akun Anda tidak memiliki akses ke dashboard"}
        )

    # Buat session token
    session_data = {
        "user_id": user.id,
        "nama":    user.nama,
        "nim_nip": user.nim_nip,
        "role":    user.role,
    }
    token = create_session_token(session_data)

    # Set cookie dan redirect sesuai role user
    redirect_url = redirect_default_page(user.role)
    response = RedirectResponse(redirect_url, status_code=302)
    response.set_cookie(
        key="session_token",
        value=token,
        httponly=True,       # tidak bisa diakses JavaScript
        max_age=86400,       # 24 jam
        samesite="lax",
        secure=False         # ganti True kalau sudah pakai HTTPS di production
    )
    return response


@router.get("/logout")
def logout():
    response = RedirectResponse("/login", status_code=302)
    response.delete_cookie("session_token")
    return response