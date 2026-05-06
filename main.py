from fastapi import FastAPI, Request, Depends
from sqlalchemy.orm import Session
from app.database import get_db
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.database import engine, Base
from app.routers import auth, users, logs, inventaris, ruangan, jadwal, \
                        login as login_router, kamera as kamera_router, setup

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Smart Door Lock API",
    description="Sistem Smart Door Lock Ruang Multimedia Polsri",
    version="1.0.0"
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# ── Routers ───────────────────────────────────────────────
app.include_router(login_router.router)   # login duluan
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(logs.router)
app.include_router(inventaris.router)
app.include_router(ruangan.router)
app.include_router(jadwal.router)
app.include_router(kamera_router.router)
app.include_router(setup.router)


# ── Helper: cek session ───────────────────────────────────
def get_session(request: Request):
    from app.services.auth_service import decode_session_token
    token = request.cookies.get("session_token")
    if not token:
        return None
    return decode_session_token(token)

# ── Helper: ambil daftar ruangan untuk dropdown ───────────
def get_ruangan_list(db):
    from app.models.models import Ruangan as RuanganModel
    return db.query(RuanganModel).filter(
        RuanganModel.aktif == True
    ).order_by(RuanganModel.id).all()


# ── Dashboard routes ──────────────────────────────────────
@app.get("/dashboard")
def dashboard_home(request: Request, db: Session = Depends(get_db)):
    user = get_session(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="pages/index.html",
        context={"active": "home", "user": user,
                 "ruangan_list": get_ruangan_list(db)}
    )

@app.get("/dashboard/log-akses")
def dashboard_log(request: Request, db: Session = Depends(get_db)):
    user = get_session(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="pages/log_akses.html",
        context={"active": "log", "user": user,
                 "ruangan_list": get_ruangan_list(db)}
    )

@app.get("/dashboard/pengguna")
def dashboard_pengguna(request: Request, db: Session = Depends(get_db)):
    user = get_session(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if user.get("role") != "admin":
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="pages/pengguna.html",
        context={"active": "pengguna", "user": user,
                 "ruangan_list": get_ruangan_list(db)}
    )

@app.get("/dashboard/inventaris")
def dashboard_inventaris(request: Request, db: Session = Depends(get_db)):
    user = get_session(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="pages/inventaris.html",
        context={"active": "inventaris", "user": user,
                 "ruangan_list": get_ruangan_list(db)}
    )

@app.get("/dashboard/ruangan")
def dashboard_ruangan(request: Request, db: Session = Depends(get_db)):
    user = get_session(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if user.get("role") != "admin":
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="pages/ruangan.html",
        context={"active": "ruangan", "user": user,
                 "ruangan_list": get_ruangan_list(db)}
    )

@app.get("/dashboard/kamera")
def dashboard_kamera(request: Request, db: Session = Depends(get_db)):
    user = get_session(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="pages/kamera.html",
        context={"active": "kamera", "user": user,
                 "ruangan_list": get_ruangan_list(db)}
    )

@app.get("/dashboard/jadwal")
def dashboard_jadwal(request: Request, db: Session = Depends(get_db)):
    user = get_session(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="pages/jadwal.html",
        context={"active": "jadwal", "user": user,
                 "ruangan_list": get_ruangan_list(db)}
    )

@app.get("/dashboard/profil")
def dashboard_profil(request: Request, db: Session = Depends(get_db)):
    user = get_session(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="pages/profil.html",
        context={"active": "profil", "user": user,
                 "ruangan_list": get_ruangan_list(db)}
    )

@app.get("/dashboard/enroll-wajah")
def dashboard_enroll(request: Request, db: Session = Depends(get_db)):
    user = get_session(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if user.get("role") != "admin":
        return RedirectResponse("/dashboard", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="pages/enroll_wajah.html",
        context={"active": "enroll", "user": user,
                 "ruangan_list": get_ruangan_list(db)}
    )

@app.get("/")
def root():
    return {
        "sistem": "Smart Door Lock",
        "versi":  "1.0.0",
        "docs":   "/docs",
        "dashboard": "/dashboard"
    }

@app.get("/health")
def health_check():
    return {"status": "ok"}
