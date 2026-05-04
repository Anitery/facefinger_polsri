import sqlite3
import json

# koneksi ke database
conn = sqlite3.connect("smartdoorlock.db")
cursor = conn.cursor()

# ambil semua data user
cursor.execute("SELECT id, nama, nim_nip, face_encoding FROM users")
rows = cursor.fetchall()

print("=== DATA USERS ===\n")

for row in rows:
    user_id, nama, nim_nip, face_encoding = row
    
    print(f"ID   : {user_id}")
    print(f"Nama : {nama}")
    print(f"NIM  : {nim_nip}")
    
    if face_encoding:
        try:
            encoding = json.loads(face_encoding)
            print(f"Face Encoding: ADA ({len(encoding)} dimensi)")
        except:
            print("Face Encoding: ADA (format tidak valid)")
    else:
        print("Face Encoding: NULL ❌")
    
    print("-" * 40)

conn.close()