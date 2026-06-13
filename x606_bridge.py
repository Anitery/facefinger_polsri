"""
X606-S Local Bridge — Smart Door Lock Polsri
Berjalan di STB Linux 24/7 di jaringan lab.

Alur kerja:
  1. Sync user + timezone ke device (awal + periodik)
  2. Pull log absensi dari device → kirim ke Railway
  3. Railway validasi jadwal KBM + catat absensi otomatis

Jalankan:
    python x606_bridge.py
"""

import os
import sys
import time
import requests
import logging
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── Konfigurasi ──────────────────────────────────────────
DEVICE_IP         = os.getenv("DEVICE_IP",         "192.168.0.177")
DEVICE_COMKEY     = os.getenv("DEVICE_COMKEY",     "0")
DEVICE_RUANGAN_ID = int(os.getenv("DEVICE_RUANGAN_ID", "8"))
SERVER_URL        = os.getenv("SERVER_URL",        "https://facefingerpolsri-production.up.railway.app")
BRIDGE_API_KEY    = os.getenv("BRIDGE_API_KEY",    "bridge-key-polsri-2026")
PULL_INTERVAL     = int(os.getenv("PULL_INTERVAL", "60"))
SYNC_INTERVAL     = int(os.getenv("SYNC_INTERVAL", "10"))
DEVICE_SN         = os.getenv("DEVICE_SN",         "X606S-001")

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
# HELPER: Komunikasi ke Railway
# ══════════════════════════════════════════════════════════

def railway_get(path: str, params: dict = None) -> dict:
    try:
        r = requests.get(
            f"{SERVER_URL}{path}",
            headers=HEADERS, params=params, timeout=15
        )
        return r.json() if r.ok else {}
    except Exception as e:
        log.error(f"GET {path} gagal: {e}")
        return {}


def railway_post(path: str, data: dict) -> dict:
    try:
        r = requests.post(
            f"{SERVER_URL}{path}",
            headers=HEADERS, json=data, timeout=30
        )
        return r.json() if r.ok else {}
    except Exception as e:
        log.error(f"POST {path} gagal: {e}")
        return {}


# ══════════════════════════════════════════════════════════
# BAGIAN A — Sync user + timezone ke device
# ══════════════════════════════════════════════════════════

def get_timezone_for_user(user: dict, jadwals: list) -> str:
    """
    Tentukan TZ1 device berdasarkan role + jadwal hari ini.
    
    Admin/Teknisi : 0000-2359 (bebas kapan saja)
    Dosen         : 0000-2359 (bebas, absensi tetap dicatat)
    Mahasiswa     : HHMM-HHMM sesuai jadwal, atau 0000-0000
    """
    role  = user.get("role", "mahasiswa")
    fp_id = user.get("fingerprint_id")

    if role in ("admin", "teknisi", "dosen"):
        return "0000-2359"

    # Mahasiswa: cari di jadwal hari ini
    for j in jadwals:
        if fp_id in (j.get("fp_ids_diizinkan") or []):
            mulai   = j["jam_mulai"][:5].replace(":", "")   # "07:00" → "0700"
            selesai = j["jam_selesai"][:5].replace(":", "")  # "09:30" → "0930"
            return f"{mulai}-{selesai}"

    # Tidak ada jadwal → blokir
    return "0000-0000"


