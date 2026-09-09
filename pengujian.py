"""
pengujian_4_2_3.py
=============================================================
Simulator LOKAL untuk reproduksi 5 skenario Tabel 4.5
(Pengujian Validasi Akses Berbasis Jadwal KBM) — subbab 4.2.3.

PENTING soal waktu:
Server memvalidasi jadwal berdasarkan `datetime` YANG DILAPORKAN DI
DALAM payload log (bukan jam sistem real-time saat push-logs diterima).
Makanya script ini bisa membuat kondisi persis seperti di tabel
pengujian — "jadwal 01:00–10:00 aktif, scan pukul 08:07" — kapan pun
script dijalankan, tanpa bergantung jam asli di komputer kamu.

Skenario & hasil yang diharapkan (Tabel 4.5):
 1. Jadwal 01:00–10:00 aktif, mhs 6CC terdaftar, scan 08:07
    -> "Berhasil"
 2. Tidak ada jadwal aktif, mhs scan
    -> "Ditolak" — "Tidak ada jadwal aktif saat ini"
 3. Jadwal aktif kelas 6CC, mhs kelas 6CM scan
    -> "Ditolak" — "Tidak terdaftar di Praktek Sistem Multimedia (6CC)"
 4. Tidak ada jadwal aktif, admin scan
    -> "Berhasil" — "Akses bebas (admin)"
 5. Jadwal aktif untuk kelas yang diampu, dosen scan
    -> "Berhasil" — keterangan menyertakan nama kegiatan

CARA PAKAI
----------
1. Jalankan server FastAPI di terminal terpisah:
       uvicorn main:app --reload

2. Pastikan data sudah ada (jalankan sekali jika belum):
       python seed.py
       python seed_real.py

3. Jalankan dari root project:
       python pengujian_4_2_3.py

4. Script berhenti sejenak (tekan Enter) di antara tiap skenario —
   screenshot dashboard (halaman Log Akses) sebelum lanjut.

Ruangan: "Lab Multimedia 2" (sesuai seed_real.py). Ganti NAMA_RUANGAN
di bawah kalau kamu memakai ruangan lain.
"""

import os
import sys
import requests
from datetime import datetime, timedelta, date, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

from app.database import SessionLocal
from app.models.models import User, Ruangan, JadwalRuangan, AccessLog, Absensi

# ── Konfigurasi ────────────────────────────────────────────────
BASE_URL     = os.getenv("SIM_BASE_URL", "http://localhost:8000")
API_KEY      = os.getenv("BRIDGE_API_KEY", "bridge-key-polsri-2026")
NAMA_RUANGAN = "Lab Multimedia 2"
DEVICE_SN    = "SIM-LOCAL-0001"
WIB          = timezone(timedelta(hours=7))

# Kondisi persis sesuai Tabel 4.5 di laporan
JADWAL_MULAI = "01:00"
JADWAL_SELESAI = "10:00"
JAM_SCAN = "08:07"   # dipakai untuk skenario 1 & 3 (dalam rentang jadwal aktif)

HEADERS = {"X-API-Key": API_KEY, "Content-Type": "application/json"}

_ruangan_id_cache = None


def wib_now():
    return datetime.now(timezone.utc).astimezone(WIB)


def waktu_scan(jam_str: str) -> datetime:
    """Bangun datetime WIB untuk hari ini pada jam tetap (mis. '08:07'),
    ditambah detik dari waktu asli sekarang supaya tiap run tetap unik
    (server menandai log dengan waktu_akses identik persis sebagai
    duplikat)."""
    today = date.today()
    jam, menit = map(int, jam_str.split(":"))
    detik = wib_now().second
    return datetime(today.year, today.month, today.day, jam, menit, detik, tzinfo=WIB)


def garis(judul=""):
    print("\n" + "=" * 70)
    if judul:
        print(f"  {judul}")
        print("=" * 70)


def jeda(pesan="Tekan Enter untuk lanjut ke skenario berikutnya..."):
    input(f"\n>> {pesan}\n")


def get_ruangan_id():
    global _ruangan_id_cache
    if _ruangan_id_cache:
        return _ruangan_id_cache
    db = SessionLocal()
    try:
        r = db.query(Ruangan).filter(Ruangan.nama.ilike(f"%{NAMA_RUANGAN}%")).first()
    finally:
        db.close()
    if not r:
        print(f"❌ Ruangan '{NAMA_RUANGAN}' tidak ditemukan. Jalankan seed_real.py dulu.")
        sys.exit(1)
    _ruangan_id_cache = r.id
    return r.id


