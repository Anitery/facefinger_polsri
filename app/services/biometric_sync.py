"""
app/services/biometric_sync.py
=========================================================
Duplikasi data user (fingerprint) antar device X606-S, dipicu oleh
jadwal — BUKAN oleh Group/TimeZone di device (terbukti tidak reliable
lewat pengujian manual sebelumnya).

Mekanisme:
    - User hanya bisa akses di ruangan yang device-nya PUNYA data user
      itu di memori internal (PIN + template fingerprint terdaftar).
    - Saat user MULAI punya jadwal di ruangan X -> push data ke device
      ruangan X.
    - Saat user TIDAK LAGI punya jadwal di ruangan X -> hapus data dari
      device ruangan X.
    - Device menolak otomatis siapapun yang PIN-nya tidak terdaftar —
      tidak perlu Group/TZ sama sekali.

Semua lewat SOAP (X606SOAPClient) — protokol resmi terdokumentasi,
bukan reverse-engineering web panel.
"""
from typing import Optional
from sqlalchemy.orm import Session

from app.services.x606_soap import X606SOAPClient
from app.models.models import User, BiometricTemplate, UserDeviceSync, Ruangan


def download_user_biometrics(db: Session, device_ip: str, com_key: str, user: User) -> int:
    """
    Ambil semua template fingerprint milik 1 user dari device tempat
    dia awal enroll, simpan/update ke tabel BiometricTemplate.
    Return: jumlah template yang berhasil diambil.
    """
    if not user.id_perangkat:
        return 0

    client = X606SOAPClient(ip=device_ip, com_key=com_key)
    templates = client.get_all_templates(str(user.id_perangkat))

    for t in templates:
        existing = db.query(BiometricTemplate).filter(
            BiometricTemplate.user_id == user.id,
            BiometricTemplate.finger_id == int(t["FingerID"]),
        ).first()
        if existing:
            existing.size = t.get("Size")
            existing.template = t.get("Template")
            existing.valid = t.get("Valid", "1")
        else:
            db.add(BiometricTemplate(
                user_id=user.id,
                finger_id=int(t["FingerID"]),
                size=t.get("Size"),
                template=t.get("Template"),
                valid=t.get("Valid", "1"),
            ))
    db.commit()
    return len(templates)


def push_user_to_device(
    db: Session, device_ip: str, com_key: str, user: User,
    group: int = 1, tz1: int = 1, tz2: int = 1, tz3: int = 1,
) -> bool:
    """
    Push data user (info + semua template fingerprint tersimpan) ke
    device tujuan. User harus sudah pernah di-download_user_biometrics()
    sebelumnya (template diambil dari DB kita, bukan device asal
    langsung, supaya device asal tidak perlu online terus).
    """
    if not user.id_perangkat:
        return False

    templates = db.query(BiometricTemplate).filter(
        BiometricTemplate.user_id == user.id,
        BiometricTemplate.valid != "0",
    ).all()
    if not templates:
        return False  # Belum pernah di-download, tidak ada yang bisa di-push

    client = X606SOAPClient(ip=device_ip, com_key=com_key)
    pin = str(user.id_perangkat)

    ok = client.set_user(pin=pin, name=user.nama, group=group, tz1=tz1, tz2=tz2, tz3=tz3)
    if not ok:
        return False

    semua_ok = True
    for t in templates:
        hasil = client.set_user_template(
            pin=pin, finger_id=t.finger_id, size=t.size or "0",
            template=t.template, valid=t.valid or "1",
        )
        semua_ok = semua_ok and hasil

    client.refresh_db()
    return semua_ok


def remove_user_from_device(device_ip: str, com_key: str, id_perangkat: int) -> bool:
    """Hapus data user dari 1 device (dipanggil saat jadwal berakhir)."""
    client = X606SOAPClient(ip=device_ip, com_key=com_key)
    ok = client.delete_user(str(id_perangkat))
    if ok:
        client.refresh_db()
    return ok


