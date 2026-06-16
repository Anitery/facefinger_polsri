"""
Hapus tabel-tabel sisa dari arsitektur X606 generasi lama
(x606_models.py) yang sudah tidak dipakai kode manapun.

Urutan DROP memperhatikan foreign key — tabel anak dihapus
lebih dulu sebelum tabel induk.

Jalankan: python cleanup_old_tables.py
"""
from sqlalchemy import text
from app.database import engine

TABEL_DIHAPUS = [
    # Tabel anak (punya FK ke tabel lain) — dihapus dulu
    "absensi_x606",
    "x606_jadwal_peserta",
    "x606_user_cache",
    # Tabel induk
    "x606_jadwal_kbm",
    "x606_devices",
]

print("\n" + "=" * 55)
print("  Pembersihan Tabel X606 Generasi Lama")
print("=" * 55)

with engine.connect() as conn:
    for tabel in TABEL_DIHAPUS:
        try:
            conn.execute(text(f"DROP TABLE IF EXISTS {tabel}"))
            conn.commit()
            print(f"  ✓ Tabel '{tabel}' dihapus")
        except Exception as e:
            print(f"  ✗ Gagal hapus '{tabel}': {e}")

print("\n✅ Pembersihan selesai. Tabel yang tersisa:")

with engine.connect() as conn:
    result = conn.execute(text(
        "SELECT name FROM sqlite_master WHERE type='table' "
        "AND name NOT LIKE 'sqlite_%' ORDER BY name"
    ))
    for row in result:
        print(f"  📁 {row[0]}")

print("=" * 55 + "\n")