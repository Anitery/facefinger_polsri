"""
migrate_add_door_service_url.py
=========================================================
Migrasi kecil (project ini tidak pakai Alembic — lihat
Dokumentasi_Setup_Smart_Door_Lock.md bagian 7) untuk menambah kolom baru
yang dipakai fitur-fitur berikut ke tabel yang SUDAH ADA:

  ruangan.door_service_url       — alamat door_service.py milik ruangan
                                    ini, misal "http://10.17.47.163:8103"
  ruangan.door_service_api_key   — opsional, override API key kalau beda
                                    dari DOOR_SERVICE_API_KEY default

  pengaturan_sistem.toleransi_masuk_awal_menit
                                  — toleransi user boleh scan/masuk
                                    sebelum jam_mulai jadwal (menit),
                                    default 15

`Base.metadata.create_all()` di main.py TIDAK menambah kolom baru ke
tabel yang sudah ada (hanya membuat tabel yang belum ada), jadi kolom
ini perlu ditambah manual sekali lewat script ini.

Jalankan sekali saja, setelah menarik update kode ini:
    source venv/bin/activate
    python migrate_add_door_service_url.py
"""
from sqlalchemy import text
from app.database import engine

STATEMENTS_POSTGRES = [
    "ALTER TABLE ruangan ADD COLUMN IF NOT EXISTS door_service_url VARCHAR(255)",
    "ALTER TABLE ruangan ADD COLUMN IF NOT EXISTS door_service_api_key VARCHAR(255)",
    "ALTER TABLE pengaturan_sistem ADD COLUMN IF NOT EXISTS toleransi_masuk_awal_menit INTEGER NOT NULL DEFAULT 15",
]

# SQLite tidak mendukung "ADD COLUMN IF NOT EXISTS", jadi dicek manual.
STATEMENTS_SQLITE = [
    ("ruangan", "door_service_url", "ALTER TABLE ruangan ADD COLUMN door_service_url VARCHAR(255)"),
    ("ruangan", "door_service_api_key", "ALTER TABLE ruangan ADD COLUMN door_service_api_key VARCHAR(255)"),
    ("pengaturan_sistem", "toleransi_masuk_awal_menit",
     "ALTER TABLE pengaturan_sistem ADD COLUMN toleransi_masuk_awal_menit INTEGER NOT NULL DEFAULT 15"),
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