def provision_user_info(
    db: Session, device_ip: str, com_key: str, user: User,
    group: int = 1, tz1: int = 1, tz2: int = 1, tz3: int = 1,
) -> bool:
    """
    Push HANYA info user (PIN + nama) ke device — TANPA template,
    karena usernya belum pernah enroll fingerprint di manapun.
    Tujuannya: device sudah "kenal" PIN ini, siap menerima pendaftaran
    fingerprint fisik saat orangnya datang.
    """
    if not user.id_perangkat:
        return False
    client = X606SOAPClient(ip=device_ip, com_key=com_key)
    return client.set_user(
        pin=str(user.id_perangkat), name=user.nama,
        group=group, tz1=tz1, tz2=tz2, tz3=tz3,
    )


def user_punya_template(db: Session, user_id: int) -> bool:
    return db.query(BiometricTemplate).filter(BiometricTemplate.user_id == user_id).first() is not None


def sync_user_ke_ruangan(
    db: Session, user: User, ruangan: Ruangan, device_ip: str, com_key: str,
    punya_jadwal: bool,
) -> str:
    """
    Sinkronkan 1 user ke 1 ruangan sesuai status jadwal DAN status
    template biometriknya. Status yang mungkin:
      - 'provisioned' : PIN+nama sudah di-push, TAPI belum ada template
                        (user belum pernah enroll di manapun — menunggu
                        dia datang & daftar jari secara fisik)
      - 'synced'      : PIN+nama+template lengkap ter-push (user sudah
                        pernah enroll di device lain, datanya diduplikasi ke sini)
      - 'removed'     : jadwal sudah tidak ada, data dihapus dari device
      - 'gagal'       : percobaan push/hapus terakhir gagal

    Return status yang terjadi: 'provisioned' / 'upgraded' / 'pushed' /
    'removed' / 'skip' / 'gagal'
    """
    sync_row = db.query(UserDeviceSync).filter(
        UserDeviceSync.user_id == user.id,
        UserDeviceSync.ruangan_id == ruangan.id,
    ).first()

    status_sekarang = sync_row.status if sync_row else None
    ada_template = user_punya_template(db, user.id)

    if punya_jadwal:
        # Kasus 1: belum pernah disentuh sama sekali di ruangan ini
        if status_sekarang is None:
            if ada_template:
                berhasil = push_user_to_device(db, device_ip, com_key, user)
                status = "synced" if berhasil else "gagal"
                db.add(UserDeviceSync(user_id=user.id, ruangan_id=ruangan.id, status=status))
                db.commit()
                return "pushed" if berhasil else "gagal"
            else:
                berhasil = provision_user_info(db, device_ip, com_key, user)
                status = "provisioned" if berhasil else "gagal"
                db.add(UserDeviceSync(user_id=user.id, ruangan_id=ruangan.id, status=status))
                db.commit()
                return "provisioned" if berhasil else "gagal"

        # Kasus 2: sebelumnya cuma di-provision (info doang), SEKARANG
        # ternyata sudah punya template (baru saja enroll di device lain)
        # -> upgrade jadi push lengkap dengan template
        if status_sekarang == "provisioned" and ada_template:
            berhasil = push_user_to_device(db, device_ip, com_key, user)
            sync_row.status = "synced" if berhasil else "gagal"
            db.commit()
            return "upgraded" if berhasil else "gagal"

        # Kasus 3: sudah synced atau masih provisioned tanpa perubahan
        # template -> tidak perlu aksi apapun
        return "skip"

    # Tidak punya jadwal lagi -> hapus kalau sebelumnya ada datanya
    if status_sekarang in ("synced", "provisioned"):
        berhasil = remove_user_from_device(device_ip, com_key, user.id_perangkat)
        sync_row.status = "removed" if berhasil else "gagal"
        db.commit()
        return "removed" if berhasil else "gagal"

    return "skip"