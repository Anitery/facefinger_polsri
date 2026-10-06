from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request, Query
from sqlalchemy.orm import Session
from sqlalchemy import func, cast, String
from pydantic import BaseModel, Field
from typing import List, Optional
import json
import logging
import re
import requests
from app.database import get_db
from app.models.models import User, BiometricTemplate, UserDeviceSync
from app.schemas import UserCreate, UserOut, UserUpdate
import bcrypt

log = logging.getLogger(__name__)


def _generate_pin_dari_nim(nim_nip: str, db: Session, exclude_user_id: Optional[int] = None) -> str:
    """
    Hasilkan ID Perangkat (PIN) mahasiswa dari NIM/NPM secara otomatis.

    BUG LAMA: PIN selalu diambil dari 4 digit terakhir NIM tanpa
    pengecekan sama sekali — dua NIM yang beda tapi kebetulan 4 digit
    terakhirnya sama (misal 062330701514 dan 062320701514, sama-sama
    berakhiran "1514") akan diberi PIN IDENTIK, dan sistem tidak pernah
    memberi peringatan soal itu. Akibatnya di alat, dua mahasiswa itu
    bisa saling tertukar datanya.

    Perbaikannya: tetap mulai dari 4 digit terakhir (supaya PIN singkat
    seperti kebiasaan lama), tapi begitu ternyata sudah dipakai user
    lain, otomatis diperpanjang jadi 5, 6, 7 digit dst. dari belakang
    NIM sampai ketemu yang belum dipakai siapapun DAN digit depannya bukan 0.
    """
    digits_only = re.sub(r"\D", "", nim_nip or "")
    if not digits_only:
        raise HTTPException(400, "NIM/NPM harus mengandung angka untuk menghasilkan ID Perangkat otomatis")

    for panjang in range(4, len(digits_only) + 1):
        kandidat = digits_only[-panjang:]
        # Kandidat yang diawali angka 0 (mis. "0026", "00026") DILEWATI: kolom
        # ID Perangkat diperlakukan sebagai angka, sehingga "0026" akan
        # tersimpan sebagai 26 (tidak sama dengan yang ditampilkan/dihitung).
        # Digit terus ditambah dari belakang NIM sampai digit depannya bukan 0
        # (mis. NIM ...700026 -> 0026 dan 00026 dilewati -> 700026).
        if kandidat.startswith("0"):
            continue
        q = db.query(User).filter(User.id_perangkat == int(kandidat))
        if exclude_user_id:
            q = q.filter(User.id != exclude_user_id)
        if not q.first():
            return kandidat

    raise HTTPException(
        400,
        f"Tidak bisa membuat ID Perangkat unik dari NIM {nim_nip} — kemungkinan "
        f"NIM ini sendiri sudah pernah dipakai user lain. Isi ID Perangkat manual."
    )


def _id_perangkat_kosong_terkecil(db: Session, exclude_user_id: Optional[int] = None) -> int:
    """
    Cari ID Perangkat (PIN) terkecil yang belum dipakai siapapun, mulai dari 1.
    Contoh: terpakai {1,2,3,4,5}        -> 6
            terpakai {1,2,3,4,5,20}     -> 6, lalu 7, 8, ... (20 tidak dilewati/terganggu)
            terpakai {1,2,4}            -> 3 (celah kosong diisi dulu)
    Dipakai untuk staff (admin/dosen/teknisi/magang) yang ID Perangkat-nya
    dikosongkan saat ditambahkan.
    """
    q = db.query(User.id_perangkat).filter(User.id_perangkat.isnot(None))
    if exclude_user_id:
        q = q.filter(User.id != exclude_user_id)
    terpakai = {r[0] for r in q.all()}
    kandidat = 1
    while kandidat in terpakai:
        kandidat += 1
    return kandidat


def _hapus_akses_fisik_dari_semua_device(user: User, db: Session, hapus_template_db: bool):
    """
    Hapus PIN user ini dari SETIAP device tempat dia pernah tercatat
    synced/provisioned (lihat UserDeviceSync) — supaya user yang sudah
    dihapus/dinonaktifkan di server TIDAK lagi bisa buka pintu secara
    fisik lewat fingerprint di device manapun, walau datanya masih
    tersisa dari sinkronisasi sebelumnya.

    Best-effort: kalau sebuah device/STB sedang offline, penghapusan di
    device itu gagal tapi TIDAK membatalkan aksi hapus/nonaktifkan user
    di database — hanya dicatat sebagai warning. Loop sync biometrik
    (roster-driven) pada akhirnya akan berhenti mem-provision ulang user
    ini karena dia sudah tidak ada di roster.
    """
    from app.routers.device_bridge import resolve_door_service

    pin = str(user.id_perangkat) if user.id_perangkat else None
    if pin:
        syncs = db.query(UserDeviceSync).filter(UserDeviceSync.user_id == user.id).all()
        for s in syncs:
            try:
                url, api_key = resolve_door_service(s.ruangan_id, db)
                requests.post(
                    f"{url}/remove-users",
                    headers={"X-API-Key": api_key},
                    json={"pins": [pin]},
                    timeout=15,
                )
            except Exception as e:
                log.warning(
                    f"Gagal hapus PIN {pin} ({user.nama}) dari device ruangan {s.ruangan_id}: {e}"
                )

    db.query(UserDeviceSync).filter(UserDeviceSync.user_id == user.id).delete()
    if hapus_template_db:
        db.query(BiometricTemplate).filter(BiometricTemplate.user_id == user.id).delete()

