"""
X606-S Testing Script V3 - AUTO SYNC
=====================================
Versi ini menggunakan endpoint quick-sync yang otomatis:
- Set user ke device
- Auto-detect PIN device (internal)
- Auto-register ke cache

Usage:
    python test_x606_v3.py
"""
import requests
import json
from datetime import datetime

BASE_URL = "http://localhost:8000"
DEVICE_ID = "lab-mulmed-2"
X606_IP = "192.168.0.177"
RUANGAN_ID = 8

GREEN = "\033[92m"
RED = "\033[91m"
YELLOW = "\033[93m"
RESET = "\033[0m"

def print_step(step_num, title):
    print(f"\n{'='*60}")
    print(f"STEP {step_num}: {title}")
    print(f"{'='*60}")

def print_result(success, message):
    color = GREEN if success else RED
    status = "✅ PASS" if success else "❌ FAIL"
    print(f"{color}{status}{RESET} {message}")

def print_warn(message):
    print(f"{YELLOW}⚠️  WARN{RESET} {message}")

def test_register_device():
    print_step(1, "Register X606-S Device")
    payload = {
        "device_id": DEVICE_ID,
        "name": "Lab Multimedia 2",
        "ip_address": X606_IP,
        "com_key": "0",
        "ruangan_id": RUANGAN_ID,
        "is_active": True
    }
    try:
        r = requests.post(f"{BASE_URL}/x606/devices", json=payload, timeout=10)
        if r.status_code == 200:
            print_result(True, f"Device registered: {r.json()['device_id']}")
        elif r.status_code == 400 and "sudah terdaftar" in r.text:
            print_result(True, "Device already registered (OK)")
        else:
            print_result(False, f"Status {r.status_code}: {r.text[:200]}")
            return False
    except Exception as e:
        print_result(False, f"Error: {e}")
        return False
    return True

def test_device_connection():
    print_step(2, "Test Koneksi ke X606-S")
    try:
        r = requests.post(f"{BASE_URL}/x606/devices/{DEVICE_ID}/test", timeout=10)
        data = r.json()
        if data.get("success"):
            print_result(True, f"Koneksi berhasil! Waktu device: {data.get('device_time')}")
        else:
            print_result(False, f"Koneksi gagal: {data.get('message')}")
            return False
    except Exception as e:
        print_result(False, f"Error: {e}")
        return False
    return True

def test_list_device_users():
    print_step(3, "List User di X606-S (Sebelum Sync)")
    try:
        r = requests.get(f"{BASE_URL}/x606/devices/{DEVICE_ID}/users", timeout=10)
        data = r.json()
        users = data.get("users", [])
        print(f"   Total user di device: {data.get('count', 0)}")
        for u in users:
            print(f"   - PIN:{u.get('PIN','N/A')} | Name:{u.get('Name','N/A')} | TZ1:{u.get('TZ1','N/A')} | PIN2:{u.get('PIN2','N/A')}")
        if users:
            print_result(True, f"{len(users)} user di device")
        else:
            print_warn("Tidak ada user di device")
        return users
    except Exception as e:
        print_result(False, f"Error: {e}")
        return []

def test_auto_sync_users():
    print_step(4, "AUTO SYNC User ke X606-S (Set + Detect PIN + Cache)")
    users_to_sync = [
        {"pin_request": "00001", "name": "Budi Santoso", "user_id": 1},
        {"pin_request": "00002", "name": "Ani Wijaya", "user_id": 2},
    ]

    success_count = 0
    for user in users_to_sync:
        try:
            r = requests.post(
                f"{BASE_URL}/lab-multimedia/devices/{DEVICE_ID}/quick-sync",
                json=user,
                timeout=30
            )
            data = r.json()
            if data.get("success"):
                print_result(True, 
                    f"{user['name']}: PIN_request={data.get('pin_request')} → PIN_device={data.get('pin_device')} | Cache OK")
                success_count += 1
            else:
                print_result(False, 
                    f"{user['name']}: {data.get('message')[:100]}")
        except Exception as e:
            print_result(False, f"{user['name']}: Error {e}")

    print(f"\n   Total berhasil: {success_count}/{len(users_to_sync)}")
    return success_count > 0

def test_list_users_after_sync():
    print_step(5, "List User di X606-S (Setelah Auto Sync)")
    try:
        r = requests.get(f"{BASE_URL}/x606/devices/{DEVICE_ID}/users", timeout=10)
        data = r.json()
        users = data.get("users", [])
        print(f"   Total user di device: {data.get('count', 0)}")
        for u in users:
            print(f"   - PIN:{u.get('PIN','N/A')} | Name:{u.get('Name','N/A')} | TZ1:{u.get('TZ1','N/A')} | PIN2:{u.get('PIN2','N/A')}")
        if users:
            print_result(True, f"{len(users)} user di device")
        else:
            print_warn("Tidak ada user")
        return users
    except Exception as e:
        print_result(False, f"Error: {e}")
        return []

