"""
door_service.py — Process 2 (jalan di STB/bridge, BUKAN di server utama)
=========================================================
2 tanggung jawab dalam 1 service:
  1. Open Door manual dari dashboard (protokol web panel /csl/...)
  2. Sinkronisasi biometrik berdasar jadwal (protokol SOAP) — push info
     user / template fingerprint ke device, hapus kalau jadwal sudah
     tidak ada. Berjalan di background thread, terpisah dari
     x606_bridge.py supaya tidak mengganggu loop pull-log presensi
     yang harus tetap cepat & real-time.

Kenapa terpisah dari x606_bridge.py? Supaya x606_bridge.py tetap fokus
pull log presensi tanpa terganggu, dan supaya server utama (yang
mungkin TIDAK satu jaringan langsung dengan device X606-S) bisa minta
STB untuk membuka pintu / sync biometrik — karena cuma STB yang punya
akses jaringan langsung ke device.

Arsitektur Open Door:
    Dashboard → Server utama (/device-bridge/open-door) → HTTP →
    door_service.py (port 8081) → curl → X606-S web panel

Arsitektur Sync Biometrik (loop background, tanpa akses DB langsung —
semua data lewat HTTP ke server, SOAP hanya ke device lokal):
    door_service.py → GET /device-bridge/roster-ruangan  (siapa yang seharusnya ada)
                    → GET /device-bridge/user-templates  (ambil data template)
                    → SOAP set_user / set_user_template ke device LOKAL
                    → POST /device-bridge/report-sync-status (lapor hasil)
                    → GET /device-bridge/to-remove        (siapa yang harus dihapus)
                    → SOAP delete_user ke device LOKAL

Jalankan (biasanya lewat systemd, lihat door_service.service):
    python door_service.py

Environment variables (.env di folder yang sama):
    DEVICE_IP              — IP X606-S di jaringan lab
    DEVICE_COMKEY          — communication key SOAP device (biasanya "0")
    DEVICE_RUANGAN_ID      — ID ruangan ini di database server (buat roster query)
    DEVICE_WEBPANEL_USER   — username admin panel device (contoh: "1")
    DEVICE_WEBPANEL_PASS   — password admin panel device (contoh: "8888")
    DOOR_SERVICE_API_KEY   — kunci rahasia utk endpoint /open-door service ini
    DOOR_SERVICE_PORT      — port service ini (default 8081)
    SERVER_URL             — URL server utama (buat panggil roster/report/dst)
    BRIDGE_API_KEY         — API key ke server utama (sama dgn punya x606_bridge.py)
    BIOMETRIC_SYNC_INTERVAL— jeda antar putaran sync biometrik, detik (default 1800 = 30 menit)
"""

import os
import sys
import time
import threading
import requests
import logging
from fastapi import FastAPI, Header, HTTPException
from dotenv import load_dotenv

from zk_web import open_door, ZKWebError

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from app.services.x606_soap import X606SOAPClient

logging.basicConfig(level=logging.INFO, format="[%(asctime)s] %(levelname)s %(message)s", datefmt="%H:%M:%S")
log = logging.getLogger("door_service")

# ── Config: Open Door ──
DEVICE_IP            = os.getenv("DEVICE_IP", "10.17.44.162")
DEVICE_WEBPANEL_USER = os.getenv("DEVICE_WEBPANEL_USER", "1")
DEVICE_WEBPANEL_PASS = os.getenv("DEVICE_WEBPANEL_PASS", "8888")
DOOR_SERVICE_API_KEY = os.getenv("DOOR_SERVICE_API_KEY", "ganti-key-ini-di-env")
DOOR_SERVICE_PORT    = int(os.getenv("DOOR_SERVICE_PORT", "8081"))

