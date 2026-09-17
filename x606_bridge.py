"""
X606-S Local Bridge — Smart Door Lock Polsri
Berjalan di STB Linux 24/7 di jaringan lab.

Alur kerja:
  1. Sync user + timezone ke device (awal + periodik)
  2. Pull log absensi dari device → kirim ke server rack lokal
  3. Server rack validasi jadwal KBM + catat absensi otomatis

Jalankan:
    python x606_bridge.py
"""

import os
import sys
import time
import requests
import logging
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv

load_dotenv()

# Konstanta WIB
WIB = timezone(timedelta(hours=7))

def now_wib() -> datetime:
    """Selalu kembalikan waktu WIB, apapun timezone STB."""
    return datetime.now(WIB)

# ── Konfigurasi ──────────────────────────────────────────
DEVICE_IP         = os.getenv("DEVICE_IP",         "10.17.44.162")
DEVICE_COMKEY     = os.getenv("DEVICE_COMKEY",     "0")
DEVICE_RUANGAN_ID = int(os.getenv("DEVICE_RUANGAN_ID", "7"))
SERVER_URL        = os.getenv("SERVER_URL",        "http://localhost:8000")
BRIDGE_API_KEY    = os.getenv("BRIDGE_API_KEY",    "bridge-key-polsri-2026")
PULL_INTERVAL     = int(os.getenv("PULL_INTERVAL", "30"))
SYNC_INTERVAL     = int(os.getenv("SYNC_INTERVAL", "10"))
DEVICE_SN         = os.getenv("DEVICE_SN",         "X606S-006")

HEADERS = {
    "X-API-Key":    BRIDGE_API_KEY,
    "Content-Type": "application/json"
}

# ── Logging ke systemd journal ───────────────────────────
logging.basicConfig(
    level   = logging.INFO,
    format  = "[%(asctime)s] %(levelname)s %(message)s",
    datefmt = "%H:%M:%S"
)
log = logging.getLogger("bridge")

# ── Import SOAP client ───────────────────────────────────
sys.path.insert(0, os.path.dirname(__file__))
from app.services.x606_soap import X606SOAPClient

# Log yang sudah diproses session ini
_processed: set = set()


# ══════════════════════════════════════════════════════════
# HELPER: Komunikasi ke server rack (FastAPI lokal)
# ══════════════════════════════════════════════════════════

def server_get(path: str, params: dict = None) -> dict:
    try:
        r = requests.get(
            f"{SERVER_URL}{path}",
            headers=HEADERS, params=params, timeout=15
        )
        return r.json() if r.ok else {}
    except Exception as e:
        log.error(f"GET {path} gagal: {e}")
        return {}


def server_post(path: str, data: dict) -> dict:
    try:
        r = requests.post(
            f"{SERVER_URL}{path}",
            headers=HEADERS, json=data, timeout=30
        )
        
        log.info(f"POST {path} status={r.status_code}")
        
        if not r.ok:
            log.error(f"Response error {r.status_code}: {r.text[:500]}")
            return {}
            
        return r.json()
        
    except Exception as e:
        log.error(f"POST {path} exception: {e}")
        return {}


# ══════════════════════════════════════════════════════════
# BAGIAN A — Sync user + timezone ke device
# ══════════════════════════════════════════════════════════

