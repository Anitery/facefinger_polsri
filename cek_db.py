import sqlite3

# koneksi ke database
conn = sqlite3.connect("smartdoorlock.db")
cursor = conn.cursor()

print("=== STRUKTUR DATABASE smartdoorlock.db ===\n")

# 1. LIST SEMUA TABEL
print("📋 DAFTAR TABEL:")
cursor.execute("SELECT name FROM sqlite_master WHERE type='table';")
tables = cursor.fetchall()
for table in tables:
    print(f"  📁 {table[0]}")
print()

# 2. DETAIL STRUKTUR SETIAP TABEL
for table_name in [t[0] for t in tables]:
    print(f"📊 TABEL: {table_name}")
    print("  Kolom & Tipe Data:")
    
    # Ambil struktur tabel
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()
    
    for col in columns:
        col_id, name, type_, notnull, default, pk = col
        notnull_str = "NOT NULL" if notnull else ""
        pk_str = "PRIMARY KEY" if pk else ""
        print(f"    {name:<20} {type_:<12} {notnull_str} {pk_str}")
    
    # Jumlah rows
    cursor.execute(f"SELECT COUNT(*) FROM {table_name}")
    row_count = cursor.fetchone()[0]
    print(f"    📈 Jumlah data: {row_count:,} rows\n")

# 3. INDEXES
print("🔍 INDEXES:")
cursor.execute("SELECT name, sql FROM sqlite_master WHERE type='index';")
indexes = cursor.fetchall()
if indexes:
    for idx_name, idx_sql in indexes:
        print(f"  {idx_name}: {idx_sql}")
else:
    print("  Tidak ada index")
print()

# 4. SIZE DATABASE
cursor.execute("SELECT page_count * page_size AS size_bytes FROM pragma_page_count(), pragma_page_size();")
db_size = cursor.fetchone()[0]
print(f"💾 Ukuran DB: {db_size:,} bytes ({db_size/1024/1024:.2f} MB)")

conn.close()
print("\n✅ CEK SELESAI!")