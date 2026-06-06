"""
Script simulasi data log akses untuk demo ke dosen pembimbing.
Mensimulasikan akses fingerprint dan face recognition secara realistis.

Jalankan:
    python simulate_access.py

Konfigurasi di .env:
    SERVER_URL = http://localhost:8000   (lokal)
    SERVER_URL = https://nama.up.railway.app  (production)
"""

import requests
import random
import time
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

SERVER_URL = os.getenv("SERVER_URL", "http://localhost:8000")
RUANGAN_ID = int(os.getenv("RUANGAN_ID", "1"))

# ── Warna terminal ────────────────────────────────────────
GREEN  = "\033[92m"
RED    = "\033[91m"
YELLOW = "\033[93m"
BLUE   = "\033[94m"
CYAN   = "\033[96m"
RESET  = "\033[0m"
BOLD   = "\033[1m"


def header():
    print(f"\n{BOLD}{'='*55}{RESET}")
    print(f"{BOLD}  Smart Door Lock — Simulasi Akses Biometrik{RESET}")
    print(f"{BOLD}{'='*55}{RESET}")
    print(f"  Server    : {CYAN}{SERVER_URL}{RESET}")
    print(f"  Ruangan   : {RUANGAN_ID}")
    print(f"  Waktu     : {datetime.now().strftime('%d/%m/%Y %H:%M:%S')}")
    print(f"{BOLD}{'='*55}{RESET}\n")


def cek_server() -> bool:
    """Cek apakah server online."""
    try:
        resp = requests.get(f"{SERVER_URL}/health", timeout=5)
        if resp.status_code == 200:
            print(f"[SERVER] {GREEN}✓ Server online{RESET}\n")
            return True
        print(f"[SERVER] {YELLOW}⚠ Status {resp.status_code}{RESET}\n")
        return False
    except Exception:
        print(f"[SERVER] {RED}✗ Tidak bisa terhubung{RESET}\n")
        return False


def ambil_users() -> list:
    """Ambil daftar user dari server."""
    try:
        resp = requests.get(f"{SERVER_URL}/users/", timeout=10)
        if resp.status_code == 200:
            users = resp.json()
            # Filter hanya yang punya fingerprint_id (bisa autentikasi)
            valid = [u for u in users if u.get("aktif")]
            print(f"[INFO] {len(valid)} pengguna aktif ditemukan:")
            for u in valid:
                fp  = f"FP ID:{u['fingerprint_id']}" if u.get("fingerprint_id") else "no FP"
                face = "✓ wajah" if u.get("face_encoding") else "✗ wajah"
                print(f"       → [{u['role']:10}] {u['nama']} ({fp}, {face})")
            print()
            return valid
        return []
    except Exception as e:
        print(f"[ERROR] Gagal ambil users: {e}")
        return []


def simulasi_fingerprint(user: dict) -> bool:
    """Kirim request autentikasi fingerprint ke server."""
    if not user.get("fingerprint_id"):
        return False
    try:
        resp = requests.post(
            f"{SERVER_URL}/auth/fingerprint",
            json={
                "ruangan_id":    RUANGAN_ID,
                "fingerprint_id": user["fingerprint_id"]
            },
            timeout=10
        )
        return resp.status_code == 200
    except Exception:
        return False


def simulasi_fingerprint_gagal() -> bool:
    """Simulasi fingerprint ID yang tidak terdaftar."""
    try:
        fake_id = random.randint(900, 999)
        resp = requests.post(
            f"{SERVER_URL}/auth/fingerprint",
            json={
                "ruangan_id":    RUANGAN_ID,
                "fingerprint_id": fake_id
            },
            timeout=10
        )
        return resp.status_code == 401
    except Exception:
        return False


def simulasi_face(user: dict) -> bool:
    """
    Simulasi face recognition — kirim encoding wajah dummy.
    Karena tidak ada wajah asli, kita simulasi dengan dua skenario:
    1. Berhasil: kirim encoding dari user terdaftar (jika ada)
    2. Gagal: kirim encoding acak
    """
    # Cek apakah user punya face encoding tersimpan
    import json
    import numpy as np

    if user.get("face_encoding"):
        # Gunakan encoding asli dengan sedikit noise (simulasi wajah nyata)
        try:
            stored = json.loads(user["face_encoding"])
            noise  = np.random.normal(0, 0.02, len(stored)).tolist()
            enc    = [stored[i] + noise[i] for i in range(len(stored))]
        except Exception:
            enc = np.random.rand(128).tolist()
    else:
        # Encoding acak — pasti gagal
        enc = np.random.rand(128).tolist()

    try:
        resp = requests.post(
            f"{SERVER_URL}/auth/face",
            json={
                "ruangan_id":   RUANGAN_ID,
                "face_encoding": enc
            },
            timeout=10
        )
        return resp.status_code == 200
    except Exception:
        return False


def simulasi_face_gagal() -> bool:
    """Simulasi wajah tidak dikenal — encoding acak."""
    import numpy as np
    try:
        resp = requests.post(
            f"{SERVER_URL}/auth/face",
            json={
                "ruangan_id":   RUANGAN_ID,
                "face_encoding": np.random.rand(128).tolist()
            },
            timeout=10
        )
        return resp.status_code == 401
    except Exception:
        return False