def kirim_log(pin: int, waktu: datetime, label: str):
    """Kirim satu log seolah-olah dari x606_bridge.py (verified=15 -> face)."""
    payload = {
        "ruangan_id": get_ruangan_id(),
        "device_sn": DEVICE_SN,
        "logs": [{
            "pin": str(pin),
            "datetime": waktu.strftime("%Y-%m-%d %H:%M:%S+07:00"),
            "verified": 15,
            "status": 0,
            "workcode": "0",
        }],
    }
    print(f"\n→ Mengirim scan simulasi: {label}")
    print(f"  PIN(id_perangkat)={pin} | waktu dilaporkan={payload['logs'][0]['datetime']}")
    try:
        r = requests.post(f"{BASE_URL}/device-bridge/push-logs", json=payload, headers=HEADERS, timeout=10)
    except Exception as e:
        print(f"❌ Gagal konek ke server lokal: {e}")
        print("   Pastikan `uvicorn main:app --reload` sudah jalan.")
        sys.exit(1)
    print(f"  Response [{r.status_code}]: {r.json()}")
    return r


def ambil_log_terakhir(user_id: int):
    db = SessionLocal()
    try:
        log = (
            db.query(AccessLog)
            .filter(AccessLog.user_id == user_id, AccessLog.ruangan_id == get_ruangan_id())
            .order_by(AccessLog.waktu_akses.desc())
            .first()
        )
    finally:
        db.close()
    if log:
        print("\n  📋 access_log tersimpan:")
        print(f"     id={log.id} | status={log.status} | metode={log.metode}")
        print(f"     keterangan=\"{log.keterangan}\"")
        print(f"     waktu_akses={log.waktu_akses}")
    else:
        print("  ⚠ Tidak ditemukan baris access_log baru untuk user ini.")
    return log


class UserSnap:
    """Salinan data user sebagai nilai biasa (bukan objek ORM terikat
    session), supaya aman dipakai lintas fungsi/lintas session tanpa
    DetachedInstanceError."""
    def __init__(self, u):
        self.id = u.id
        self.nama = u.nama
        self.id_perangkat = u.id_perangkat
        self.kelas = u.kelas


def ambil_data():
    db = SessionLocal()
    try:
        mhs_6cc = db.query(User).filter(User.role == "mahasiswa", User.kelas == "6CC", User.id_perangkat.isnot(None)).first()
        mhs_6cm = db.query(User).filter(User.role == "mahasiswa", User.kelas == "6CM", User.id_perangkat.isnot(None)).first()
        dosen   = db.query(User).filter(User.role == "dosen", User.id_perangkat.isnot(None)).first()
        admin   = db.query(User).filter(User.role == "admin", User.id_perangkat.isnot(None)).first()

        if not all([mhs_6cc, mhs_6cm, dosen, admin]):
            print("❌ Data user tidak lengkap (butuh mahasiswa kelas 6CC, 6CM, dosen, admin dengan id_perangkat terisi).")
            print("   Jalankan `python seed.py` dan `python seed_real.py` dulu.")
            sys.exit(1)

        return UserSnap(mhs_6cc), UserSnap(mhs_6cm), UserSnap(dosen), UserSnap(admin)
    finally:
        db.close()


def set_jadwal_aktif(kelas: str, mahasiswa_id_list, dosen_nama: str,
                      jam_mulai: str = JADWAL_MULAI, jam_selesai: str = JADWAL_SELESAI):
    """Bikin/update jadwal KBM untuk HARI INI dengan jam_mulai/jam_selesai
    tetap (default 01:00–10:00 sesuai Tabel 4.5). mahasiswa_id_list
    berisi ID (int), bukan objek ORM — supaya tidak DetachedInstanceError
    lintas session."""
    tanggal = date.today().strftime("%Y-%m-%d")

    db = SessionLocal()
    try:
        j = (
            db.query(JadwalRuangan)
            .filter(
                JadwalRuangan.ruangan_id == get_ruangan_id(),
                JadwalRuangan.nama_kegiatan == "Praktek Sistem Multimedia",
                JadwalRuangan.tanggal == tanggal,
            )
            .first()
        )
        if not j:
            j = JadwalRuangan(
                ruangan_id=get_ruangan_id(),
                nama_kegiatan="Praktek Sistem Multimedia",
                kelas=kelas,
                dosen=dosen_nama,
                tanggal=tanggal,
                jam_mulai=jam_mulai,
                jam_selesai=jam_selesai,
            )
            db.add(j)
            db.flush()
        else:
            j.kelas = kelas
            j.dosen = dosen_nama
            j.jam_mulai = jam_mulai
            j.jam_selesai = jam_selesai

        mahasiswa_list = db.query(User).filter(User.id.in_(mahasiswa_id_list)).all()
        existing_ids = {m.id for m in j.mahasiswa_diizinkan}
        for m in mahasiswa_list:
            if m.id not in existing_ids:
                j.mahasiswa_diizinkan.append(m)

        db.commit()
        jid = j.id
    finally:
        db.close()
    print(f"  ✓ Jadwal uji aktif: id={jid} | kelas={kelas} | {tanggal} {jam_mulai}-{jam_selesai}")
    return jid