# ── Config: Biometric Sync ──
DEVICE_COMKEY            = os.getenv("DEVICE_COMKEY", "0")
DEVICE_RUANGAN_ID        = int(os.getenv("DEVICE_RUANGAN_ID", "0"))
SERVER_URL               = os.getenv("SERVER_URL", "http://10.17.47.189:8080")
BRIDGE_API_KEY           = os.getenv("BRIDGE_API_KEY", "bridge-key-polsri-2026")
BIOMETRIC_SYNC_INTERVAL  = int(os.getenv("BIOMETRIC_SYNC_INTERVAL", "1800"))  # 30 menit
JEDA_ANTAR_USER          = 0.3  # detik, hindari membanjiri device dengan request beruntun

app = FastAPI(title="Door Service — X606-S Bridge Companion")


def verify_key(x_api_key: str = Header(...)):
    if x_api_key != DOOR_SERVICE_API_KEY:
        raise HTTPException(status_code=401, detail="API key salah")
    return x_api_key


@app.get("/health")
def health():
    return {"status": "ok", "device_ip": DEVICE_IP, "ruangan_id": DEVICE_RUANGAN_ID}


@app.post("/open-door")
def trigger_open_door(x_api_key: str = Header(...)):
    verify_key(x_api_key)
    try:
        berhasil = open_door(DEVICE_IP, DEVICE_WEBPANEL_USER, DEVICE_WEBPANEL_PASS)
    except ZKWebError as e:
        raise HTTPException(
            status_code=502,
            detail=f"{str(e).splitlines()[0]} | Cuplikan respons device: {e.response_snippet[:300]}",
        )
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gagal menghubungi device: {e}")

    if not berhasil:
        raise HTTPException(status_code=502, detail="Device tidak mengonfirmasi pintu terbuka")

    return {"pesan": "Pintu berhasil dibuka", "device_ip": DEVICE_IP}


@app.post("/provision-users")
def provision_users(payload: dict, x_api_key: str = Header(...)):
    """
    Dipanggil server saat admin MULAI sesi input finger. Push PIN+nama
    (TANPA template) ke device — supaya device siap terima pendaftaran
    fingerprint fisik untuk tiap user di daftar ini.
    Body: {"users": [{"pin": "101", "nama": "Andi"}, ...]}
    """
    verify_key(x_api_key)
    users = payload.get("users", [])
    if not users:
        raise HTTPException(status_code=400, detail="Daftar users kosong")

    client = X606SOAPClient(ip=DEVICE_IP, com_key=DEVICE_COMKEY)
    berhasil, gagal = [], []
    for u in users:
        try:
            ok = client.set_user(pin=str(u["pin"]), name=u["nama"])
            (berhasil if ok else gagal).append(u["pin"])
        except Exception as e:
            log.error(f"provision-users gagal untuk PIN {u.get('pin')}: {e}")
            gagal.append(u["pin"])
        time.sleep(JEDA_ANTAR_USER)

    return {"berhasil": berhasil, "gagal": gagal}


@app.post("/remove-users")
def remove_users(payload: dict, x_api_key: str = Header(...)):
    """
    Hapus sekumpulan user (by PIN) dari device ini via SOAP DeleteUser.
    Dipakai untuk:
      - Bersihkan device sehabis sesi input finger (peserta hanya perlu
        TERDAFTAR sementara di device supaya bisa taruh jari fisik —
        setelah template diekstrak & disimpan di server, entrinya di
        device ini tidak lagi diperlukan; push berikutnya ke device yang
        benar akan dilakukan oleh loop sync biometrik berbasis jadwal).
      - Hapus akses fisik user yang dihapus/dinonaktifkan di database
        server, supaya PIN itu tidak lagi bisa buka pintu di device ini
        walau datanya masih tersisa dari sinkronisasi sebelumnya.
    Body: {"pins": ["101", "102", ...]}
    """
    verify_key(x_api_key)
    pins = payload.get("pins", [])
    if not pins:
        raise HTTPException(status_code=400, detail="Daftar pins kosong")

    client = X606SOAPClient(ip=DEVICE_IP, com_key=DEVICE_COMKEY)
    berhasil, gagal = [], []
    for pin in pins:
        pin = str(pin)
        try:
            # DeleteTemplate dulu (jaga-jaga device menyimpan template
            # terpisah dari record user), baru DeleteUser untuk hapus
            # seluruh record-nya.
            client.delete_template(pin)
            ok = client.delete_user(pin)
            (berhasil if ok else gagal).append(pin)
        except Exception as e:
            log.error(f"remove-users gagal untuk PIN {pin}: {e}")
            gagal.append(pin)
        time.sleep(JEDA_ANTAR_USER)

    if berhasil:
        try:
            client.refresh_db()
        except Exception as e:
            log.warning(f"RefreshDB setelah remove-users gagal: {e}")

    log.info(f"remove-users: {len(berhasil)} berhasil, {len(gagal)} gagal")
    return {"berhasil": berhasil, "gagal": gagal}


