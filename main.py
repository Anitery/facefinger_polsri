from fastapi import FastAPI, Request, Depends, HTTPException
from fastapi.responses import RedirectResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from apscheduler.schedulers.background import BackgroundScheduler
from typing import Optional # Ditambahkan untuk kebutuhan route cetak laporan
import time

# Import database dan model
from app.database import engine, Base, SessionLocal, get_db

# Import semua routers aktif (Kategori A & B dihapus)
from app.routers import (
    auth, users, logs, inventaris, ruangan, jadwal,
    login as login_router, kamera as kamera_router,
    setup, stream as stream_router,
    absensi as absensi_router
)
from app.routers import device_bridge as device_bridge_router

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
    """Log semua request masuk — untuk debugging device bridge."""
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
app.include_router(logs.router)
app.include_router(inventaris.router)
app.include_router(ruangan.router)
app.include_router(jadwal.router)
app.include_router(kamera_router.router)
app.include_router(setup.router)
app.include_router(stream_router.router)
app.include_router(absensi_router.router)
app.include_router(device_bridge_router.router)


# ── Helper Functions ────────────────────────────────────────────────────

def get_session(request: Request):
    from app.services.auth_service import decode_session_token
    token = request.cookies.get("session_token")
    if not token:
        return None
    return decode_session_token(token)

def redirect_default_page(role: str) -> str:
    """Halaman default setelah login, sesuai role."""
    if role == "admin":
        return "/dashboard"
    elif role == "dosen":
        return "/dashboard/jadwal"
    elif role == "teknisi":
        return "/dashboard/ruangan"
    return "/dashboard"

def get_ruangan_list(db):
    from app.models.models import Ruangan as RuanganModel
    return db.query(RuanganModel).filter(
        RuanganModel.aktif == True
    ).order_by(RuanganModel.id).all()


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

scheduler.start()


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
        request=request, name="pages/index.html",
        context={"active": "dashboard", "user": user,
                 "ruangan_list": get_ruangan_list(db)}
    )