def sync_users(client: X606SOAPClient):
    """Sync semua user dari Railway ke device dengan timezone yang benar."""
    log.info("── Sync user ke device...")

    users   = railway_get("/device-bridge/users")
    jadwals = railway_get(
        "/device-bridge/jadwal-hari-ini",
        {"ruangan_id": DEVICE_RUANGAN_ID}
    )

    if not users:
        log.warning("Tidak ada user dari Railway")
        return 0

    if isinstance(jadwals, dict):
        jadwals = []

    log.info(f"  {len(users)} user | {len(jadwals)} jadwal hari ini")

    synced = failed = 0
    for u in users:
        fp_id = str(u.get("fingerprint_id", ""))
        nama  = u.get("nama", "")
        role  = u.get("role", "mahasiswa")
        tz    = get_timezone_for_user(u, jadwals)
        priv  = "14" if role in ("admin", "teknisi") else "0"

        try:
            ok = client.set_user(
                pin=fp_id, name=nama,
                privilege=priv, tz1=tz
            )
            if ok:
                synced += 1
                log.info(
                    f"  ✓ [{role:10}] {nama:25} "
                    f"FP:{fp_id:3} TZ:{tz}"
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


# ══════════════════════════════════════════════════════════
# BAGIAN B — Pull log dari device → Railway
# ══════════════════════════════════════════════════════════

def pull_logs(client: X606SOAPClient) -> int:
    """Pull SOAP log dari device, filter baru, kirim ke Railway."""
    try:
        logs = client.get_logs("All")
    except Exception as e:
        log.error(f"Pull SOAP gagal: {e}")
        return 0

    if not logs:
        return 0

    # Filter yang belum diproses session ini
    new_logs = []
    for l in logs:
        key = f"{l.get('PIN','')}|{l.get('DateTime','')}"
        if key not in _processed:
            new_logs.append(l)

    if not new_logs:
        log.debug(f"Semua {len(logs)} log sudah diproses")
        return 0

    log.info(f"Mengirim {len(new_logs)} log baru ke Railway...")

    payload = {
        "ruangan_id": DEVICE_RUANGAN_ID,
        "device_sn":  DEVICE_SN,
        "logs": [
            {
                "pin":      l.get("PIN",      ""),
                "datetime": l.get("DateTime", ""),
                "verified": l.get("Verified", "1"),
                "status":   l.get("Status",   "0"),
            }
            for l in new_logs
        ]
    }

    res = railway_post("/device-bridge/push-logs", payload)
    if res:
        log.info(
            f"  Railway: {res.get('berhasil',0)} berhasil | "
            f"{res.get('ditolak',0)} ditolak | "
            f"{res.get('duplikat',0)} duplikat"
        )
        # Tandai sudah diproses
        for l in new_logs:
            key = f"{l.get('PIN','')}|{l.get('DateTime','')}"
            _processed.add(key)
        return res.get("berhasil", 0) + res.get("ditolak", 0)

    return 0


# ══════════════════════════════════════════════════════════
# BAGIAN C — Sync enrollment (fingerprint mapping)
# ══════════════════════════════════════════════════════════

def sync_enrollment(client: X606SOAPClient):
    """
    Ambil semua user di device, kirim ke Railway untuk
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
        res = railway_post("/device-bridge/sync-enrollment", payload)
        if res.get("updated", 0) > 0:
            log.info(
                f"Enrollment sync: {res['updated']} "
                f"user diperbarui"
            )
    except Exception as e:
        log.error(f"Enrollment sync gagal: {e}")


# ══════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════

def main():
    print("\n" + "═" * 58)
    print("  Smart Door Lock Bridge — Polsri")
    print("  STB Linux ↔ X606-S ↔ Railway")
    print("═" * 58)
    print(f"  Device     : {DEVICE_IP}")
    print(f"  Server     : {SERVER_URL}")
    print(f"  Ruangan    : {DEVICE_RUANGAN_ID}")
    print(f"  Pull setiap: {PULL_INTERVAL}s | "
          f"Sync tiap {SYNC_INTERVAL} loop")
    print("═" * 58)

    # ── Test Railway ─────────────────────────────────────
    log.info("Test koneksi Railway...")

    try:
        r = requests.get(
            f"{SERVER_URL}/device-bridge/status-public",
            params={"ruangan_id": DEVICE_RUANGAN_ID},
            timeout=10
        )

        if r.status_code == 200:
            log.info("  ✓ Railway online")
        else:
            log.error("  ✗ Railway tidak merespons!")
            return

    except Exception as e:
        log.error(f"  ✗ Railway gagal diakses: {e}")
        return

    # ── Test Device ──────────────────────────────────────
    log.info("Test koneksi X606-S...")
    client = X606SOAPClient(ip=DEVICE_IP, com_key=DEVICE_COMKEY)
    try:
        t = client.ping()
        if t.get("date") or t.get("time"):
            # Sinkronisasi waktu device dengan STB
            now = datetime.now()
            client.set_time(
                now.strftime("%Y-%m-%d"),
                now.strftime("%H:%M:%S")
            )
            log.info(
                f"  ✓ Device online — "
                f"{t.get('date','')} {t.get('time','')} "
                f"(waktu disinkronkan)"
            )

            heartbeat(client)
        else:
            log.warning("  ⚠ Device merespons tapi data kosong")
    except Exception as e:
        log.error(f"  ✗ Gagal konek ke {DEVICE_IP}: {e}")
        log.error("  Pastikan STB dan device satu jaringan WiFi")
        return

def heartbeat(client: X606SOAPClient):
    """Kirim status bridge + info device ke Railway."""
    try:
        # jumlah user di device
        users = client.get_all_users()
        total = len(users) if users else 0

        # waktu device
        try:
            t = client.get_time()
            device_time = (
                f"{t.get('date','')} {t.get('time','')}"
            ).strip()
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

        log.debug(
            f"Heartbeat terkirim — {total} user di device"
        )

    except Exception as e:
        log.warning(f"Heartbeat gagal: {e}")

    # ── Sync awal ────────────────────────────────────────
    log.info("Sync awal user...")
    sync_users(client)

    # ── Pull log awal ────────────────────────────────────
    log.info("Pull log awal...")
    pull_logs(client)

    # ── Sync enrollment awal ─────────────────────────────
    log.info("Sync enrollment...")
    sync_enrollment(client)

    # ── Main loop ─────────────────────────────────────────
    log.info(
        f"Bridge aktif — loop setiap {PULL_INTERVAL} detik\n"
    )

    loop = 0
    while True:
        try:
            time.sleep(PULL_INTERVAL)
            loop += 1

            heartbeat(client)

            # Pull log setiap interval
            n = pull_logs(client)
            if n > 0:
                log.info(f"Loop #{loop}: {n} log diproses")

            # Sync user periodik
            if loop % SYNC_INTERVAL == 0:
                log.info(f"Loop #{loop}: Sync periodik...")
                sync_users(client)
                sync_enrollment(client)

            # Sync waktu device setiap 1 jam
            if loop % (3600 // PULL_INTERVAL) == 0:
                now = datetime.now()
                client.set_time(
                    now.strftime("%Y-%m-%d"),
                    now.strftime("%H:%M:%S")
                )
                log.info("Waktu device disinkronkan")

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