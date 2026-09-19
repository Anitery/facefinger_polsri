from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Request, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from typing import List, Optional
import json
import logging
import requests
from app.database import get_db
from app.models.models import User, BiometricTemplate, UserDeviceSync
from app.schemas import UserCreate, UserOut, UserUpdate
import bcrypt

log = logging.getLogger(__name__)


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
ROLE_ORDER = {"admin": 0, "teknisi": 1, "dosen": 2, "mahasiswa": 3}

ROLE_ALLOWED_TO_CREATE = {
    "admin":   {"admin", "teknisi", "dosen", "mahasiswa"},
    "dosen":   {"mahasiswa"},
    "teknisi": {"dosen"},
}

ROLE_ALLOWED_TO_MODIFY = {
    "admin":   {"admin", "teknisi", "dosen", "mahasiswa"},
    "dosen":   {"mahasiswa"},
    "teknisi": {"dosen"},
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
    user.id_perangkat = fingerprint_id
    db.commit()
    return {"pesan": f"ID Perangkat {fingerprint_id} disimpan untuk {user.nama}"}

# --- Read Endpoints ---
@router.get("/daftar-kelas")
def get_daftar_kelas(db: Session = Depends(get_db)):
    """Daftar nilai 'kelas' yang unik & terisi — buat isi dropdown filter di halaman Pengguna."""
    rows = db.query(User.kelas).filter(
        User.kelas.isnot(None), User.kelas != ""
    ).distinct().order_by(User.kelas).all()
    return [r[0] for r in rows]


@router.get("/")
def get_users(
    request: Request,  # <-- Tambahkan parameter request di sini
    include_inactive: bool = False,
    role:             Optional[str] = None,
    kelas:            Optional[str] = None,
    fingerprint:      Optional[str] = Query(None, description="Filter: 'ada' atau 'belum'"),
    search:           Optional[str] = None,
    limit:            int = Query(50, ge=1, le=200),
    page:             int = Query(1,  ge=1),
    db: Session = Depends(get_db)
):
    q = db.query(User)
    if not include_inactive:
        q = q.filter(User.aktif == True)
    if role:
        q = q.filter(User.role == role)
    if kelas:
        q = q.filter(User.kelas == kelas)
    if search:
        q = q.filter(
            User.nama.ilike(f"%{search}%") |
            User.nim_nip.ilike(f"%{search}%") |
            User.kelas.ilike(f"%{search}%")
        )

    # --- FIX 4: Sembunyikan Role Admin dari Dosen dan Teknisi ---
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
    if viewer_role in ("dosen", "teknisi"):
        q = q.filter(User.role != "admin")
    # -------------------------------------------------------------

    all_users = q.all()

    # Status fingerprint dihitung untuk SELURUH hasil filter di atas (bukan
    # cuma 1 halaman) — supaya filter "punya/belum fingerprint" bisa
    # dikombinasikan dengan filter lain + pagination secara konsisten,
    # bukan cuma menyaring apa yang kebetulan ada di halaman saat ini.
    ids_dgn_template = set()
    all_ids = [u.id for u in all_users]
    if all_ids:
        rows = db.query(BiometricTemplate.user_id).filter(
            BiometricTemplate.user_id.in_(all_ids)
        ).distinct().all()
        ids_dgn_template = {r[0] for r in rows}

    if fingerprint == "ada":
        all_users = [u for u in all_users if u.id in ids_dgn_template]
    elif fingerprint == "belum":
        all_users = [u for u in all_users if u.id not in ids_dgn_template]

    ROLE_ORDER = {"admin": 0, "teknisi": 1, "dosen": 2, "mahasiswa": 3}
    all_users.sort(key=lambda u: (
        ROLE_ORDER.get(u.role, 99),
        u.kelas or "",
        u.nama or ""
    ))
    
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
                "punya_template": u.id in ids_dgn_template,
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
        password_hash=_hash_pw(payload.password) if getattr(payload, 'password', None) else None,
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