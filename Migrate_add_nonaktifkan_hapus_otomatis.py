"""
migrate_add_nonaktifkan_hapus_otomatis.py
=========================================================
Migrasi kecil (project ini tidak pakai Alembic — lihat
Dokumentasi_Setup_Smart_Door_Lock.md bagian 7) untuk menambah kolom baru
yang dipakai fitur "Nonaktifkan Penghapusan Otomatis" di halaman
Pengaturan:

  pengaturan_sistem.nonaktifkan_hapus_otomatis_global
                                  — toggle GLOBAL (semua alat), default False
  ruangan.nonaktifkan_hapus_otomatis
                                  — toggle PER-RUANGAN (1 atau beberapa
                                    alat saja), default False

Saat salah satu aktif, endpoint GET /device-bridge/to-remove akan
selalu kosong untuk ruangan yang bersangkutan, jadi data user di alat
TIDAK dihapus otomatis lagi walau jadwalnya sudah tidak ada.

`Base.metadata.create_all()` di main.py TIDAK menambah kolom baru ke
tabel yang sudah ada (hanya membuat tabel yang belum ada), jadi kolom
ini perlu ditambah manual sekali lewat script ini.

Jalankan sekali saja, setelah menarik update kode ini:
    source venv/bin/activate
    python migrate_add_nonaktifkan_hapus_otomatis.py
"""
from sqlalchemy import text
from app.database import engine

STATEMENTS_POSTGRES = [
    "ALTER TABLE pengaturan_sistem ADD COLUMN IF NOT EXISTS nonaktifkan_hapus_otomatis_global BOOLEAN NOT NULL DEFAULT FALSE",
    "ALTER TABLE ruangan ADD COLUMN IF NOT EXISTS nonaktifkan_hapus_otomatis BOOLEAN NOT NULL DEFAULT FALSE",
]

# SQLite tidak mendukung "ADD COLUMN IF NOT EXISTS", jadi dicek manual.
STATEMENTS_SQLITE = [
    ("pengaturan_sistem", "nonaktifkan_hapus_otomatis_global",
     "ALTER TABLE pengaturan_sistem ADD COLUMN nonaktifkan_hapus_otomatis_global BOOLEAN NOT NULL DEFAULT 0"),
    ("ruangan", "nonaktifkan_hapus_otomatis",
     "ALTER TABLE ruangan ADD COLUMN nonaktifkan_hapus_otomatis BOOLEAN NOT NULL DEFAULT 0"),
]


def migrate():
    dialect = engine.dialect.name
    print(f"Database dialect terdeteksi: {dialect}")

    with engine.begin() as conn:
        if dialect == "postgresql":
            for stmt in STATEMENTS_POSTGRES:
                print(f"  > {stmt}")
                conn.execute(text(stmt))
        elif dialect == "sqlite":
            for table, col_name, stmt in STATEMENTS_SQLITE:
                existing_cols = {
                    row[1] for row in conn.execute(text(f"PRAGMA table_info({table})"))
                }
                if col_name in existing_cols:
                    print(f"  - kolom '{table}.{col_name}' sudah ada, skip")
                    continue
                print(f"  > {stmt}")
                conn.execute(text(stmt))
        else:
            raise RuntimeError(
                f"Dialect '{dialect}' belum didukung script ini — "
                f"tambahkan kolom-kolom di atas ke tabel terkait secara manual."
            )

    print("Migrasi selesai.")


if __name__ == "__main__":
    migrate()