'''ZONE_OPEN_ID     = int(os.getenv("ZONE_OPEN_ID",     "1"))
ZONE_BLOCKED_ID  = int(os.getenv("ZONE_BLOCKED_ID",  "2"))
GROUP_TERKONTROL = 1   # ← default device, fail-safe tertutup (mahasiswa)
GROUP_BEBAS      = 2   # ← eksplisit via bridge (admin/teknisi/dosen)

def get_access_config(user: dict, jadwals: list) -> tuple[int, int]:
    role  = user.get("role", "mahasiswa")
    fp_id = str(user.get("fingerprint_id", "")).strip()

    if role in ("admin", "teknisi", "dosen"):
        return GROUP_BEBAS, ZONE_OPEN_ID

    def time_to_minutes(t_str):
        try:
            parts = str(t_str).split(":")
            return int(parts[0]) * 60 + int(parts[1])
        except (ValueError, TypeError, IndexError):
            return 0

    now_minutes = time_to_minutes(datetime.now().strftime("%H:%M"))

    for j in jadwals:
        allowed_fps = [str(x).strip() for x in (j.get("fp_ids_diizinkan") or [])]
        start_min   = time_to_minutes(j.get("jam_mulai", "00:00"))
        end_min     = time_to_minutes(j.get("jam_selesai", "00:00"))

        if not (start_min <= now_minutes <= end_min):
            continue  # bukan jadwal yang sedang aktif, skip

        # Jadwal terbuka (tanpa daftar mahasiswa spesifik) → semua boleh
        if not allowed_fps:
            return GROUP_TERKONTROL, ZONE_OPEN_ID

        # Jadwal tertutup → cek keanggotaan
        if fp_id in allowed_fps:
            return GROUP_TERKONTROL, ZONE_OPEN_ID

    return GROUP_TERKONTROL, ZONE_BLOCKED_ID

def sync_users(client: X606SOAPClient):
    """Sync semua user dari server rack ke device dengan timezone dan group yang benar."""
    log.info("── Sync user ke device...")

    users   = server_get("/device-bridge/users")
    jadwals = server_get(
        "/device-bridge/jadwal-hari-ini",
        {"ruangan_id": DEVICE_RUANGAN_ID}
    )

    if not users:
        log.warning("Tidak ada user dari server rack")
        return 0

    if isinstance(jadwals, dict):
        jadwals = []

    log.info(f"  {len(users)} user | {len(jadwals)} jadwal hari ini")

    synced = failed = 0
    for u in users:
        fp_id = str(u.get("fingerprint_id", ""))
        nama  = u.get("nama", "")
        role  = u.get("role", "mahasiswa")
        
        # Ambil setelan akses baru (Group & Zone)
        group, zone = get_access_config(u, jadwals)  
        priv = "14" if role in ("admin", "teknisi") else "0"

        try:
            ok = client.set_user(
                pin=fp_id, name=nama, 
                privilege=priv, group=group,
                tz1=zone, tz2=zone, tz3=zone   # ← semua slot sama, hindari OR-fallback
            )
            if ok:
                synced += 1
                log.info(
                    f"  ✓ [{role:10}] {nama:25} "
                    f"FP:{fp_id:3} GRP:{group} ZONE:{zone}"
                )
            else:
                failed += 1
                log.warning(f"  ✗ {nama} — set_user gagal")
        except Exception as e:
            failed += 1
            log.error(f"  ✗ {nama}: {e}")
            
    if synced > 0:
        client.refresh_db()
        log.info(f"  RefreshDB OK — {synced} user aktif")

    log.info(f"  Sync selesai: {synced} OK, {failed} gagal")
    return synced

'''
# ══════════════════════════════════════════════════════════
# BAGIAN B — Pull log dari device → server rack
# ══════════════════════════════════════════════════════════

def pull_logs(client: X606SOAPClient) -> int:
    """Pull SOAP log dari device, filter baru, kirim ke server rack."""
    try:
        logs = client.get_logs("All")
    except Exception as e:
        log.error(f"Pull SOAP gagal: {e}")
        return 0

    if not logs:
        return 0

    # Filter yang belum diproses
    new_logs = []
    for l in logs:
        key = f"{l.get('PIN','')}|{l.get('DateTime','')}"
        if key not in _processed:
            new_logs.append(l)

    if not new_logs:
        log.debug(f"Semua {len(logs)} log sudah diproses")
        return 0

    log.info(f"Mengirim {len(new_logs)} log baru ke server rack...")

    payload = {
        "ruangan_id": DEVICE_RUANGAN_ID,
        "device_sn":  DEVICE_SN,
        "logs": [
            {
                "pin":      str(l.get("PIN", "")),
                "datetime": l.get("DateTime", "") + "+07:00",
                "verified": int(l.get("Verified", 0)),
                "status":   int(l.get("Status", 0)),
                "workcode": str(l.get("WorkCode", "0")),
            }
            for l in new_logs
        ]
    }

    # Debug: tampilkan setiap log
    for l in new_logs:
        pin = l.get("PIN", "")
        v = int(l.get("Verified", 0))
        method = {
            0: "Password", 1: "Fingerprint", 2: "Card",
            3: "Password", 4: "Face", 5: "Face", 6: "Face",
            15: "Face", 200: "Other"
        }.get(v, f"Unknown({v})")
        log.info(f"  → PIN:{pin} Method:{method}(verified={v}) DT:{l.get('DateTime')}")

    res = server_post("/device-bridge/push-logs", payload)
    
    if res:
        berhasil = res.get("berhasil", 0)
        ditolak  = res.get("ditolak", 0)
        duplikat = res.get("duplikat", 0)
        error    = res.get("error", 0)
        total    = res.get("total", 0)
        
        log.info(
            f"  Server: {berhasil} berhasil | {ditolak} ditolak | "
            f"{duplikat} duplikat | {error} error (total:{total})"
        )
        
        if berhasil + ditolak + duplikat == 0 and total > 0:
            log.error("  ⚠️ ANOMALI: Semua log error atau tidak diproses!")
            log.error("  Cek log backend untuk detail error.")

        # Tandai sudah diproses
        for l in new_logs:
            key = f"{l.get('PIN','')}|{l.get('DateTime','')}"
            _processed.add(key)
        return berhasil + ditolak

    return 0


# ══════════════════════════════════════════════════════════
# BAGIAN C — Sync enrollment (fingerprint mapping)
# ══════════════════════════════════════════════════════════

def sync_enrollment(client: X606SOAPClient):
    """
    Ambil semua user di device, kirim ke server rack untuk
    verifikasi mapping fingerprint_id.
    Berguna saat ada pendaftaran baru di device.
    """
    try:
        device_users = client.get_all_users()
        if not device_users:
            return

        payload = {
            "device_sn":   DEVICE_SN,
            "ruangan_id":  DEVICE_RUANGAN_ID,
            "device_users": [
                {
                    "pin":  u.get("PIN", ""),
                    "name": u.get("Name", ""),
                    "pin2": u.get("PIN2", ""),
                }
                for u in device_users
            ]
        }
        res = server_post("/device-bridge/sync-enrollment", payload)
        if res.get("updated", 0) > 0:
            log.info(
                f"Enrollment sync: {res['updated']} "
                f"user diperbarui"
            )
    except Exception as e:
        log.error(f"Enrollment sync gagal: {e}")


