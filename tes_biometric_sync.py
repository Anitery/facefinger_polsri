"""
tes_biometric_sync.py — Script tes manual untuk biometric_sync.py
=========================================================
Karena ini modul backend (bukan fitur dashboard), script ini biar kamu
bisa coba fungsinya langsung dari terminal, step-by-step.

PENTING: script ini butuh koneksi DATABASE (Postgres/SQLite project
kamu), bukan cuma ke device — karena template disimpan ke DB dulu
sebelum bisa di-push ke device manapun.

Jalankan dari root folder project (yang ada app/ dan main.py):
    python tes_biometric_sync.py
"""
import os
import sys

# Pastikan .env project ke-load (DATABASE_URL, dll.)
from dotenv import load_dotenv
load_dotenv()

from app.database import SessionLocal
from app.models.models import User, BiometricTemplate
from app.services.biometric_sync import download_user_biometrics, push_user_to_device

DEVICE_IP = "10.17.44.162"
COM_KEY   = "0"   # sesuaikan kalau device kamu pakai communication key lain


def jeda(pesan):
    input(f"\n>> {pesan}\nTekan ENTER untuk lanjut...\n")


def main():
    db = SessionLocal()

    print("=" * 60)
    print("STEP 1 — Cari user Fatah di database kita")
    print("=" * 60)
    fatah = db.query(User).filter(User.nim_nip == "062330701511").first()
    if not fatah:
        print("✗ User dengan NIM 062330701511 tidak ditemukan di database.")
        print("  Cek dulu apakah user ini ada — sesuaikan NIM di script ini kalau perlu.")
        sys.exit(1)
    print(f"✓ Ketemu: {fatah.nama} (id_perangkat/PIN = {fatah.id_perangkat})")

    if not fatah.id_perangkat:
        print("✗ User ini belum punya id_perangkat (PIN) terisi di database — isi dulu lewat dashboard Pengguna.")
        sys.exit(1)

    print("\n" + "=" * 60)
    print(f"STEP 2 — Download semua template fingerprint dari device {DEVICE_IP}")
    print("=" * 60)
    jumlah = download_user_biometrics(db, DEVICE_IP, COM_KEY, fatah)
    print(f"✓ {jumlah} template berhasil di-download dan disimpan ke database kita")

    if jumlah == 0:
        print("  Kemungkinan: PIN salah, device tidak online, atau user ini belum enroll fingerprint sama sekali.")
        sys.exit(1)

    print("\n" + "=" * 60)
    print("STEP 3 — Lihat isi template yang tersimpan di DB")
    print("=" * 60)
    templates = db.query(BiometricTemplate).filter(BiometricTemplate.user_id == fatah.id).all()
    for t in templates:
        preview = (t.template or "")[:50]
        print(f"  finger_id={t.finger_id} | size={t.size} | valid={t.valid} | template (preview 50 char): {preview}...")

    jeda(
        "Template sudah tersimpan di database kita (bukan cuma di device). "
        "Lanjut ke STEP 4 untuk coba PUSH BALIK ke device yang SAMA "
        "(sanity check — kalau berhasil, artinya data ini valid untuk dipakai duplikasi ke device lain nanti)."
    )

    print("\n" + "=" * 60)
    print(f"STEP 4 — Push balik ke device {DEVICE_IP} (sanity check)")
    print("=" * 60)
    print("PERINGATAN: ini akan MENIMPA data user Fatah di device dengan data yang baru saja di-download.")
    konfirmasi = input("Ketik 'ya' untuk lanjut, atau apapun lain untuk batal: ").strip().lower()
    if konfirmasi != "ya":
        print("Dibatalkan.")
        db.close()
        return

    berhasil = push_user_to_device(db, DEVICE_IP, COM_KEY, fatah)
    if berhasil:
        print("✓ Push berhasil! Coba scan fingerprint Fatah di alat sekarang — harusnya tetap berhasil seperti biasa.")
    else:
        print("✗ Push GAGAL — cek pesan error di atas (kalau ada) atau koneksi ke device.")

    jeda("Coba scan fingerprint di alat SEKARANG untuk konfirmasi.")

    db.close()
    print("\nSelesai.")


if __name__ == "__main__":
    main()