"""
tes_manual_jadwal.py — Script tes manual (BUKAN bagian sistem final)
=========================================================
Tujuan: validasi step-by-step di hardware ASLI sebelum fitur jadwal
dibangun permanen di website. Jalan lewat terminal, berhenti di tiap
langkah supaya kamu bisa cocokkan dengan reaksi fisik alat (coba scan
kartu/fingerprint setelah tiap langkah).

Pakai TZ/Group index tinggi (40-50 / 90-99) supaya tidak bentrok
dengan index rendah yang mungkin dipakai manual.

Jalankan:
    python tes_manual_jadwal.py
"""
import sys
from zk_admin import (
    _login_get_cookiejar, set_timezone, set_group, list_users, set_user_group,
)
from zk_web import ZKWebError
import tempfile
import os

DEVICE_IP = "10.17.44.162"
USERNAME  = "1"
PASSWORD  = "8888"

TZ_SELALU_BUKA  = 40   # TZ index yang akan diset "selalu buka" (00:00-23:59 tiap hari)
TZ_SELALU_TUTUP = 41   # TZ index yang akan diset "selalu tutup" (end < start tiap hari)
GID_BUKA  = 90
GID_TUTUP = 91


def jeda(pesan):
    input(f"\n>> {pesan}\nTekan ENTER untuk lanjut...\n")


def main():
    with tempfile.TemporaryDirectory() as tmpdir:
        cookie_file = os.path.join(tmpdir, "cookies.txt")

        print("=" * 60)
        print("STEP 1 — Login ke device")
        print("=" * 60)
        try:
            _login_get_cookiejar(DEVICE_IP, USERNAME, PASSWORD, cookie_file)
            print("✓ Login berhasil")
        except ZKWebError as e:
            print("✗ Login GAGAL:", e)
            sys.exit(1)

        print("\n" + "=" * 60)
        print(f"STEP 2 — Set TZ {TZ_SELALU_BUKA} = SELALU BUKA (00:00-23:59 semua hari)")
        print("=" * 60)
        jadwal_buka = {h: ("00:00", "23:59") for h in
                       ["minggu", "senin", "selasa", "rabu", "kamis", "jumat", "sabtu"]}
        set_timezone(DEVICE_IP, cookie_file, TZ_SELALU_BUKA, jadwal_buka)
        print(f"✓ TZ {TZ_SELALU_BUKA} diset selalu buka")

        print("\n" + "=" * 60)
        print(f"STEP 3 — Set TZ {TZ_SELALU_TUTUP} = SELALU TUTUP (end < start, semua hari)")
        print("=" * 60)
        # Tidak masukkan hari apapun ke jadwal_mingguan -> otomatis 23:59-00:00 (tutup) semua hari
        set_timezone(DEVICE_IP, cookie_file, TZ_SELALU_TUTUP, {})
        print(f"✓ TZ {TZ_SELALU_TUTUP} diset selalu tutup")

        print("\n" + "=" * 60)
        print(f"STEP 4 — Set Group {GID_BUKA} -> pakai TZ {TZ_SELALU_BUKA} di ketiga slot")
        print("=" * 60)
        set_group(DEVICE_IP, cookie_file, GID_BUKA, TZ_SELALU_BUKA, TZ_SELALU_BUKA, TZ_SELALU_BUKA)
        print(f"✓ Group {GID_BUKA} -> TZ {TZ_SELALU_BUKA} (buka)")

        print("\n" + "=" * 60)
        print(f"STEP 5 — Set Group {GID_TUTUP} -> pakai TZ {TZ_SELALU_TUTUP} di ketiga slot")
        print("=" * 60)
        set_group(DEVICE_IP, cookie_file, GID_TUTUP, TZ_SELALU_TUTUP, TZ_SELALU_TUTUP, TZ_SELALU_TUTUP)
        print(f"✓ Group {GID_TUTUP} -> TZ {TZ_SELALU_TUTUP} (tutup)")

        print("\n" + "=" * 60)
        print("STEP 6 — Ambil daftar user dari device")
        print("=" * 60)
        users = list_users(DEVICE_IP, cookie_file)
        for u in users:
            print(f"  PIN={u['pin']:<6} uid={u['uid']:<4} nama={u['nama']}")

        pin_target = input("\nMasukkan PIN user yang mau dites (contoh: 4 untuk Fatah): ").strip()
        target = next((u for u in users if u["pin"] == pin_target), None)
        if not target:
            print(f"✗ PIN {pin_target} tidak ditemukan di device")
            sys.exit(1)

        print("\n" + "=" * 60)
        print(f"STEP 7 — Assign user PIN {pin_target} ke Group {GID_BUKA} (SELALU BUKA)")
        print("=" * 60)
        set_user_group(DEVICE_IP, cookie_file, target["uid"], target["pin"], target["nama"], GID_BUKA)
        print(f"✓ User PIN {pin_target} sekarang di Group {GID_BUKA} (harusnya SELALU BISA akses)")
        jeda(f"COBA SCAN user PIN {pin_target} SEKARANG di alat fisik. Harusnya BERHASIL/hijau.")

        print("\n" + "=" * 60)
        print(f"STEP 8 — Assign user PIN {pin_target} ke Group {GID_TUTUP} (SELALU TUTUP)")
        print("=" * 60)
        set_user_group(DEVICE_IP, cookie_file, target["uid"], target["pin"], target["nama"], GID_TUTUP)
        print(f"✓ User PIN {pin_target} sekarang di Group {GID_TUTUP} (harusnya SELALU DITOLAK)")
        jeda(f"COBA SCAN user PIN {pin_target} SEKARANG di alat fisik. Harusnya DITOLAK/merah.")

        print("\n" + "=" * 60)
        print("SELESAI — laporkan hasil kedua tes scan fisik di atas.")
        print("=" * 60)


if __name__ == "__main__":
    main()