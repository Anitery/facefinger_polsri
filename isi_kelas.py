"""
Isi kolom kelas pada tabel users dengan data real 6CC dan 6CM.
Jalankan: python isi_kelas.py
"""
from app.database import SessionLocal
from app.models.models import User

db = SessionLocal()

DATA_6CC = [
    ("062330701435", "AGUNG DILA UTAMA"),
    ("062330701436", "AL-MAN RAFFLI SAPUTRA"),
    ("062330701437", "APRILIA DAMAYANTI"),
    ("062330701438", "DZIKRY FADILLAH"),
    ("062330701439", "FAHREZI ISLAMI PASHA"),
    ("062330701440", "FAZA LA AMY"),
    ("062330701441", "ILHAM PUTRA PANI"),
    ("062330701442", "JERY JULIANSYAH"),
    ("062330701443", "M FIQIULUM"),
    ("062330701444", "M. ARIF RAHMAN"),
    ("062330701445", "M. DZAKY DARMAWAN"),
    ("062330701446", "MEILA PUTRI"),
    ("062330701447", "MUHAMMAD ABSHORUDDIN"),
    ("062330701448", "MUHAMMAD ATHIRA RAMADHAN"),
    ("062330701449", "MUHAMMAD REZA PUTRA RAMADHANI"),
    ("062330701450", "MUTTIA BELLA MEYSHA"),
    ("062330701451", "NADIA SEPTIANA"),
    ("062330701452", "NICCO DWI SATRIA"),
    ("062330701453", "RIDHO FEBRIAN"),
    ("062330701454", "RIZKI ANUGRAH"),
    ("062330701455", "SILPI HAIRUNNISA"),
    ("062330701456", "TIO SANDIKA"),
    ("062330701457", "WINDA MUFIDAH"),
]

DATA_6CM = [
    ("062330701530", "ADLIN ILHAM"),
    ("062330701531", "AMANDA FITRI ZASKIA"),
    ("062330701532", "BAGASKARA ADITYA"),
    ("062330701533", "FAJAR ALIANSYA"),
    ("062330701534", "INTAN MAHDALENA"),
    ("062330701535", "M FARIZ YUSUF HABIBIE"),
    ("062330701536", "M. AKBAR FADHILAH"),
    ("062330701537", "M. RASYID GYMNASTIAR"),
    ("062330701538", "M.ETO ATTHOILLAH"),
    ("062330701539", "M.WILDAN HABIB"),
    ("062330701540", "MUHAMMAD AGAM RAMADHAN"),
    ("062330701541", "MUHAMMAD ARROHMAN"),
    ("062330701542", "MUHAMMAD FATIH FARHAN"),
    ("062330701543", "MUHAMMAD RIZKY ANANDA"),
    ("062330701544", "REZA AL GIFFARI"),
    ("062330701545", "RIZKY CHAVENESI"),
    ("062330701546", "SANJAYA ANDRIAN SYAHPUTRA"),
    ("062330701547", "WAHYU GUSTIANSYAH"),
    ("062330701548", "YAZID ZINADIN ZIDAN"),
    ("062330701549", "ZAKIA PUTRI"),
]

def isi_kelas(data_list, kelas):
    updated, not_found = 0, []
    for nim, nama in data_list:
        u = db.query(User).filter(User.nim_nip == nim).first()
        if u:
            u.kelas = kelas
            updated += 1
        else:
            not_found.append(f"{nim} - {nama}")
    return updated, not_found

print("\n=== Isi Kolom Kelas ===")
upd_cc, nf_cc = isi_kelas(DATA_6CC, "6CC")
upd_cm, nf_cm = isi_kelas(DATA_6CM, "6CM")
db.commit()

print(f"6CC: {upd_cc}/{len(DATA_6CC)} berhasil diupdate")
if nf_cc:
    print("  Tidak ditemukan:", nf_cc)
print(f"6CM: {upd_cm}/{len(DATA_6CM)} berhasil diupdate")
if nf_cm:
    print("  Tidak ditemukan:", nf_cm)

db.close()
print("\nSelesai.")