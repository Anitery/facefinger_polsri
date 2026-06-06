"""
Test apakah server FastAPI bisa menerima data dari device.
Jalankan: python test_device_connection.py
"""
import requests

# Ganti dengan IP laptop kamu
SERVER_URL = "http://10.108.121.233:8000"

print("=" * 50)
print("  Test Koneksi Device ADMS")
print("=" * 50)

# Test 1: Ping
print("\n[TEST 1] Ping server...")
try:
    r = requests.get(f"{SERVER_URL}/iclock/ping", timeout=5)
    print(f"  Status : {r.status_code}")
    print(f"  Body   : {r.text}")
    print("  ✓ Server bisa dijangkau!")
except Exception as e:
    print(f"  ✗ Gagal: {e}")

# Test 2: Simulasi heartbeat device
print("\n[TEST 2] Simulasi heartbeat device...")
try:
    r = requests.get(
        f"{SERVER_URL}/iclock/getrequest",
        params={"SN": "TEST001", "INFO": "test"},
        timeout=5
    )
    print(f"  Status : {r.status_code}")
    print(f"  Body   : {r.text}")
    print("  ✓ Heartbeat OK!")
except Exception as e:
    print(f"  ✗ Gagal: {e}")

# Test 3: Simulasi push data transaksi
print("\n[TEST 3] Simulasi push data scan wajah (PIN=1)...")
from datetime import datetime
now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

try:
    r = requests.post(
        f"{SERVER_URL}/iclock/cdata",
        params={
            "SN":    "TEST001",
            "table": "ATTLOG",
            "Stamp": "0",
        },
        # Format: PIN TAB DateTime TAB VerifyCode TAB InOutState
        data=f"1\t{now}\t4\t0",   # PIN=1, waktu=sekarang, face(4), masuk(0)
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        timeout=10
    )
    print(f"  Status : {r.status_code}")
    print(f"  Body   : {r.text}")
    print("  ✓ Data transaksi diterima!")
except Exception as e:
    print(f"  ✗ Gagal: {e}")

print("\n" + "=" * 50)
print("  Cek terminal server untuk log detail")
print("=" * 50)