@app.get("/device-users")
def list_device_users(x_api_key: str = Header(...)):
    """
    List semua user yang SAAT INI ada di device ini, ditandai apakah
    sudah punya fingerprint atau belum. Dipakai fitur "Transfer Data"
    di dashboard untuk memilih user yang mau dipindah dari alat ini ke
    alat lain.
    """
    verify_key(x_api_key)
    client = X606SOAPClient(ip=DEVICE_IP, com_key=DEVICE_COMKEY)
    try:
        users = client.get_all_users()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gagal membaca daftar user dari device: {e}")

    hasil = []
    for u in users:
        pin = u.get("PIN", "")
        if not pin:
            continue
        try:
            jumlah_template = len(client.get_all_templates(pin))
        except Exception as e:
            log.warning(f"Cek template PIN {pin} gagal: {e}")
            jumlah_template = 0
        hasil.append({
            "pin": pin,
            "nama": u.get("Name", ""),
            "punya_fingerprint": jumlah_template > 0,
            "jumlah_jari": jumlah_template,
        })
    return hasil


@app.post("/export-users")
def export_users(payload: dict, x_api_key: str = Header(...)):
    """
    Ambil data lengkap (nama + seluruh template fingerprint yang ada)
    untuk PIN-PIN yang diminta — dipakai fitur "Transfer Data" untuk
    membaca data dari alat SUMBER sebelum di-push ke alat TUJUAN.
    Kalau user belum punya fingerprint, "templates" akan kosong ([]) —
    tetap diikutkan supaya nama+PIN-nya tetap bisa dipindah/di-provision
    di alat tujuan (tinggal daftar jari fisik di sana).
    Body: {"pins": ["101", "102", ...]}
    """
    verify_key(x_api_key)
    pins = payload.get("pins", [])
    if not pins:
        raise HTTPException(status_code=400, detail="Daftar pins kosong")

    client = X606SOAPClient(ip=DEVICE_IP, com_key=DEVICE_COMKEY)
    try:
        nama_by_pin = {u.get("PIN", ""): u.get("Name", "") for u in client.get_all_users()}
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Gagal membaca daftar user dari device: {e}")

    hasil = []
    for pin in pins:
        pin = str(pin)
        try:
            templates = client.get_all_templates(pin)
        except Exception as e:
            log.warning(f"Ambil template PIN {pin} gagal: {e}")
            templates = []
        hasil.append({
            "pin": pin,
            "nama": nama_by_pin.get(pin, ""),
            "templates": [
                {
                    "finger_id": int(t["FingerID"]),
                    "size": t.get("Size"),
                    "valid": t.get("Valid", "1"),
                    "template": t.get("Template"),
                }
                for t in templates
            ],
        })
    return hasil