def hapus_jadwal_test():
    """Bersihkan jadwal Praktek Sistem Multimedia supaya kondisi 'tidak ada
    jadwal aktif' terpenuhi. Baris `absensi` yang otomatis tercatat saat
    scan berhasil (terhubung via jadwal_id) dihapus dulu, karena kolom
    itu NOT NULL — kalau tidak, penghapusan jadwal akan gagal."""
    db = SessionLocal()
    try:
        rows = db.query(JadwalRuangan).filter(JadwalRuangan.nama_kegiatan == "Praktek Sistem Multimedia").all()
        jadwal_ids = [r.id for r in rows]

        n_absensi = 0
        if jadwal_ids:
            n_absensi = (
                db.query(Absensi)
                .filter(Absensi.jadwal_id.in_(jadwal_ids))
                .delete(synchronize_session=False)
            )

        for r in rows:
            db.delete(r)
        db.commit()
        n = len(rows)
    finally:
        db.close()
    if n or n_absensi:
        print(f"  🧹 Dibersihkan: {n} jadwal simulasi, {n_absensi} baris absensi terkait.")


def main():
    print("Simulasi Pengujian 4.2.3 — Validasi Akses Berbasis Jadwal KBM")
    print(f"Server target : {BASE_URL}")
    print(f"Ruangan       : {NAMA_RUANGAN}")
    print(f"Jadwal aktif  : {JADWAL_MULAI}-{JADWAL_SELESAI} WIB | Jam scan (skenario dalam jadwal): {JAM_SCAN}")

    mhs_6cc, mhs_6cm, dosen, admin = ambil_data()
    hapus_jadwal_test()

    # ── Skenario 1: jadwal 01:00-10:00 aktif, mhs 6CC terdaftar, scan 08:07 ──
    garis("Skenario 1 — Jadwal 01:00–10:00 aktif, mahasiswa terdaftar, scan 08:07")
    set_jadwal_aktif(kelas="6CC", mahasiswa_id_list=[mhs_6cc.id], dosen_nama=dosen.nama)
    kirim_log(mhs_6cc.id_perangkat, waktu_scan(JAM_SCAN), f"{mhs_6cc.nama} (6CC, terdaftar & dalam jadwal, 08:07)")
    ambil_log_terakhir(mhs_6cc.id)
    print("\n  ✅ Ekspektasi: status='Berhasil'")
    jeda()

    # ── Skenario 2: tidak ada jadwal aktif, mhs scan ──
    garis("Skenario 2 — Tidak ada jadwal aktif, mahasiswa scan")
    hapus_jadwal_test()
    kirim_log(mhs_6cc.id_perangkat, wib_now(), f"{mhs_6cc.nama} (tidak ada jadwal aktif)")
    ambil_log_terakhir(mhs_6cc.id)
    print("\n  ✅ Ekspektasi: status='Ditolak', keterangan='Tidak ada jadwal aktif saat ini'")
    jeda()

    # ── Skenario 3: jadwal aktif kelas 6CC, mhs 6CM scan ──
    garis("Skenario 3 — Jadwal aktif kelas 6CC, mahasiswa kelas 6CM scan")
    set_jadwal_aktif(kelas="6CC", mahasiswa_id_list=[mhs_6cc.id], dosen_nama=dosen.nama)
    kirim_log(mhs_6cm.id_perangkat, waktu_scan(JAM_SCAN), f"{mhs_6cm.nama} (6CM, jadwal aktif untuk 6CC, 08:07)")
    ambil_log_terakhir(mhs_6cm.id)
    print('\n  ✅ Ekspektasi: status=\'Ditolak\', keterangan=\'Tidak terdaftar di Praktek Sistem Multimedia (6CC)\'')
    jeda()

    # ── Skenario 4: tidak ada jadwal aktif, admin scan ──
    garis("Skenario 4 — Tidak ada jadwal aktif, admin scan")
    hapus_jadwal_test()
    kirim_log(admin.id_perangkat, wib_now(), f"{admin.nama} (admin, tidak ada jadwal aktif)")
    ambil_log_terakhir(admin.id)
    print("\n  ✅ Ekspektasi: status='Berhasil', keterangan='Akses bebas (admin)'")
    jeda()

    # ── Skenario 5: jadwal aktif untuk kelas yang diampu, dosen scan ──
    garis("Skenario 5 — Jadwal aktif untuk kelas yang diampu, dosen scan")
    set_jadwal_aktif(kelas="6CC", mahasiswa_id_list=[mhs_6cc.id], dosen_nama=dosen.nama)
    kirim_log(dosen.id_perangkat, waktu_scan(JAM_SCAN), f"{dosen.nama} (dosen pengampu 6CC, 08:07)")
    ambil_log_terakhir(dosen.id)
    print("\n  ✅ Ekspektasi: status='Berhasil', keterangan='Dosen — Praktek Sistem Multimedia'")
    print("     (catatan: sistem menulis format 'Dosen — <nama kegiatan>' dengan tanda em dash,")
    print("      bukan 'Dosen <nama kegiatan>' — sesuaikan redaksi tabel bila ingin persis sama)")

    hapus_jadwal_test()
    garis("SELESAI")
    print("Semua 5 skenario Tabel 4.5 sudah dijalankan sesuai kondisi tabel.")
    print("Screenshot dashboard → Log Akses untuk tiap baris hasil di atas sebagai bukti pengujian.")


if __name__ == "__main__":
    main()