def log_hasil(metode: str, nama: str, berhasil: bool, waktu_ms: int):
    """Tampilkan hasil simulasi di terminal."""
    status  = f"{GREEN}✓ BERHASIL{RESET}" if berhasil else f"{RED}✗ DITOLAK{RESET}"
    icon    = "👆" if metode == "fingerprint" else "👤"
    metode_str = f"{CYAN}Fingerprint{RESET}" if metode == "fingerprint" \
                 else f"{BLUE}Face Recog{RESET}"
    ts      = datetime.now().strftime("%H:%M:%S")
    print(f"  [{ts}] {icon} {metode_str} | {nama:<22} | {status} | {waktu_ms}ms")


def jalankan_simulasi(users: list, jumlah: int, jeda_min: float, jeda_max: float):
    """
    Jalankan simulasi sejumlah `jumlah` akses dengan jeda acak.
    """
    print(f"{BOLD}Memulai simulasi {jumlah} akses...{RESET}")
    print(f"{'─'*60}")

    berhasil_total = 0
    gagal_total    = 0

    for i in range(1, jumlah + 1):
        # Tentukan skenario secara acak
        # 70% berhasil, 30% gagal
        skenario_berhasil = random.random() < 0.70

        # Pilih metode: 50% fingerprint, 50% face
        metode = random.choice(["fingerprint", "face"])

        if skenario_berhasil and users:
            # Pilih user acak yang valid
            user = random.choice(users)
            nama = user["nama"]

            t_start = time.time()
            if metode == "fingerprint":
                ok = simulasi_fingerprint(user)
            else:
                ok = simulasi_face(user)
            waktu_ms = int((time.time() - t_start) * 1000)

            # Jika user tidak punya FP/face, fallback ke gagal
            if not ok:
                nama = "Tidak dikenal"
                skenario_berhasil = False
        else:
            # Skenario gagal — orang tidak terdaftar
            nama = "Tidak dikenal"
            t_start = time.time()
            if metode == "fingerprint":
                simulasi_fingerprint_gagal()
            else:
                simulasi_face_gagal()
            waktu_ms = int((time.time() - t_start) * 1000)
            ok = False

        log_hasil(metode, nama, ok, waktu_ms)

        if ok:
            berhasil_total += 1
        else:
            gagal_total += 1

        # Jeda acak antar akses (kecuali akses terakhir)
        if i < jumlah:
            jeda = random.uniform(jeda_min, jeda_max)
            time.sleep(jeda)

    # Ringkasan
    print(f"{'─'*60}")
    print(f"\n{BOLD}Ringkasan Simulasi:{RESET}")
    print(f"  Total akses  : {jumlah}")
    print(f"  {GREEN}Berhasil     : {berhasil_total}{RESET}")
    print(f"  {RED}Ditolak      : {gagal_total}{RESET}")
    print(f"  Akurasi      : {berhasil_total/jumlah*100:.1f}%\n")


def menu():
    """Menu interaktif untuk memilih mode simulasi."""
    print(f"{BOLD}Pilih mode simulasi:{RESET}")
    print("  1. Demo cepat      — 10 akses, jeda 1-2 detik")
    print("  2. Demo normal     — 20 akses, jeda 2-5 detik")
    print("  3. Demo panjang    — 50 akses, jeda 3-8 detik")
    print("  4. Custom")
    print("  0. Keluar\n")

    pilihan = input("Pilih [0-4]: ").strip()

    if pilihan == "1":
        return 10, 1.0, 2.0
    elif pilihan == "2":
        return 20, 2.0, 5.0
    elif pilihan == "3":
        return 50, 3.0, 8.0
    elif pilihan == "4":
        try:
            jumlah   = int(input("Jumlah akses    : "))
            jeda_min = float(input("Jeda minimum (detik): "))
            jeda_max = float(input("Jeda maximum (detik): "))
            return jumlah, jeda_min, jeda_max
        except ValueError:
            print(f"{RED}Input tidak valid, pakai default.{RESET}")
            return 10, 1.0, 2.0
    elif pilihan == "0":
        return None, None, None
    else:
        print(f"{YELLOW}Pilihan tidak valid, pakai demo cepat.{RESET}")
        return 10, 1.0, 2.0


def main():
    header()

    if not cek_server():
        print(f"{RED}Server tidak aktif. Pastikan server berjalan dulu.{RESET}")
        return

    users = ambil_users()
    if not users:
        print(f"{YELLOW}⚠ Tidak ada user aktif di database.{RESET}")
        print(f"  Jalankan seed.py terlebih dahulu.\n")

    jumlah, jeda_min, jeda_max = menu()
    if jumlah is None:
        print("Keluar.")
        return

    print()
    jalankan_simulasi(users, jumlah, jeda_min, jeda_max)

    print(f"{GREEN}{BOLD}✓ Simulasi selesai!{RESET}")
    print(f"  Buka dashboard untuk melihat hasilnya:")
    print(f"  {CYAN}{SERVER_URL}/dashboard/log-akses{RESET}\n")


if __name__ == "__main__":
    main()