@app.post("/import-users")
def import_users(payload: dict, x_api_key: str = Header(...)):
    """
    Terima daftar user (nama + PIN, opsional template fingerprint) dan
    push ke device ini — sisi TUJUAN dari fitur "Transfer Data".
    Body: {"users": [{"pin": "101", "nama": "Andi", "templates": [...]}]}
    """
    verify_key(x_api_key)
    users = payload.get("users", [])
    if not users:
        raise HTTPException(status_code=400, detail="Daftar users kosong")

    client = X606SOAPClient(ip=DEVICE_IP, com_key=DEVICE_COMKEY)
    berhasil, gagal = [], []
    for u in users:
        pin = str(u.get("pin", "")).strip()
        nama = u.get("nama", "")
        if not pin:
            continue
        try:
            ok = client.set_user(pin=pin, name=nama)
            for t in u.get("templates", []):
                ok_t = client.set_user_template(
                    pin=pin,
                    finger_id=t["finger_id"],
                    size=t.get("size") or "0",
                    template=t["template"],
                    valid=t.get("valid", "1"),
                )
                ok = ok and ok_t
            (berhasil if ok else gagal).append(pin)
        except Exception as e:
            log.error(f"import-users gagal untuk PIN {pin}: {e}")
            gagal.append(pin)
        time.sleep(JEDA_ANTAR_USER)

    if berhasil:
        try:
            client.refresh_db()
        except Exception as e:
            log.warning(f"RefreshDB setelah import-users gagal: {e}")

    log.info(f"import-users: {len(berhasil)} berhasil, {len(gagal)} gagal")
    return {"berhasil": berhasil, "gagal": gagal}


@app.post("/extract-session-templates")
def extract_session_templates(payload: dict, x_api_key: str = Header(...)):
    """
    Dipanggil server saat admin klik "Selesaikan Sesi". Ambil semua
    template fingerprint (SOAP GetUserTemplate) untuk daftar PIN yang
    diberikan — dipakai setelah sesi enrollment fisik selesai.
    Body: {"pins": ["101", "102", ...]}
    Return: {"101": [{"finger_id":0,"size":"512","valid":"1","template":"..."}], "102": [...]}
    """
    verify_key(x_api_key)
    pins = payload.get("pins", [])
    if not pins:
        raise HTTPException(status_code=400, detail="Daftar pins kosong")

    client = X606SOAPClient(ip=DEVICE_IP, com_key=DEVICE_COMKEY)
    hasil = {}
    for pin in pins:
        try:
            templates = client.get_all_templates(str(pin))
            hasil[str(pin)] = [
                {"finger_id": int(t["FingerID"]), "size": t.get("Size"), "valid": t.get("Valid", "1"), "template": t.get("Template")}
                for t in templates
            ]
            log.info(f"extract-session-templates: PIN {pin} -> {len(templates)} template")
        except Exception as e:
            log.error(f"extract-session-templates gagal untuk PIN {pin}: {e}")
            hasil[str(pin)] = []
        time.sleep(JEDA_ANTAR_USER)

    return hasil


# ══════════════════════════════════════════════════════════
# BACKGROUND LOOP — Sinkronisasi biometrik berdasar jadwal
# ══════════════════════════════════════════════════════════

def _server_get(path: str, params: dict = None):
    try:
        r = requests.get(f"{SERVER_URL}{path}", headers={"X-API-Key": BRIDGE_API_KEY}, params=params, timeout=15)
        return r.json() if r.ok else []
    except Exception as e:
        log.error(f"GET {path} gagal: {e}")
        return []


def _server_post(path: str, data: dict):
    try:
        r = requests.post(f"{SERVER_URL}{path}", headers={"X-API-Key": BRIDGE_API_KEY}, json=data, timeout=15)
        return r.json() if r.ok else {}
    except Exception as e:
        log.error(f"POST {path} gagal: {e}")
        return {}


def _report_status(user_id: int, status: str):
    _server_post("/device-bridge/report-sync-status", {
        "ruangan_id": DEVICE_RUANGAN_ID, "user_id": user_id, "status": status,
    })


