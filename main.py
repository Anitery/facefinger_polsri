from fastapi import FastAPI, Request, Depends
from fastapi.responses import RedirectResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler
import time

# Import database dan model
from app.database import engine, Base, SessionLocal, get_db

# Import semua routers
from app.routers import (
    auth, users, logs, inventaris, ruangan, jadwal,
    login as login_router, kamera as kamera_router,
    setup, stream as stream_router,
    absensi as absensi_router  # Router baru
)
from app.routers import device as device_router
from app.routers import x606 as x606_router
from app.routers import x606_lab as x606_lab_router  # ←TAMBAHKAN
from app.routers import device_bridge as device_bridge_router

# Import model X606 untuk trigger create_all
from app.models import x606_models  # ←TAMBAHKAN

# Import services
from app.services.x606_scheduler import start_x606_scheduler

# Inisiasi database
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Smart Door Lock API",
    description="Sistem Smart Door Lock Ruang Multimedia Polsri",
    version="1.0.0"
)

# ── Middleware ───────────────────────────────────────────────
@app.middleware("http")
async def log_semua_request(request: Request, call_next):
    """Log semua request masuk — untuk debug device ADMS."""
    body = await request.body()
    
    print(f"\n{'='*60}")
    print(f"[REQUEST] {request.method} {request.url}")
    print(f"[HEADERS] {dict(request.headers)}")
    print(f"[PARAMS]  {dict(request.query_params)}")
    if body:
        print(f"[BODY]    {body.decode('utf-8', errors='ignore')[:500]}")
    print(f"{'='*60}")
    
    # Rebuild body agar bisa dibaca lagi oleh endpoint
    async def receive():
        return {"type": "http.request", "body": body}
    
    request._receive = receive
    response = await call_next(request)
    return response

