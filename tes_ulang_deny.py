"""
tes_group_rendah.py — Tes hipotesis: cuma Group 1-5 yang beneran
dipakai logika relay fisik (sesuai grid 'Lock Group' yang cuma
punya 5 kolom: Group-1 s/d Group-5).

2 skenario dites berurutan pada Group index 2 (rendah, bukan 90-99):
  A. Group 2 -> TZ 41 (waktu terbalik/'tutup')
  B. Group 2 -> None/None/None (tz=0 semua slot)
"""
import tempfile, os
from zk_admin import _login_get_cookiejar, set_group, set_user_group, list_users
from zk_web import ZKWebError

DEVICE_IP = "10.17.44.162"
USERNAME  = "1"
PASSWORD  = "8888"

GID_TES        = 2    # Group RENDAH (1-5), bukan 90-99
TZ_SELALU_TUTUP = 41  # sudah ada dari tes sebelumnya (waktu terbalik)
PIN_TARGET     = "4"  # Fatah

with tempfile.TemporaryDirectory() as tmpdir:
    cookie_file = os.path.join(tmpdir, "cookies.txt")

    print("Login...")
    _login_get_cookiejar(DEVICE_IP, USERNAME, PASSWORD, cookie_file)
    print("✓ Login berhasil")

    users = list_users(DEVICE_IP, cookie_file)
    target = next((u for u in users if u["pin"] == PIN_TARGET), None)
    if not target:
        print(f"✗ PIN {PIN_TARGET} tidak ditemukan")
        exit(1)

    print("\n" + "=" * 60)
    print(f"SKENARIO A — Group {GID_TES} -> TZ {TZ_SELALU_TUTUP} (waktu terbalik)")
    print("=" * 60)
    set_group(DEVICE_IP, cookie_file, GID_TES, TZ_SELALU_TUTUP, TZ_SELALU_TUTUP, TZ_SELALU_TUTUP)
    set_user_group(DEVICE_IP, cookie_file, target["uid"], target["pin"], target["nama"], GID_TES)
    print(f"✓ User PIN {PIN_TARGET} di Group {GID_TES}, Group {GID_TES} -> TZ {TZ_SELALU_TUTUP} (harusnya tutup)")
    input(f"\n>> COBA SCAN PIN {PIN_TARGET} SEKARANG. Harusnya DITOLAK. Tekan ENTER setelah dicoba...\n")

    print("\n" + "=" * 60)
    print(f"SKENARIO B — Group {GID_TES} -> None/None/None")
    print("=" * 60)
    set_group(DEVICE_IP, cookie_file, GID_TES, tz1=0, tz2=0, tz3=0)
    print(f"✓ Group {GID_TES} sekarang None di ketiga slot (user PIN {PIN_TARGET} masih di Group ini)")
    input(f"\n>> COBA SCAN PIN {PIN_TARGET} SEKARANG. Harusnya DITOLAK. Tekan ENTER setelah dicoba...\n")

    print("\nSelesai — laporkan hasil kedua skenario.")