def biometric_sync_sekali_jalan():
    """1 putaran penuh: provision/push sesuai roster, hapus yang tidak perlu lagi."""
    if not DEVICE_RUANGAN_ID:
        log.warning("DEVICE_RUANGAN_ID belum di-set — skip sync biometrik.")
        return

    # Kalau ada sesi input finger yang sedang aktif di ruangan ini, SKIP
    # putaran ini sepenuhnya — biar tidak bentrok dengan proses manual admin.
    sesi = _server_get("/device-bridge/sesi-finger-aktif", {"ruangan_id": DEVICE_RUANGAN_ID})
    if isinstance(sesi, dict) and sesi.get("aktif"):
        log.info(f"Ada sesi input finger aktif di ruangan {DEVICE_RUANGAN_ID} — skip sync biometrik putaran ini.")
        return

    client = X606SOAPClient(ip=DEVICE_IP, com_key=DEVICE_COMKEY)

    # ── Bagian 1: push/provision sesuai roster ──
    roster = _server_get("/device-bridge/roster-ruangan", {"ruangan_id": DEVICE_RUANGAN_ID, "hari_kedepan": 3})
    log.info(f"Roster ruangan {DEVICE_RUANGAN_ID}: {len(roster)} user seharusnya ada")

    for u in roster:
        pin = str(u["pin"])
        try:
            if u["punya_template"]:
                detail = _server_get("/device-bridge/user-templates", {"pin": pin})
                templates = detail.get("templates", [])
                ok = client.set_user(pin=pin, name=u["nama"])
                for t in templates:
                    hasil_t = client.set_user_template(
                        pin=pin, finger_id=t["finger_id"],
                        size=t.get("size") or "0", template=t["template"],
                        valid=t.get("valid", "1"),
                    )
                    ok = ok and hasil_t
                if ok:
                    client.refresh_db()
                _report_status(u["user_id"], "synced" if ok else "gagal")
                log.info(f"  {'✓' if ok else '✗'} PIN {pin} ({u['nama']}) -> synced (+{len(templates)} template)")
            else:
                ok = client.set_user(pin=pin, name=u["nama"])
                _report_status(u["user_id"], "provisioned" if ok else "gagal")
                log.info(f"  {'✓' if ok else '✗'} PIN {pin} ({u['nama']}) -> provisioned (belum ada template)")
        except Exception as e:
            log.error(f"  ✗ PIN {pin}: {e}")
            _report_status(u["user_id"], "gagal")
        time.sleep(JEDA_ANTAR_USER)

    # ── Bagian 2: hapus yang jadwalnya sudah tidak ada ──
    to_remove = _server_get("/device-bridge/to-remove", {"ruangan_id": DEVICE_RUANGAN_ID, "hari_kedepan": 3})
    if to_remove:
        log.info(f"Perlu dihapus dari device: {len(to_remove)} user")
    for u in to_remove:
        pin = str(u["pin"])
        try:
            ok = client.delete_user(pin)
            if ok:
                client.refresh_db()
            _report_status(u["user_id"], "removed" if ok else "gagal")
            log.info(f"  {'✓' if ok else '✗'} PIN {pin} ({u['nama']}) -> dihapus dari device")
        except Exception as e:
            log.error(f"  ✗ PIN {pin}: {e}")
            _report_status(u["user_id"], "gagal")
        time.sleep(JEDA_ANTAR_USER)


def biometric_sync_loop():
    log.info(f"Biometric sync loop aktif — putaran tiap {BIOMETRIC_SYNC_INTERVAL} detik")
    while True:
        try:
            biometric_sync_sekali_jalan()
        except Exception as e:
            log.error(f"Biometric sync loop error: {e}")
        time.sleep(BIOMETRIC_SYNC_INTERVAL)


@app.on_event("startup")
def start_background_sync():
    t = threading.Thread(target=biometric_sync_loop, daemon=True)
    t.start()


if __name__ == "__main__":
    import uvicorn
    print(f"Door Service aktif — device target: {DEVICE_IP}, port: {DOOR_SERVICE_PORT}, ruangan_id: {DEVICE_RUANGAN_ID}")
    uvicorn.run(app, host="0.0.0.0", port=DOOR_SERVICE_PORT)