# ── Static & Templates ───────────────────────────────────
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# ── Routers ───────────────────────────────────────────────
app.include_router(login_router.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(device_router.router)
app.include_router(logs.router)
app.include_router(inventaris.router)
app.include_router(ruangan.router)
app.include_router(jadwal.router)
app.include_router(kamera_router.router)
app.include_router(setup.router)
app.include_router(stream_router.router)
app.include_router(absensi_router.router)
app.include_router(x606_router.router)
app.include_router(x606_lab_router.router)  # ←TAMBAHKAN
app.include_router(device_bridge_router.router)

# ── Helper Functions ────────────────────────────────────────────────────

def get_session(request: Request):
    from app.services.auth_service import decode_session_token
    token = request.cookies.get("session_token")
    if not token:
        return None
    return decode_session_token(token)

def get_ruangan_list(db):
    from app.models.models import Ruangan as RuanganModel
    return db.query(RuanganModel).filter(
        RuanganModel.aktif == True
    ).order_by(RuanganModel.id).all()


# ── X606 Scheduler Jobs ─────────────────────────────────────────────────

def job_pull_x606():
    """
    Tarik log dari semua X606-S aktif setiap 2 menit.
    """
    from app.models.x606_models import X606Device
    from app.services.x606_service import X606LabService

    print("[X606 SCHEDULER] Memulai pull logs...")
    
    db = SessionLocal()
    try:
        devices = db.query(X606Device).filter(
            X606Device.is_active == True
        ).all()

        if not devices:
            print("[X606 SCHEDULER] Tidak ada device aktif")
            return

        svc = X606LabService(db)
        for dev in devices:
            try:
                result = svc.pull_logs_from_device(dev.device_id)
                if result["success"] and result.get("new_records", 0) > 0:
                    print(
                        f"[X606] {dev.device_id}: "
                        f"{result['new_records']} log baru - "
                        f"{result['message']}"
                    )
            except Exception as e:
                print(f"[X606 ERROR] {dev.device_id}: {e}")
    except Exception as e:
        print(f"[X606 SCHEDULER ERROR] {e}")
    finally:
        db.close()


def job_sync_jadwal_x606():
    """
    Sync jadwal ke semua device X606-S setiap 5 menit.
    """
    from app.models.x606_models import X606Device, X606JadwalKBM
    from app.models.x606_models import HariEnum
    from datetime import datetime
    from app.services.x606_service import X606LabService

    print("[X606 SCHEDULER] Memulai sync jadwal...")
    
    db = SessionLocal()
    try:
        # Cari jadwal hari ini
        hari_ini = datetime.now().strftime("%A")
        hari_map = {
            "Monday": "SENIN", "Tuesday": "SELASA", "Wednesday": "RABU",
            "Thursday": "KAMIS", "Friday": "JUMAT", "Saturday": "SABTU", "Sunday": "Minggu"
        }
        hari_db = hari_map.get(hari_ini, "SENIN")
        
        jadwals = db.query(X606JadwalKBM).filter(
            X606JadwalKBM.hari == hari_db,
            X606JadwalKBM.is_active == True
        ).all()
        
        devices = db.query(X606Device).filter(
            X606Device.is_active == True
        ).all()
        
        svc = X606LabService(db)
        
        for dev in devices:
            for jadwal in jadwals:
                try:
                    result = svc.sync_users_to_device(dev.device_id, jadwal.id)
                    if result["success"]:
                        print(f"[X606 SYNC] {dev.device_id} <- Jadwal #{jadwal.id}")
                except Exception as e:
                    print(f"[X606 SYNC ERROR] {dev.device_id}: {e}")
                    
    except Exception as e:
        print(f"[X606 SYNC SCHEDULER ERROR] {e}")
    finally:
        db.close()


# ── Absensi Otomatis Scheduler Job ──────────────────────────────────────

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


# ── Setup Scheduler ───────────────────────────────────────────────────────

scheduler = BackgroundScheduler()

# Job: Tutup Absensi Otomatis (setiap 1 menit)
scheduler.add_job(
    func=job_tutup_absensi,
    trigger="interval",
    minutes=1,
    id="tutup_absensi",
    replace_existing=True
)

# Job: Pull X606 Logs (setiap 2 menit) ←TAMBAHKAN
scheduler.add_job(
    func=job_pull_x606,
    trigger="interval",
    minutes=2,
    id="x606_pull_logs",
    replace_existing=True
)

# Job: Sync Jadwal X606 (setiap 5 menit) ←TAMBAHKAN
scheduler.add_job(
    func=job_sync_jadwal_x606,
    trigger="interval",
    minutes=5,
    id="x606_sync_jadwal",
    replace_existing=True
)

scheduler.start()

@app.on_event("startup")
def startup_event():
    """Start X606 background scheduler jika ada."""
    start_x606_scheduler()
    print("[STARTUP] Scheduler X606 dimulai")


# ── Event Shutdown ──────────────────────────────────────────────────────

@app.on_event("shutdown")
def shutdown_scheduler():
    if scheduler.running:
        scheduler.shutdown()
    print("[SHUTDOWN] Scheduler dihentikan")


# ── Dashboard Routes ────────────────────────────────────────────────────────

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

@app.get("/dashboard/device")
def dashboard_device(request: Request, db: Session = Depends(get_db)):
    user = get_session(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(
        request=request,
        name="pages/device_status.html",
        context={"active": "device", "user": user,
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


# ── iWatch Catchall ────────────────────────────────────────────────────────

@app.api_route(
    "/iclock/{full_path:path}",
    methods=["GET", "POST"],
    include_in_schema=False
)
async def iclock_catchall(full_path: str, request: Request):
    """Catch semua request ke /iclock/* yang tidak tertangkap router."""
    body   = await request.body()
    params = dict(request.query_params)
    
    print(f"\n[CATCHALL] Path  : /iclock/{full_path}")
    print(f"[CATCHALL] Method: {request.method}")
    print(f"[CATCHALL] Params: {params}")
    print(f"[CATCHALL] Body  : {body.decode('utf-8', errors='ignore')[:300]}")
    
    return PlainTextResponse("OK")


# ── Root & Health ────────────────────────────────────────────────────────

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
    return {"status": "ok", "service": "SmartDoorLock"}