def test_user_cache():
    print_step(6, "Cek User Cache di Backend (Auto Registered)")
    try:
        r = requests.get(f"{BASE_URL}/lab-multimedia/devices/{DEVICE_ID}/user-cache", timeout=10)
        caches = r.json()
        print(f"   Total cache: {len(caches)}")
        for c in caches:
            print(f"   - PIN:{c['pin']} | UserID:{c['user_id']} | Name:{c['name']}")
        if caches:
            print_result(True, f"{len(caches)} user cache terdaftar otomatis")
        else:
            print_warn("Tidak ada cache (auto sync mungkin gagal)")
        return caches
    except Exception as e:
        print_result(False, f"Error: {e}")
        return []

def test_scan_instruction():
    print_step(7, "INSTRUKSI MANUAL")
    print("   Sekarang scan fingerprint di X606-S untuk user yang sudah di-sync.")
    print("   Pastikan pintu terbuka dan log tersimpan di device.")
    print("   Tekan ENTER setelah scan selesai...")
    input()

def test_quick_pull_logs():
    print_step(8, "Pull Logs (Quick Test - Tanpa Cek Jadwal)")
    try:
        r = requests.post(
            f"{BASE_URL}/lab-multimedia/devices/{DEVICE_ID}/quick-test-scan",
            timeout=30
        )
        data = r.json()
        if data.get("success"):
            print_result(True, f"Pull berhasil: {data.get('message')}")
        else:
            print_result(False, f"Pull gagal: {data.get('message')}")
    except Exception as e:
        print_result(False, f"Error: {e}")

def test_list_absensi():
    print_step(9, "List Absensi di Database")
    try:
        r = requests.get(f"{BASE_URL}/lab-multimedia/absensi?ruangan_id={RUANGAN_ID}", timeout=10)
        data = r.json()
        print(f"   Total absensi: {len(data)}")
        for a in data[:5]:
            name = a.get('user_name') or 'Unknown'
            status = a.get('status_absensi')
            keterangan = a.get('keterangan','')
            print(f"   - {name} | {a.get('waktu_scan')} | {status} | {keterangan}")
        if data:
            # Count valid vs invalid
            valid = sum(1 for a in data if a.get('is_valid_jadwal'))
            invalid = len(data) - valid
            print_result(True, f"{len(data)} absensi ({valid} valid, {invalid} invalid)")
        else:
            print_warn("Tidak ada absensi")
    except Exception as e:
        print_result(False, f"Error: {e}")

def test_disable_all():
    print_step(10, "Disable Semua User (Simulasi Akhir Jadwal)")
    try:
        r = requests.post(
            f"{BASE_URL}/lab-multimedia/devices/{DEVICE_ID}/disable-all",
            timeout=30
        )
        data = r.json()
        if data.get("success"):
            print_result(True, f"Disable berhasil: {data.get('message')}")
        else:
            print_result(False, f"Disable gagal: {data.get('message')}")
    except Exception as e:
        print_result(False, f"Error: {e}")

def main():
    print(f"{YELLOW}X606-S SMART LOCK TESTING SCRIPT V3 - AUTO SYNC{RESET}")
    print(f"Base URL: {BASE_URL}")
    print(f"Device IP: {X606_IP}")
    print(f"Ruangan ID: {RUANGAN_ID}")
    print("\n" + "="*60)
    print("PASTIKAN:")
    print("1. Backend berjalan: uvicorn main:app --reload")
    print("2. X606-S terhubung ke jaringan yang sama dengan laptop")
    print("3. X606-S IP address benar dan port 80 terbuka")
    print("4. User ID 1 dan 2 sudah ada di database (tabel users)")
    print("5. File router sudah di-replace dengan versi AUTO")
    print("="*60)

    input("\nTekan ENTER untuk mulai testing...")

    ok = test_register_device()
    if not ok:
        print_warn("Lanjutkan...")

    ok = test_device_connection()
    if not ok:
        print("\n❌ Koneksi ke device gagal. Stop testing.")
        return

    users_before = test_list_device_users()

    ok = test_auto_sync_users()
    if not ok:
        print_warn("Auto sync gagal, coba manual...")

    users_after = test_list_users_after_sync()

    caches = test_user_cache()

    test_scan_instruction()

    test_quick_pull_logs()

    test_list_absensi()

    test_disable_all()

    print(f"\n{GREEN}=== TESTING SELESAI ==={RESET}")
    print(f"\n{YELLOW}Catatan:{RESET}")
    print("- Jika auto sync berhasil, user cache sudah terdaftar otomatis dengan PIN device")
    print("- Jika masih ada masalah, jalankan: python debug_setuser.py")

if __name__ == "__main__":
    main()