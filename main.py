from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.database import engine, Base
from app.routers import auth, users, logs, inventaris, ruangan

Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Smart Door Lock API",
    description="Sistem Smart Door Lock Ruang Multimedia Polsri",
    version="1.0.0"
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

# API routers
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(logs.router)
app.include_router(inventaris.router)
app.include_router(ruangan.router)


# ── Dashboard routes ──────────────────────────────────────────────────────
@app.get("/dashboard")
def dashboard_home(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="pages/index.html",
        context={"active": "home"}
    )

@app.get("/dashboard/log-akses")
def dashboard_log(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="pages/log_akses.html",
        context={"active": "log"}
    )

@app.get("/dashboard/pengguna")
def dashboard_pengguna(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="pages/pengguna.html",
        context={"active": "pengguna"}
    )

@app.get("/dashboard/inventaris")
def dashboard_inventaris(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="pages/inventaris.html",
        context={"active": "inventaris"}
    )

@app.get("/dashboard/kamera")
def dashboard_kamera(request: Request):
    return templates.TemplateResponse(
        request=request,
        name="pages/kamera.html",
        context={"active": "kamera"}
    )


@app.get("/")
def root():
    return {
        "sistem": "Smart Door Lock",
        "versi": "1.0.0",
        "docs": "/docs",
        "dashboard": "/dashboard"
    }

@app.get("/health")
def health_check():
    return {"status": "ok"}