def _hash_pw(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

def _verify_pw(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except Exception:
        return False

router = APIRouter(prefix="/users", tags=["Pengguna"])

class FaceEncodingPayload(BaseModel):
    encoding: List[float]

# --- Ranks & Permissions Constants ---
# Tier role (atas -> bawah):
# 1. admin  2. dosen_privilege  3. teknisi  4. dosen  5. magang  6. mahasiswa
ROLE_ORDER = {
    "admin": 0, "dosen_privilege": 1, "teknisi": 2,
    "dosen": 3, "magang": 4, "mahasiswa": 5,
}

ROLE_ALLOWED_TO_CREATE = {
    "admin":   {"admin", "dosen_privilege", "teknisi", "dosen", "magang", "mahasiswa"},
    # Dosen privilege: mengelola dosen, magang, dan mahasiswa.
    "dosen_privilege": {"dosen", "magang", "mahasiswa"},
    "dosen":   {"mahasiswa"},
    "teknisi": {"dosen"},
    # Magang: sesuai batasan aksesnya, hanya boleh menginput data mahasiswa.
    "magang":  {"mahasiswa"},
}

ROLE_ALLOWED_TO_MODIFY = {
    "admin":   {"admin", "dosen_privilege", "teknisi", "dosen", "magang", "mahasiswa"},
    "dosen_privilege": {"dosen", "magang", "mahasiswa"},
    "dosen":   {"mahasiswa"},
    "teknisi": {"dosen"},
    "magang":  {"mahasiswa"},
}

# --- Helper Functions ---
def get_current_role(request: Request) -> str:
    from app.services.auth_service import decode_session_token
    token = request.cookies.get("session_token")
    if not token:
        raise HTTPException(status_code=401, detail="Sesi tidak valid")
    return decode_session_token(token)["role"]

# --- Face & Fingerprint Endpoints ---
@router.post("/{user_id}/enroll-face")
def enroll_face(
    user_id: int,
    payload: FaceEncodingPayload,
    db: Session = Depends(get_db)
):
    """Simpan face encoding hasil proses face-api.js dari browser."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    if len(payload.encoding) != 128:
        raise HTTPException(
            status_code=400,
            detail=f"Encoding harus 128 dimensi, diterima {len(payload.encoding)}"
        )
    user.face_encoding = json.dumps(payload.encoding)
    db.commit()
    return {
        "pesan":   f"Face encoding {user.nama} berhasil disimpan",
        "user_id": user.id,
        "nama":    user.nama
    }

@router.delete("/{user_id}/enroll-face")
def hapus_face(user_id: int, db: Session = Depends(get_db)):
    """Hapus face encoding user."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    user.face_encoding = None
    db.commit()
    return {"pesan": f"Face encoding {user.nama} dihapus"}

@router.put("/{user_id}/face-encoding")
def update_face_encoding(user_id: int, encoding: list[float], db: Session = Depends(get_db)):
    """Simpan/update encoding wajah pengguna (128 dimensi)."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    if len(encoding) != 128:
        raise HTTPException(status_code=400, detail="Encoding harus 128 dimensi")
    user.face_encoding = json.dumps(encoding)
    db.commit()
    return {"pesan": f"Face encoding user {user.nama} berhasil disimpan"}

@router.patch("/{user_id}/fingerprint")
def update_fingerprint(user_id: int, fingerprint_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")

    # BUG LAMA: tidak ada pengecekan sama sekali, jadi 2 user bisa saja
    # diberi ID Perangkat yang sama persis tanpa peringatan.
    pemilik_lain = db.query(User).filter(
        User.id_perangkat == fingerprint_id, User.id != user_id
    ).first()
    if pemilik_lain:
        raise HTTPException(
            status_code=400,
            detail=(
                f"ID Perangkat {fingerprint_id} sudah dipakai oleh {pemilik_lain.nama} "
                f"({pemilik_lain.nim_nip}). Setiap ID Perangkat harus unik — gunakan PIN lain."
            ),
        )

    user.id_perangkat = fingerprint_id
    db.commit()
    return {"pesan": f"ID Perangkat {fingerprint_id} disimpan untuk {user.nama}"}


@router.post("/{user_id}/fingerprint-otomatis")
def set_fingerprint_otomatis(user_id: int, db: Session = Depends(get_db)):
    """
    Hasilkan & simpan ID Perangkat mahasiswa otomatis dari NIM-nya,
    dengan pengecekan anti-duplikat (lihat _generate_pin_dari_nim).
    Dipakai frontend menggantikan perhitungan 4-digit-terakhir yang dulu
    dilakukan di JS tanpa validasi apapun ke server.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")

    pin = _generate_pin_dari_nim(user.nim_nip, db, exclude_user_id=user.id)
    user.id_perangkat = int(pin)
    db.commit()
    return {
        "pesan": f"ID Perangkat {pin} disimpan untuk {user.nama}",
        "id_perangkat": pin,
        "diperpanjang": len(pin) > 4,
    }


@router.post("/{user_id}/id-perangkat-otomatis")
def set_id_perangkat_otomatis(
    user_id: int,
    paksa: bool = Query(False, description="True = hitung ulang nomor kosong terkecil walau user sudah punya ID Perangkat (dipakai saat EDIT staff yang kolom ID Perangkat-nya tidak diubah)"),
    db: Session = Depends(get_db),
):
    """
    Beri ID Perangkat otomatis (nomor kosong terkecil) untuk user non-mahasiswa.

    - paksa=False (default, dipakai saat TAMBAH): kalau user ini SUDAH punya
      ID Perangkat, tidak diubah sama sekali (aman dipanggil berulang).
    - paksa=True (dipakai saat EDIT ketika kolom ID Perangkat dibiarkan/dikosongkan):
      ID Perangkat dihitung ulang jadi nomor kosong terkecil, dengan
      mengabaikan ID milik user ini sendiri. Contoh: terpakai {1..5} dan user ini
      ber-ID 20 -> menjadi 6. Kalau user ini ber-ID 3 dan 3 memang celah
      terkecil, tetap 3.
    """
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")

    if user.id_perangkat is not None and not paksa:
        return {
            "pesan": f"{user.nama} sudah punya ID Perangkat {user.id_perangkat}",
            "id_perangkat": user.id_perangkat,
            "dibuat": False,
            "berubah": False,
        }

    lama = user.id_perangkat
    pin = _id_perangkat_kosong_terkecil(db, exclude_user_id=user.id)
    user.id_perangkat = pin
    db.commit()
    return {
        "pesan": f"ID Perangkat {pin} disimpan untuk {user.nama}",
        "id_perangkat": pin,
        "dibuat": lama is None,
        "berubah": lama != pin,
        "sebelumnya": lama,
    }


@router.get("/duplikat-id-perangkat")
def get_duplikat_id_perangkat(db: Session = Depends(get_db)):
    """
    Cari ID Perangkat yang kebetulan dipakai lebih dari 1 user — sisa
    dari bug lama sebelum ada validasi keunikan. Dipakai admin untuk
    membersihkan data yang sudah kadung bentrok di database saat ini.
    """
    dup_ids = db.query(User.id_perangkat).filter(
        User.id_perangkat.isnot(None)
    ).group_by(User.id_perangkat).having(func.count(User.id) > 1).all()
    dup_ids = [d[0] for d in dup_ids]
    if not dup_ids:
        return []

    users = db.query(User).filter(User.id_perangkat.in_(dup_ids)).order_by(User.id_perangkat).all()
    kelompok = {}
    for u in users:
        kelompok.setdefault(u.id_perangkat, []).append({
            "id": u.id, "nama": u.nama, "nim_nip": u.nim_nip,
            "role": u.role, "kelas": u.kelas, "aktif": u.aktif,
        })
    return [{"id_perangkat": pin, "users": daftar} for pin, daftar in sorted(kelompok.items())]


@router.post("/{user_id}/hapus-fingerprint")
def hapus_fingerprint_user(user_id: int, request: Request, db: Session = Depends(get_db)):
    """
    Hapus SEMUA data fingerprint milik 1 user — dari database server DAN
    dari semua alat yang pernah menyimpannya (lewat door_service
    /remove-users di tiap alat terkait). User TETAP AKTIF dan datanya
    yang lain (nama, NIM, riwayat) TIDAK disentuh — cuma template
    fingerprint-nya yang dihapus, supaya bisa didaftarkan ulang dari nol
    lewat Registrasi Biometrik.

    Dibuat khusus untuk membereskan akibat bug duplikasi ID Perangkat
    lama: kalau 2 mahasiswa pernah berbagi 1 PIN yang sama, fingerprint
    salah satu bisa tertimpa/tercampur jadi milik user yang lain di
    database. Setelah PIN masing-masing dibetulkan (lewat Cek Duplikat
    ID Perangkat), gunakan tombol ini untuk menghapus template yang
    salah, baru daftarkan ulang jarinya yang benar.
    """
    current_role = get_current_role(request)
    if current_role not in ("admin", "teknisi"):
        raise HTTPException(403, "Hanya admin/teknisi yang boleh menghapus data fingerprint")

    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(404, "User tidak ditemukan")

    jumlah_template = db.query(BiometricTemplate).filter(BiometricTemplate.user_id == user_id).count()
    if jumlah_template == 0:
        return {"pesan": f"{user.nama} memang belum punya data fingerprint tersimpan.", "dihapus": 0}

    _hapus_akses_fisik_dari_semua_device(user, db, hapus_template_db=True)
    db.commit()

    return {
        "pesan": (
            f"Data fingerprint {user.nama} berhasil dihapus dari server & semua alat. "
            f"Silakan daftar ulang lewat menu Registrasi Biometrik."
        ),
        "dihapus": jumlah_template,
    }

# --- Read Endpoints ---
@router.get("/daftar-kelas")
def get_daftar_kelas(db: Session = Depends(get_db)):
    """Daftar nilai 'kelas' yang unik & terisi — buat isi dropdown filter di halaman Pengguna."""
    rows = db.query(User.kelas).filter(
        User.kelas.isnot(None), User.kelas != ""
    ).distinct().order_by(User.kelas).all()
    return [r[0] for r in rows]


# ── Aturan kelas per jurusan ────────────────────────────────────────────────
# Format kelas: [tingkat][kode jurusan][kode kelas]
#   Teknik Komputer      -> {tingkat}C{A-F/M/N}   contoh 1CF ... 6CF  (tingkat 1–6)
#   Teknologi Informasi  -> {tingkat}TI{A-F/M/N}  contoh 1TIA ... 8TIA (tingkat 1–8)
# Begitu sebuah kelas berada di tingkat maksimal jurusannya, kenaikan
# berikutnya = "Alumni". Ubah konstanta di bawah kalau aturan berubah.
KELAS_ALUMNI = "Alumni"
KODE_KELAS_VALID = "ABCDEFMN"
JURUSAN_KELAS = {
    "C":  {"nama": "Teknik Komputer",     "maks_tingkat": 6},
    "TI": {"nama": "Teknologi Informasi", "maks_tingkat": 8},
}
_POLA_KELAS = re.compile(
    rf"^(\d{{1,2}})(TI|C)([{KODE_KELAS_VALID}])$", re.IGNORECASE
)


def _parse_kelas(kelas_asal: str) -> dict:
    """
    Urai nama kelas lalu hitung kelas tujuannya menurut aturan jurusan.

    Return dict: jurusan ('C'/'TI'), nama_jurusan, tingkat, kode, maks_tingkat,
    kelas_tujuan, jadi_alumni. Raise HTTPException 400 kalau formatnya tidak
    dikenali atau tingkatnya melebihi batas jurusan (mis. 7CF, 9TIA).
    """
    m = _POLA_KELAS.match((kelas_asal or "").strip())
    if not m:
        raise HTTPException(
            400,
            f"Format kelas '{kelas_asal}' tidak dikenali. Format yang benar: "
            f"[tingkat]C[{KODE_KELAS_VALID[:6]}/{KODE_KELAS_VALID[6]}/{KODE_KELAS_VALID[7]}] "
            f"untuk Teknik Komputer (contoh 1CF) atau [tingkat]TI[...] untuk "
            f"Teknologi Informasi (contoh 1TIA).",
        )
    tingkat = int(m.group(1))
    jurusan = m.group(2).upper()
    kode = m.group(3).upper()
    cfg = JURUSAN_KELAS[jurusan]
    maks = cfg["maks_tingkat"]

    if not (1 <= tingkat <= maks):
        raise HTTPException(
            400,
            f"Tingkat {tingkat} tidak valid untuk {cfg['nama']} pada kelas '{kelas_asal}' "
            f"(tingkat 1–{maks}).",
        )

    jadi_alumni = tingkat == maks
    kelas_tujuan = KELAS_ALUMNI if jadi_alumni else f"{tingkat + 1}{jurusan}{kode}"
    return {
        "jurusan": jurusan,
        "nama_jurusan": cfg["nama"],
        "tingkat": tingkat,
        "kode": kode,
        "maks_tingkat": maks,
        "kelas_tujuan": kelas_tujuan,
        "jadi_alumni": jadi_alumni,
    }


def _mahasiswa_aktif_di_kelas(db: Session, kelas: str):
    return db.query(User).filter(
        User.role == "mahasiswa", User.kelas == kelas, User.aktif == True
    ).order_by(User.nama).all()


@router.get("/preview-naik-tingkat")
def preview_naik_tingkat(kelas_asal: str, db: Session = Depends(get_db)):
    """
    Pratinjau sebelum eksekusi: kelas tujuan, aturan jurusan, dan DAFTAR
    mahasiswa aktif di kelas itu (dipakai UI untuk memilih siapa yang
    di-blacklist / tidak ikut naik).
    """
    info = _parse_kelas(kelas_asal)
    mahasiswa = _mahasiswa_aktif_di_kelas(db, kelas_asal)

    # Peringatan urutan: kalau kelas tujuan masih berisi mahasiswa aktif,
    # kemungkinan kelas itu belum dinaikkan duluan (harusnya top-down:
    # tingkat tertinggi dulu) atau sengaja digabung dengan yang tinggal kelas.
    tujuan_terisi = 0
    if not info["jadi_alumni"]:
        tujuan_terisi = db.query(User).filter(
            User.role == "mahasiswa", User.kelas == info["kelas_tujuan"], User.aktif == True
        ).count()

    return {
        "kelas_asal": kelas_asal,
        "kelas_tujuan": info["kelas_tujuan"],
        "jadi_alumni": info["jadi_alumni"],
        "jurusan": info["jurusan"],
        "nama_jurusan": info["nama_jurusan"],
        "tingkat": info["tingkat"],
        "maks_tingkat": info["maks_tingkat"],
        "kelas_tujuan_terisi": tujuan_terisi,
        "jumlah_mahasiswa": len(mahasiswa),
        "mahasiswa": [
            {"id": u.id, "nama": u.nama, "nim_nip": u.nim_nip} for u in mahasiswa
        ],
    }


class NaikTingkatBody(BaseModel):
    # ID mahasiswa yang di-blacklist pada proses ini: TIDAK ikut naik /
    # tidak diluluskan (mis. gagal & mengulang semester). Mereka tetap di
    # kelas asal dan tetap aktif (akses alat tidak dicabut).
    blacklist_user_ids: List[int] = Field(default_factory=list)


@router.post("/naikkan-tingkat")
def naikkan_tingkat_kelas(
    request: Request,
    kelas_asal: str = Query(...),
    body: Optional[NaikTingkatBody] = None,
    db: Session = Depends(get_db),
):
    """
    Naikkan tingkat mahasiswa aktif di 1 kelas sekaligus, dengan aturan
    per jurusan:
      • Teknik Komputer (xC?)     : tingkat 1–6, setelah 6 -> Alumni
      • Teknologi Informasi (xTI?) : tingkat 1–8, setelah 8 -> Alumni
    Mahasiswa yang lulus dari tingkat maksimal dipindah ke kelas "Alumni"
    DAN dinonaktifkan (akses fisik dicabut dari semua alat — data &
    riwayat tetap aman di server).

    `blacklist_user_ids` (opsional, body JSON): mahasiswa yang tidak ikut
    naik / tidak lulus. Kelas & status aktif mereka TIDAK diubah, jadi bisa
    mengulang semester dan otomatis bergabung dengan angkatan berikutnya
    yang naik ke kelas yang sama.
    """
    current_role = get_current_role(request)
    if current_role != "admin":
        raise HTTPException(403, "Hanya admin yang boleh menaikkan tingkat kelas")

    info = _parse_kelas(kelas_asal)
    kelas_tujuan = info["kelas_tujuan"]
    jadi_alumni = info["jadi_alumni"]

    mahasiswa_list = _mahasiswa_aktif_di_kelas(db, kelas_asal)
    if not mahasiswa_list:
        return {"pesan": f"Tidak ada mahasiswa aktif di kelas {kelas_asal}", "dipindah": 0, "ditahan": 0}

    blacklist_ids = set(body.blacklist_user_ids) if body else set()
    ditahan = [m for m in mahasiswa_list if m.id in blacklist_ids]
    dinaikkan = [m for m in mahasiswa_list if m.id not in blacklist_ids]

    if not dinaikkan:
        return {
            "pesan": (
                f"Semua {len(ditahan)} mahasiswa kelas {kelas_asal} di-blacklist — "
                f"tidak ada yang dipindah."
            ),
            "dipindah": 0,
            "ditahan": len(ditahan),
            "ditahan_nama": [m.nama for m in ditahan],
        }

    for m in dinaikkan:
        m.kelas = kelas_tujuan
        if jadi_alumni:
            _hapus_akses_fisik_dari_semua_device(m, db, hapus_template_db=False)
            m.aktif = False

    db.commit()

    if ditahan:
        log.info(
            "Naik tingkat %s -> %s: %d ditahan (blacklist): %s",
            kelas_asal, kelas_tujuan, len(ditahan),
            ", ".join(f"{m.nama} ({m.nim_nip})" for m in ditahan),
        )

    pesan = (
        f"{len(dinaikkan)} mahasiswa dari kelas {kelas_asal} dipindah ke {kelas_tujuan}"
        + (" dan dinonaktifkan (alumni)" if jadi_alumni else "")
    )
    if ditahan:
        pesan += f". {len(ditahan)} mahasiswa di-blacklist dan tetap di kelas {kelas_asal}"

    return {
        "pesan": pesan,
        "dipindah": len(dinaikkan),
        "kelas_tujuan": kelas_tujuan,
        "ditahan": len(ditahan),
        "ditahan_nama": [m.nama for m in ditahan],
    }


# ── Pengurutan kolom tabel Pengguna ─────────────────────────────────────────
# Kolom yang boleh dipakai untuk sort_by. Tanpa sort_by, urutan default
# (role → kelas → nama) tetap dipakai persis seperti sebelumnya.
SORTABLE_COLUMNS = {"nama", "nim_nip", "role", "kelas", "id_perangkat", "fingerprint", "status"}


def _natural_key(teks: str):
    """
    Kunci urutan "alami": angka dibandingkan sebagai angka, huruf tidak
    peduli besar/kecil. Contoh kelas: 1CA < 2CF < 10CA < 8TIN diurutkan
    per tingkat dulu (1, 2, 8, 10), baru kode hurufnya. Tiap bagian diberi
    penanda tipe (0=angka, 1=huruf) supaya tidak pernah membandingkan int vs str.
    """
    bagian = re.findall(r"\d+|\D+", teks or "")
    return [(0, int(b), "") if b.isdigit() else (1, 0, b.casefold()) for b in bagian]


def _nilai_sort(u, kolom: str, jumlah_finger: dict):
    """Nilai pembanding untuk 1 user. Return None = 'kosong' (selalu ditaruh di akhir)."""
    if kolom == "nama":
        return (u.nama or "").casefold() or None
    if kolom == "nim_nip":
        return _natural_key(u.nim_nip) if u.nim_nip else None
    if kolom == "role":
        return ROLE_ORDER.get(u.role, 99)
    if kolom == "kelas":
        return _natural_key(u.kelas.strip()) if u.kelas and u.kelas.strip() else None
    if kolom == "id_perangkat":
        return u.id_perangkat  # int atau None
    if kolom == "fingerprint":
        return jumlah_finger.get(u.id, 0)
    if kolom == "status":
        return 1 if u.aktif else 0
    return None


def _urutkan_users(users: list, kolom: str, arah: str, jumlah_finger: dict) -> list:
    """
    Urutkan berdasarkan 1 kolom. Aturan:
    - Nilai kosong (mis. ID Perangkat 'Belum diset', kelas kosong) SELALU di
      akhir, baik naik maupun turun — supaya data yang berisi tidak tenggelam.
    - Sort Python bersifat stabil, jadi user dengan nilai sama tetap mengikuti
      urutan default (role → kelas → nama) yang sudah terpasang sebelumnya.
    """
    terisi, kosong = [], []
    for u in users:
        v = _nilai_sort(u, kolom, jumlah_finger)
        (kosong if v is None else terisi).append((v, u))
    terisi.sort(key=lambda t: t[0], reverse=(arah == "desc"))
    return [u for _, u in terisi] + [u for _, u in kosong]


@router.get("/")
def get_users(
    request: Request,  # <-- Tambahkan parameter request di sini
    include_inactive: bool = False,
    role:             Optional[str] = None,
    group:            Optional[str] = Query(None, description="Kelompok tabel: 'staff' (semua role selain mahasiswa) atau 'mahasiswa'"),
    kelas:            Optional[str] = None,
    fingerprint:      Optional[str] = Query(None, description="Filter: 'ada', 'belum', atau 'ganda' (>1 jari)"),
    search:           Optional[str] = None,
    sort_by:          Optional[str] = Query(None, description="Urutkan berdasarkan kolom: nama, nim_nip, role, kelas, id_perangkat, fingerprint, status. Kosong = urutan default."),
    sort_dir:         str = Query("asc", pattern="^(asc|desc)$", description="Arah urutan: 'asc' (naik) atau 'desc' (turun)"),
    limit:            int = Query(50, ge=1, le=200),
    page:             int = Query(1,  ge=1),
    db: Session = Depends(get_db)
):
    q = db.query(User)
    if not include_inactive:
        q = q.filter(User.aktif == True)
    if role:
        q = q.filter(User.role == role)
    # Halaman Pengguna dipisah jadi 2 menu (tab): Staff & Mahasiswa.
    # Filter dilakukan di server (bukan di browser) supaya paginasi
    # masing-masing tab akurat — sebelumnya staff & mahasiswa tercampur
    # dalam satu daftar berpaginasi lalu dipisah belakangan di JS.
    if group == "staff":
        q = q.filter(User.role != "mahasiswa")
    elif group == "mahasiswa":
        q = q.filter(User.role == "mahasiswa")
    if kelas:
        q = q.filter(User.kelas == kelas)
    if search:
        # Buang awalan "#" karena di tampilan ID Perangkat ditulis "#1514",
        # sedangkan di database nilainya hanya angka 1514.
        kw = search.strip().lstrip("#")
        if kw:
            q = q.filter(
                User.nama.ilike(f"%{kw}%") |
                User.nim_nip.ilike(f"%{kw}%") |
                User.kelas.ilike(f"%{kw}%") |
                cast(User.id_perangkat, String).ilike(f"%{kw}%")
            )

    # --- FIX 4: Sembunyikan Role Admin dari Dosen, Dosen Privilege, dan Teknisi ---
    try:
        from app.services.auth_service import decode_session_token
        token = request.cookies.get("session_token")
        session = decode_session_token(token) if token else None
        # Jika tidak ada sesi/gagal baca, default sebagai admin agar 
        # tidak sengaja ter-filter jika endpoint diakses secara internal
        viewer_role = session.get("role") if session else "admin"
    except Exception:
        viewer_role = "admin"

    # Filter query database agar admin tidak di-load sama sekali
    if viewer_role in ("dosen", "teknisi", "dosen_privilege", "magang"):
        q = q.filter(User.role != "admin")
    # -------------------------------------------------------------

    all_users = q.all()

    # Jumlah jari (finger_id unik) dihitung per user untuk SELURUH hasil
    # filter di atas (bukan cuma 1 halaman) — supaya filter fingerprint
    # bisa dikombinasikan dengan filter lain + pagination secara
    # konsisten. Dihitung sebagai jumlah, bukan cuma ada/tidak, supaya
    # bisa mendeteksi user dengan >1 jari — indikasi kemungkinan data
    # fingerprint tercampur (bug lama duplikasi ID Perangkat: 2 orang
    # beda sempat berbagi 1 PIN, jadi template salah satunya nempel ke
    # user yang lain).
    jumlah_finger_per_user = {}
    all_ids = [u.id for u in all_users]
    if all_ids:
        rows = db.query(
            BiometricTemplate.user_id, func.count(BiometricTemplate.finger_id)
        ).filter(
            BiometricTemplate.user_id.in_(all_ids)
        ).group_by(BiometricTemplate.user_id).all()
        jumlah_finger_per_user = {r[0]: r[1] for r in rows}

    if fingerprint == "ada":
        all_users = [u for u in all_users if jumlah_finger_per_user.get(u.id, 0) > 0]
    elif fingerprint == "belum":
        all_users = [u for u in all_users if jumlah_finger_per_user.get(u.id, 0) == 0]
    elif fingerprint == "ganda":
        all_users = [u for u in all_users if jumlah_finger_per_user.get(u.id, 0) > 1]

    all_users.sort(key=lambda u: (
        ROLE_ORDER.get(u.role, 99),
        u.kelas or "",
        u.nama or ""
    ))

    # Urutan khusus dari klik header kolom (opsional). Diterapkan SESUDAH urutan
    # default di atas, sehingga default tetap jadi tie-breaker.
    if sort_by in SORTABLE_COLUMNS:
        all_users = _urutkan_users(all_users, sort_by, sort_dir, jumlah_finger_per_user)

    total  = len(all_users)
    offset = (page - 1) * limit
    users  = all_users[offset: offset + limit]

    return {
        "data": [
            {
                "id":             u.id,
                "nama":           u.nama,
                "nim_nip":        u.nim_nip,
                "role":           u.role,
                "kelas":          u.kelas,
                "aktif":          u.aktif,
                "id_perangkat":   u.id_perangkat,
                "punya_template": jumlah_finger_per_user.get(u.id, 0) > 0,
                "jumlah_finger":  jumlah_finger_per_user.get(u.id, 0),
            }
            for u in users
        ],
        "pagination": {
            "total":       total,
            "page":        page,
            "limit":       limit,
            "total_pages": (total + limit - 1) // limit,
            "has_prev":    page > 1,
            "has_next":    page * limit < total,
        }
    }

@router.get("/{user_id}", response_model=UserOut)
def get_user(user_id: int, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    return user

# --- Write/Modify Endpoints ---
@router.post("/", response_model=UserOut)
def create_user(
    payload: UserCreate,
    request: Request,
    db: Session = Depends(get_db)
):
    current_role = get_current_role(request)
    allowed = ROLE_ALLOWED_TO_CREATE.get(current_role, set())
    
    if payload.role not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Role '{current_role}' tidak boleh menambahkan pengguna dengan role '{payload.role}'"
        )

    # Cek apakah NIP/NIM sudah ada
    existing = db.query(User).filter(User.nim_nip == payload.nim_nip).first()
    if existing:
        raise HTTPException(status_code=400, detail="NIM/NIP sudah terdaftar")
        
    user = User(
        nama=payload.nama, 
        nim_nip=payload.nim_nip, 
        role=payload.role,
        kelas=payload.kelas if hasattr(payload, 'kelas') else None, 
        aktif=True,
        # Non-mahasiswa: kalau password dikosongkan, pakai NIM/NIP sebagai password awal.
        # Mahasiswa tidak butuh password (login tidak dipakai), jadi dibiarkan kosong.
        password_hash=(
            _hash_pw(payload.password) if getattr(payload, 'password', None)
            else (_hash_pw(payload.nim_nip) if payload.role != "mahasiswa" else None)
        ),
    )
    
    db.add(user)
    db.commit()
    db.refresh(user)
    return user

@router.put("/{user_id}", response_model=UserOut)
def update_user(
    user_id: int, 
    payload: UserUpdate, 
    request: Request,
    db: Session = Depends(get_db)
):
    current_role = get_current_role(request)
    target = db.query(User).filter(User.id == user_id).first()
    
    if not target:
        raise HTTPException(status_code=404, detail="Pengguna tidak ditemukan")
        
    allowed = ROLE_ALLOWED_TO_MODIFY.get(current_role, set())
    if target.role not in allowed:
        raise HTTPException(
            status_code=403,
            detail=f"Role '{current_role}' tidak boleh mengubah data pengguna dengan role '{target.role}'"
        )
        
    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(target, field, value)
    # Mis. mahasiswa diubah jadi staff: dia belum punya password, jadi beri default NIM/NIP.
    if target.role != "mahasiswa" and not target.password_hash and target.nim_nip:
        target.password_hash = _hash_pw(target.nim_nip)
        
    db.commit()
    db.refresh(target)
    return target

@router.delete("/{user_id}")
def delete_user(
    user_id: int,
    request: Request,
    force: bool = Query(False, description="Hapus juga seluruh data & relasi terkait"),
    db: Session = Depends(get_db)
):
    current_role = get_current_role(request)
    target = db.query(User).filter(User.id == user_id).first()
    if not target:
        raise HTTPException(404, "Pengguna tidak ditemukan")

    allowed = ROLE_ALLOWED_TO_MODIFY.get(current_role, set())
    if target.role not in allowed:
        raise HTTPException(403, f"Role '{current_role}' tidak boleh menghapus pengguna dengan role '{target.role}'")
    if current_role != "admin":
        raise HTTPException(403, "Hanya admin yang dapat menghapus permanen, gunakan nonaktifkan")

    from app.models.models import AccessLog, Absensi, jadwal_mahasiswa, penanggung_jawab, sesi_finger_user

    has_relasi = (
        db.query(AccessLog).filter(AccessLog.user_id == user_id).first() is not None
        or db.query(Absensi).filter(Absensi.user_id == user_id).first() is not None
        or db.execute(jadwal_mahasiswa.select().where(jadwal_mahasiswa.c.user_id == user_id)).first() is not None
        or db.execute(penanggung_jawab.select().where(penanggung_jawab.c.user_id == user_id)).first() is not None
        or db.execute(sesi_finger_user.select().where(sesi_finger_user.c.user_id == user_id)).first() is not None
    )

    if has_relasi and not force:
        raise HTTPException(
            400,
            "Pengguna ini memiliki riwayat/relasi data (log akses, absensi, jadwal, "
            "penanggung jawab ruangan, atau riwayat sesi input fingerprint). Centang opsi "
            "'hapus beserta riwayat' untuk menghapus paksa, atau nonaktifkan saja untuk "
            "menjaga data historis."
        )

    if force:
        db.query(AccessLog).filter(AccessLog.user_id == user_id).delete()
        db.query(Absensi).filter(Absensi.user_id == user_id).delete()
        db.execute(jadwal_mahasiswa.delete().where(jadwal_mahasiswa.c.user_id == user_id))
        db.execute(penanggung_jawab.delete().where(penanggung_jawab.c.user_id == user_id))
        db.execute(sesi_finger_user.delete().where(sesi_finger_user.c.user_id == user_id))

    # Hapus juga data fingerprint-nya: dari SEMUA device (biar tidak
    # bisa buka pintu lagi) dan dari tabel biometric_template (biar
    # tidak ada data biometrik nyangkut buat user yang sudah dihapus).
    _hapus_akses_fisik_dari_semua_device(target, db, hapus_template_db=True)

    try:
        db.delete(target)
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Gagal menghapus pengguna: {str(e)}")

    return {"pesan": "Pengguna dihapus" + (" beserta seluruh riwayatnya" if force else "")}


@router.post("/cabut-akses-alat-mahasiswa")
def cabut_akses_alat_mahasiswa(
    request: Request,
    konfirmasi: str = Query(
        ...,
        description="Ketik persis 'CABUT AKSES SEMUA MAHASISWA' untuk konfirmasi.",
    ),
    kelas: Optional[str] = Query(
        None,
        description="Isi nama kelas untuk cabut akses 1 kelas saja. Diabaikan kalau user_ids diisi.",
    ),
    user_ids: Optional[List[int]] = Query(
        None,
        description="Isi 1/beberapa ID user (mahasiswa) untuk cabut akses orang-orang tsb saja "
                     "('per orang'). Kalau diisi, parameter kelas diabaikan. Kosongkan kelas & "
                     "user_ids untuk cabut akses SEMUA mahasiswa.",
    ),
    db: Session = Depends(get_db),
):
    """
    Menu "Zona Berbahaya" — cabut akses fisik user berrole 'mahasiswa'
    dari SEMUA alat (hapus PIN mereka di setiap device lewat
    door_service /remove-users), TIDAK menyentuh user
    admin/dosen/teknisi sama sekali. 3 mode lingkup, saling eksklusif
    dengan prioritas: `user_ids` > `kelas` > (kosong = semua mahasiswa):
      1. `user_ids` diisi  → hanya mahasiswa dengan ID tsb ("per orang").
      2. `kelas` diisi     → hanya mahasiswa di kelas itu ("per kelas").
      3. Keduanya kosong   → SEMUA mahasiswa (global).

    PENTING — beda dengan hapus user biasa: endpoint ini SENGAJA
    TIDAK menghapus apapun di database server. Baris di tabel `users`
    dan `biometric_template` tetap utuh, begitu juga riwayat log/
    absensi/jadwal. Yang dihapus HANYA baris `user_device_sync`
    (bookkeeping status sync) dan entri PIN di alat itu sendiri.

    Cocok dipakai misalnya di akhir semester untuk "kosongkan" semua
    alat dari akses mahasiswa (1 orang, 1 kelas yang lulus/pindah, atau
    semua sekaligus), tanpa kehilangan data biometrik/riwayat di
    server — nanti tinggal push lagi user yang relevan lewat "Kirim
    dari Database Server ke Alat" tanpa perlu daftar ulang jari.

    Wajib admin, dan wajib isi query param `konfirmasi` PERSIS supaya
    tidak kepencet tidak sengaja.
    """
    current_role = get_current_role(request)
    if current_role != "admin":
        raise HTTPException(403, "Hanya admin yang boleh mencabut akses alat mahasiswa")

    if konfirmasi != "CABUT AKSES SEMUA MAHASISWA":
        raise HTTPException(
            400,
            "Konfirmasi tidak sesuai. Ketik persis: CABUT AKSES SEMUA MAHASISWA",
        )

    q = db.query(User).filter(User.role == "mahasiswa")
    if user_ids:
        q = q.filter(User.id.in_(user_ids))
    elif kelas:
        q = q.filter(User.kelas == kelas)
    mahasiswa_list = q.all()

    total = len(mahasiswa_list)
    if user_ids:
        lingkup = f"{total} user terpilih"
    elif kelas:
        lingkup = f"kelas {kelas}"
    else:
        lingkup = "semua mahasiswa"
    if total == 0:
        return {"pesan": f"Tidak ada data mahasiswa untuk {lingkup}", "diproses": 0}

    # Cabut akses fisik di SETIAP device tempat mahasiswa itu pernah
    # synced — TIDAK hapus template DB (hapus_template_db=False),
    # jadi baris di biometric_template & users tetap utuh.
    gagal_device = []
    for m in mahasiswa_list:
        try:
            _hapus_akses_fisik_dari_semua_device(m, db, hapus_template_db=False)
        except Exception as e:
            log.warning(f"Gagal cabut akses device untuk {m.nama} (id={m.id}): {e}")
            gagal_device.append(m.nama)

    try:
        db.commit()
    except Exception as e:
        db.rollback()
        raise HTTPException(500, f"Gagal menyimpan perubahan: {str(e)}")

    respon = {
        "pesan": f"Akses alat {total} mahasiswa ({lingkup}) berhasil dicabut. Data user & fingerprint di server TIDAK dihapus.",
        "diproses": total,
    }
    if gagal_device:
        respon["peringatan"] = (
            f"Sebagian device gagal dihubungi untuk: {', '.join(gagal_device)} "
            f"(mungkin offline) — PIN mereka mungkin masih aktif di device tsb sampai online lagi."
        )
    return respon

@router.patch("/{user_id}/toggle-aktif")
def toggle_aktif(user_id: int, request: Request, db: Session = Depends(get_db)):
    """Nonaktifkan/aktifkan — dipakai dosen & teknisi sebagai pengganti delete."""
    current_role = get_current_role(request)
    target = db.query(User).filter(User.id == user_id).first()
    
    if not target:
        raise HTTPException(status_code=404, detail="Pengguna tidak ditemukan")
        
    allowed = ROLE_ALLOWED_TO_MODIFY.get(current_role, set())
    if target.role not in allowed:
        raise HTTPException(status_code=403, detail=f"Tidak diizinkan mengubah status role '{target.role}'")
        
    target.aktif = not target.aktif
    db.commit()

    # Kalau yang terjadi adalah NONAKTIFKAN (bukan aktifkan lagi), user
    # ini harus langsung kehilangan akses fisik di semua device — jangan
    # tunggu loop sync biometrik (bisa sampai 30 menit). Template DB
    # tetap disimpan supaya kalau diaktifkan lagi tidak perlu enroll
    # ulang; roster sync akan otomatis push lagi sesuai jadwal terbaru.
    if not target.aktif:
        _hapus_akses_fisik_dari_semua_device(target, db, hapus_template_db=False)
        db.commit()

    return {"pesan": "Status diperbarui", "aktif": target.aktif}

# --- Password Endpoints ---
@router.patch("/{user_id}/password")
def update_password(
    user_id: int,
    password_lama: str,
    password_baru: str,
    db: Session = Depends(get_db)
):
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    if user.password_hash and not _verify_pw(password_lama, user.password_hash):
        raise HTTPException(status_code=400, detail="Password lama salah")
    user.password_hash = _hash_pw(password_baru)
    db.commit()
    return {"pesan": "Password berhasil diperbarui"}

@router.post("/{user_id}/set-password")
def set_password_admin(
    user_id: int,
    password_baru: str,
    db: Session = Depends(get_db)
):
    """Khusus admin — set password tanpa perlu password lama."""
    user = db.query(User).filter(User.id == user_id).first()
    if not user:
        raise HTTPException(status_code=404, detail="User tidak ditemukan")
    user.password_hash = _hash_pw(password_baru)
    db.commit()
    return {"pesan": f"Password {user.nama} berhasil di-set"}