@app.get("/dashboard/jadwal")
def dashboard_jadwal(request: Request, db: Session = Depends(get_db)):
    user = get_session(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if user["role"] not in ("admin", "dosen"):
        return RedirectResponse(redirect_default_page(user["role"]), status_code=302)
    return templates.TemplateResponse(
        request=request, name="pages/jadwal.html",
        context={"active": "jadwal", "user": user,
                 "ruangan_list": get_ruangan_list(db)}
    )

@app.get("/dashboard/absensi")
def dashboard_absensi(request: Request, db: Session = Depends(get_db)):
    user = get_session(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if user["role"] not in ("admin", "dosen"):
        return RedirectResponse(redirect_default_page(user["role"]), status_code=302)
    return templates.TemplateResponse(
        request=request, name="pages/absensi.html",
        context={"active": "absensi", "user": user,
                 "ruangan_list": get_ruangan_list(db)}
    )

@app.get("/dashboard/log-akses")
def dashboard_log_akses(request: Request, db: Session = Depends(get_db)):
    user = get_session(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(
        request=request, name="pages/log_akses.html",
        context={"active": "log_akses", "user": user,
                 "ruangan_list": get_ruangan_list(db)}
    )

@app.get("/dashboard/ruangan")
def dashboard_ruangan(request: Request, db: Session = Depends(get_db)):
    user = get_session(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if user["role"] not in ("admin", "teknisi"):
        return RedirectResponse(redirect_default_page(user["role"]), status_code=302)
    return templates.TemplateResponse(
        request=request, name="pages/ruangan.html",
        context={"active": "ruangan", "user": user,
                 "ruangan_list": get_ruangan_list(db)}
    )

@app.get("/dashboard/pengguna")
def dashboard_pengguna(request: Request, db: Session = Depends(get_db)):
    user = get_session(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if user["role"] not in ("admin", "dosen", "teknisi"):
        return RedirectResponse(redirect_default_page(user["role"]), status_code=302)
    return templates.TemplateResponse(
        request=request, name="pages/pengguna.html",
        context={"active": "pengguna", "user": user,
                 "ruangan_list": get_ruangan_list(db)}
    )

@app.get("/dashboard/inventaris")
def dashboard_inventaris(request: Request, db: Session = Depends(get_db)):
    user = get_session(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(
        request=request, name="pages/inventaris.html",
        context={"active": "inventaris", "user": user,
                 "ruangan_list": get_ruangan_list(db)}
    )

@app.get("/dashboard/kamera")
def dashboard_kamera(request: Request, db: Session = Depends(get_db)):
    user = get_session(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(
        request=request, name="pages/kamera.html",
        context={"active": "kamera", "user": user,
                 "ruangan_list": get_ruangan_list(db)}
    )

@app.get("/dashboard/profil")
def dashboard_profil(request: Request, db: Session = Depends(get_db)):
    user = get_session(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(
        request=request, name="pages/profil.html",
        context={"active": "profil", "user": user,
                 "ruangan_list": get_ruangan_list(db)}
    )

@app.get("/dashboard/enroll-wajah")
def dashboard_enroll(request: Request, db: Session = Depends(get_db)):
    user = get_session(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if user["role"] != "admin":
        return RedirectResponse(redirect_default_page(user["role"]), status_code=302)
    return templates.TemplateResponse(
        request=request, name="pages/enroll_wajah.html",
        context={"active": "enroll", "user": user,
                 "ruangan_list": get_ruangan_list(db)}
    )

# ── Absensi & Laporan Routes ───────────────────────────────────────────────────

@app.get("/absensi/cetak-laporan")
def cetak_laporan_bulanan(
    request: Request,
    ruangan_id: int,
    bulan: str,
    kelas: Optional[str] = None,
    jadwal_ids: Optional[str] = None,
    db: Session = Depends(get_db)
):
    user = get_session(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    if user["role"] not in ("admin", "dosen"):
        return RedirectResponse(redirect_default_page(user["role"]), status_code=302)

    from sqlalchemy.orm import joinedload
    from collections import defaultdict
    from app.models.models import JadwalRuangan, Absensi, Ruangan, User

    q = db.query(JadwalRuangan).options(
        joinedload(JadwalRuangan.mahasiswa_diizinkan)
    ).filter(
        JadwalRuangan.ruangan_id == ruangan_id,
        JadwalRuangan.tanggal.startswith(bulan),
    )
    if kelas:
        q = q.filter(JadwalRuangan.kelas == kelas)
    if user["role"] == "dosen":
        q = q.filter(JadwalRuangan.dosen == user["nama"])

    if jadwal_ids:
        try:
            ids = [int(x) for x in jadwal_ids.split(",") if x.strip()]
            q = q.filter(JadwalRuangan.id.in_(ids))
        except ValueError:
            raise HTTPException(status_code=400, detail="Format jadwal_ids tidak valid")

    jadwal_list = q.order_by(JadwalRuangan.tanggal).all()
    if not jadwal_list:
        raise HTTPException(404, "Tidak ada data jadwal pada periode ini")

    ruangan = db.query(Ruangan).filter(Ruangan.id == ruangan_id).first()

    STATUS_LABEL_PENDEK = {"hadir": "H", "terlambat": "T", "tidak_hadir": "A", "izin": "I"}
    BULAN_NAMA = {
        "01": "Januari", "02": "Februari", "03": "Maret", "04": "April",
        "05": "Mei", "06": "Juni", "07": "Juli", "08": "Agustus",
        "09": "September", "10": "Oktober", "11": "November", "12": "Desember"
    }
    thn, bln = bulan.split("-")

    # ── Kelompokkan jadwal per (dosen, kelas) — supaya tiap kelas
    # ── tampil sebagai blok laporan terpisah, bukan tergabung ──
    groups_map = defaultdict(list)
    for j in jadwal_list:
        key = (j.dosen or "-", j.kelas or "-")
        groups_map[key].append(j)

    ordered_keys = sorted(groups_map.keys(), key=lambda k: (k[0], k[1]))

    print_pages = []
    for key in ordered_keys:
        dosen_nama_grp, kelas_grp = key
        jadwals_grp = groups_map[key]

        tanggal_list_grp = [j.tanggal[8:10] + "/" + j.tanggal[5:7] for j in jadwals_grp]

        mhs_set = {}
        for j in jadwals_grp:
            if j.mahasiswa_diizinkan:
                for m in j.mahasiswa_diizinkan:
                    mhs_set[m.id] = m
            else:
                q_mhs = db.query(User).filter(User.role == "mahasiswa", User.aktif == True)
                if j.kelas:
                    q_mhs = q_mhs.filter(User.kelas == j.kelas)
                for m in q_mhs.all():
                    mhs_set[m.id] = m
        mhs_list_grp = sorted(mhs_set.values(), key=lambda m: m.nama)

        if not mhs_list_grp:
            continue  # lewati kelompok tanpa mahasiswa

        jadwal_ids_grp = [j.id for j in jadwals_grp]
        absensi_rows_grp = db.query(Absensi).filter(Absensi.jadwal_id.in_(jadwal_ids_grp)).all()
        absensi_map_grp = {(a.jadwal_id, a.user_id): a.status for a in absensi_rows_grp}

        rows_grp = []
        for i, m in enumerate(mhs_list_grp, 1):
            cells, cnt = [], {"hadir": 0, "terlambat": 0, "tidak_hadir": 0, "izin": 0}
            for j in jadwals_grp:
                st = absensi_map_grp.get((j.id, m.id))
                cells.append(STATUS_LABEL_PENDEK.get(st, "-"))
                if st in cnt:
                    cnt[st] += 1
            rows_grp.append({"no": i, "nim": m.nim_nip or "-", "nama": m.nama, "cells": cells, "cnt": cnt})

        dosen_user_grp = None
        if dosen_nama_grp != "-":
            dosen_user_grp = db.query(User).filter(
                User.nama == dosen_nama_grp, User.role == "dosen"
            ).first()

        chunks = [rows_grp[i:i + 30] for i in range(0, len(rows_grp), 30)] or [[]]

        for ci, chunk in enumerate(chunks):
            print_pages.append({
                "kelas":                  kelas_grp,
                "dosen_nama":             dosen_nama_grp,
                "dosen_nim_nip":          dosen_user_grp.nim_nip if dosen_user_grp else None,
                "tanggal_list":           tanggal_list_grp,
                "rows":                   chunk,
                "is_last_chunk_of_group": (ci == len(chunks) - 1),
            })

    for idx, p in enumerate(print_pages):
        p["is_last_page"] = (idx == len(print_pages) - 1)

    if not print_pages:
        raise HTTPException(
            400,
            "Belum ada mahasiswa terdaftar pada jadwal-jadwal di periode ini — "
            "laporan tidak dapat dibuat"
        )

    # Cari Ketua Jurusan — Dr. Slamet Widodo (NIP konsisten di seed)
    ketua_jurusan = db.query(User).filter(
        User.nim_nip == "197305162002121001"
    ).first()
    
    # Kalau tidak ketemu fallback ke admin pertama
    if not ketua_jurusan:
        ketua_jurusan = db.query(User).filter(
            User.role == "admin"
        ).first()

    return templates.TemplateResponse(
        request=request,
        name="pages/cetak_laporan.html",
        context={
            "ruangan":       ruangan,
            "bulan_label":   f"{BULAN_NAMA.get(bln, bln)} {thn}",
            "print_pages":   print_pages,
            "ketua_jurusan": ketua_jurusan.nama if ketua_jurusan else "Ketua Jurusan",
            "ketua_nip":     ketua_jurusan.nim_nip if ketua_jurusan else "",
        }
    )

@app.get("/dashboard/status-lab")
def dashboard_status_lab(request: Request, db: Session = Depends(get_db)):
    user = get_session(request)
    if not user:
        return RedirectResponse("/login", status_code=302)
    return templates.TemplateResponse(
        request=request, name="pages/status_lab.html",
        context={"active": "status_lab", "user": user,
                 "ruangan_list": get_ruangan_list(db)}
    )

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