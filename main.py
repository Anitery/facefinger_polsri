from fastapi import FastAPI, Request, Depends
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler

# Import database dan model
from app.database import engine, Base, SessionLocal, get_db

# Import semua routers
from app.routers import (
    auth, users, logs, inventaris, ruangan, jadwal,
    login as login_router, kamera as kamera_router,
    setup, stream as stream_router,
    absensi as absensi_router  # Router baru
)

# Inisiasi database
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Smart Door Lock API",
    description="Sistem Smart Door Lock Ruang Multimedia Polsri",
    version="1.0.0"
)

# ── Middleware ───────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Static & Templates ───────────────────────────────────
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# ── Routers ───────────────────────────────────────────────
app.include_router(login_router.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(logs.router)
app.include_router(inventaris.router)
app.include_router(ruangan.router)
app.include_router(jadwal.router)
app.include_router(kamera_router.router)
app.include_router(setup.router)
app.include_router(stream_router.router)
app.include_router(absensi_router.router) # Include router absensi


# ── Scheduler: Tutup Absensi Otomatis ───────────────────
def job_tutup_absensi():
    """
    Cek setiap menit — jika ada jadwal yang baru selesai (jam_selesai == sekarang),
    tutup absensinya otomatis.
    """
    from app.models.models import JadwalRuangan
    from app.services.absensi_service import tutup_absensi_jadwal

    db = SessionLocal()
    try:
        now      = __import__('datetime').datetime.now()
        today    = now.strftime("%Y-%m-%d")
        now_time = now.strftime("%H:%M")

        # Jadwal yang jam_selesai tepat sekarang (dalam window 1 menit)
        jadwal_selesai = db.query(JadwalRuangan).filter(
            JadwalRuangan.tanggal    == today,
            JadwalRuangan.jam_selesai == now_time,
        ).all()

        for j in jadwal_selesai:
            count = tutup_absensi_jadwal(db, j.id)
            if count > 0:
                print(
                    f"[SCHEDULER] Absensi jadwal #{j.id} "
                    f"'{j.nama_kegiatan}' ditutup — "
                    f"{count} tidak hadir"
                )
    except Exception as e:
        print(f"[SCHEDULER] Error: {e}")
    finally:
        db.close()

# Jalankan scheduler
scheduler = BackgroundScheduler()
scheduler.add_job(job_tutup_absensi, "interval", minutes=1)
scheduler.start()

# ── Event Shutdown ──────────────────────────────────────
@app.on_event("shutdown")
def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown()


# ── Helper: Cek Session ───────────────────────────────────
def get_session(request: Request):
    from app.services.auth_service import decode_session_token
    token = request.cookies.get("session_token")
    if not token:
        return None
    return decode_session_token(token)

# ── Helper: Ambil Daftar Ruangan ─────────────────────────
def get_ruangan_list(db):
    from app.models.models import Ruangan as RuanganModel
    return db.query(RuanganModel).filter(
        RuanganModel.aktif == True
    ).order_by(RuanganModel.id).all()


# ── Dashboard Routes ────────────────────────────────────└───────────────────────────────────────────────────────────
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

# ── Route Absensi Baru ──────────────────────────────────
@app.get("/dashboard/absensi")
def dashboard_absensi(request: Request, db: Session = Depends(get_db)):
    user = get_session(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="pages/absensi.html",
        context={"active": "absensi", "user": user,
                 "ruangan_list": get_ruangan_list(db)}
    )

# ── Root & Health ──────────────────────────────────────
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