def heartbeat(client: X606SOAPClient):
    """Kirim status bridge + info device ke server rack."""
    try:
        users = client.get_all_users()
        total = len(users) if users else 0

        try:
            t = client.get_time()
            device_time = f"{t.get('date','')} {t.get('time','')}".strip()
        except Exception:
            device_time = ""

        requests.post(
            f"{SERVER_URL}/device-bridge/status",
            headers=HEADERS,
            params={
                "device_sn":   DEVICE_SN,
                "device_ip":   DEVICE_IP,
                "device_time": device_time,
                "total_user":  total,
                "ruangan_id":  DEVICE_RUANGAN_ID,
            },
            timeout=10
        )
        log.debug(f"Heartbeat terkirim — {total} user di device")
    except Exception as e:
        log.warning(f"Heartbeat gagal: {e}")


# ══════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════

def main():
    print("\n" + "═" * 58)
    print("  Smart Door Lock Bridge — Polsri")
    print("  STB Linux ↔ X606-S ↔ Server Rack")
    print("═" * 58)
    print(f"  Device     : {DEVICE_IP}")
    print(f"  Server     : {SERVER_URL}")
    print(f"  Ruangan    : {DEVICE_RUANGAN_ID}")
    print(f"  Pull setiap: {PULL_INTERVAL}s | Sync tiap {SYNC_INTERVAL} loop")
    print("═" * 58)

    # Konfirmasi timezone sebelum mulai
    _now_utc = datetime.now(timezone.utc)
    _now_wib = now_wib()
    log.info(f"  Waktu UTC : {_now_utc.strftime('%Y-%m-%d %H:%M:%S')}")
    log.info(f"  Waktu WIB : {_now_wib.strftime('%Y-%m-%d %H:%M:%S')} (yang dikirim ke device)")

    # ── Test Server Rack ─────────────────────────────────
    log.info("Test koneksi server rack...")
    try:
        r = requests.get(
            f"{SERVER_URL}/device-bridge/status-public",
            params={"ruangan_id": DEVICE_RUANGAN_ID},
            timeout=10
        )
        if r.status_code == 200:
            log.info("  ✓ Server rack online")
        else:
            log.error("  ✗ Server rack tidak merespons!")
            return
    except Exception as e:
        log.error(f"  ✗ Server rack gagal diakses: {e}")
        return

    # ── Test Device ──────────────────────────────────────
    log.info("Test koneksi X606-S...")
    client = X606SOAPClient(ip=DEVICE_IP, com_key=DEVICE_COMKEY)
    try:
        t = client.ping()
        if t.get("date") or t.get("time"):
            now = now_wib()
            client.set_time(
                now.strftime("%Y-%m-%d"),
                now.strftime("%H:%M:%S")
            )
            log.info(
                f"  ✓ Device online — "
                f"{t.get('date','')} {t.get('time','')} "
                f"(waktu disinkronkan)"
            )
        else:
            log.warning("  ⚠ Device merespons tapi data kosong")
            return
    except Exception as e:
        log.error(f"  ✗ Gagal konek ke {DEVICE_IP}: {e}")
        log.error("  Pastikan STB dan device satu jaringan WiFi")
        return

    # ── Heartbeat awal ────────────────────────────────────
    heartbeat(client)

    # ── Sync awal ────────────────────────────────────────
    # log.info("Sync awal user...")
    # sync_users(client)

    # ── Pull log awal ────────────────────────────────────
    log.info("Pull log awal...")
    pull_logs(client)

    # ── Sync enrollment awal ─────────────────────────────
    log.info("Sync enrollment...")
    sync_enrollment(client)

    # ── Main loop ─────────────────────────────────────────
    log.info(f"Bridge aktif — loop setiap {PULL_INTERVAL} detik\n")

    loop = 0
    while True:
        try:
            time.sleep(PULL_INTERVAL)
            loop += 1

            heartbeat(client)

            n = pull_logs(client)
            if n > 0:
                log.info(f"Loop #{loop}: {n} log diproses")

            if loop % SYNC_INTERVAL == 0:
                log.info(f"Loop #{loop}: Sync periodik...")
                # sync_users(client)
                sync_enrollment(client)

            if loop % (3600 // PULL_INTERVAL) == 0:
                now = now_wib()
                client.set_time(
                    now.strftime("%Y-%m-%d"),
                    now.strftime("%H:%M:%S")
                )
                log.info(f"Waktu device disinkronkan → {now.strftime('%H:%M:%S')} WIB")

        except KeyboardInterrupt:
            raise
        except Exception as e:
            log.error(f"Error di loop #{loop}: {e}")
            time.sleep(5)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Bridge dihentikan (Ctrl+C)")