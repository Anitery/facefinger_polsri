"""
zk_admin.py — Client TimeZone / Group / User Access untuk X606-S Web Panel
=========================================================
Lanjutan dari zk_web.py (open door). Modul ini menangani sisi "jadwal"
lewat protokol web panel yang sama (BUKAN SOAP), hasil reverse-
engineering yang SUDAH DIVERIFIKASI di hardware asli (lampu hijau saat
scan setelah konfigurasi TZ+Group+User berhasil).

Field yang ditemukan:

    TimeZone (POST /form/Actz?act=1):
        tzid        — index TZ, 1-50
        tz0s/tz0c   — Minggu, jam mulai/tutup (format HH:MM)
        tz1s/tz1c   — Senin
        tz2s/tz2c   — Selasa
        tz3s/tz3c   — Rabu
        tz4s/tz4c   — Kamis
        tz5s/tz5c   — Jumat
        tz6s/tz6c   — Sabtu

    Group (POST /form/Actz?act=3):
        gid         — index Group, 1-99
        grp1/2/3    — index TZ yang dipakai group ini (0 = None)

    Modify User (POST /csl/user?action=save&id=modify):
        upin        — uid INTERNAL device (BUKAN PIN!), didapat dari /csl/user
        upin2       — PIN asli (ID Number) — readonly, tapi tetap wajib dikirim
        uname       — nama tampilan (maks 8 karakter di device ini)
        uprivilege  — 0 = User, 14 = Super Administrator
        ugroup      — index Group yang di-assign
        usegrouptz  — 0 = pakai TZ dari Group (YA), 1 = pakai TZ manual per-user (TIDAK)
        upwd        — password device (opsional)
        ucard       — nomor kartu (opsional, '0' kalau tidak ada)

PENTING: TZ index default 1-49 SELALU TERBUKA PENUH (00:00-23:59 tiap
hari) — jadi Group tanpa TZ ('None') itu yang membuat akses SELALU
DITOLAK (fail-safe closed). Ini konsisten dengan asumsi GROUP_TERKONTUNG
di x606_bridge.py.
"""

import re
import tempfile
import os
from typing import Optional

from zk_web import _run_curl, _COMMON_HEADERS, ZKWebError


HARI_KE_SLOT = {
    "minggu": 0, "senin": 1, "selasa": 2, "rabu": 3,
    "kamis": 4, "jumat": 5, "sabtu": 6,
}


def _login_get_cookiejar(device_ip: str, username: str, password: str, cookie_file: str, timeout: int = 10):
    """Login sekali, hasil cookie disimpan di cookie_file — dipakai ulang
    untuk beberapa aksi berturut-turut tanpa perlu login ulang tiap kali."""
    device_url = f"http://{device_ip}"

    _run_curl([device_url + "/", *_COMMON_HEADERS, "-c", cookie_file], timeout=timeout)
    _run_curl([
        device_url + "/csl/login", *_COMMON_HEADERS,
        "-H", "Referer: " + device_url + "/",
        "-b", cookie_file, "-c", cookie_file,
    ], timeout=timeout)

    payload = f"username={username}&userpwd={password}"
    check_resp = _run_curl([
        device_url + "/csl/check", *_COMMON_HEADERS,
        "-H", "Content-Type: application/x-www-form-urlencoded",
        "-H", "Origin: " + device_url,
        "-H", "Referer: " + device_url + "/csl/login",
        "-b", cookie_file, "-c", cookie_file,
        "--data-raw", payload,
    ], timeout=timeout)

    if "userpwd" in check_resp.lower() and "frameset" not in check_resp.lower():
        raise ZKWebError("Login ditolak device — username/password admin panel salah.", check_resp)


def set_timezone(device_ip: str, cookie_file: str, tzid: int, jadwal_mingguan: dict, timeout: int = 10) -> bool:
    """
    Definisikan isi 1 TZ index (hari & jam). `jadwal_mingguan` contoh:
        {"senin": ("07:00", "21:00"), "selasa": ("07:00", "21:00"), ...}
    Hari yang tidak disebutkan otomatis dianggap TUTUP (start > close).
    """
    device_url = f"http://{device_ip}"
    fields = {}
    for hari, slot in HARI_KE_SLOT.items():
        if hari in jadwal_mingguan:
            mulai, selesai = jadwal_mingguan[hari]
        else:
            mulai, selesai = "23:59", "00:00"  # tutup sepanjang hari
        fields[f"tz{slot}s"] = mulai
        fields[f"tz{slot}c"] = selesai

    payload = f"tzid={tzid}&" + "&".join(f"{k}={v.replace(':', '%3A')}" for k, v in fields.items())

    resp = _run_curl([
        device_url + "/form/Actz?act=1", *_COMMON_HEADERS,
        "-H", "Content-Type: application/x-www-form-urlencoded",
        "-H", "Origin: " + device_url,
        "-H", "Referer: " + device_url + "/form/Actz",
        "-b", cookie_file, "-c", cookie_file,
        "--data-raw", payload,
    ], timeout=timeout)

    if "location.href='/'" in resp or 'location.href="/"' in resp:
        raise ZKWebError(f"Set TimeZone {tzid} gagal — session ditolak.", resp)
    return True


def set_group(device_ip: str, cookie_file: str, gid: int, tz1: int = 0, tz2: int = 0, tz3: int = 0, timeout: int = 10) -> bool:
    """Assign hingga 3 TZ index ke 1 Group. tz=0 berarti 'None'."""
    device_url = f"http://{device_ip}"
    payload = f"gid={gid}&grp1={tz1}&grp2={tz2}&grp3={tz3}"

    resp = _run_curl([
        device_url + "/form/Actz?act=3", *_COMMON_HEADERS,
        "-H", "Content-Type: application/x-www-form-urlencoded",
        "-H", "Origin: " + device_url,
        "-H", "Referer: " + device_url + "/form/Actz?act=2",
        "-b", cookie_file, "-c", cookie_file,
        "--data-raw", payload,
    ], timeout=timeout)

    if "location.href='/'" in resp or 'location.href="/"' in resp:
        raise ZKWebError(f"Set Group {gid} gagal — session ditolak.", resp)
    return True


def list_users(device_ip: str, cookie_file: str, timeout: int = 10) -> list:
    """
    Ambil daftar user dari device (PIN + uid internal), dengan parsing
    HTML (device ini tidak expose ini lewat SOAP). Rapuh terhadap
    perubahan firmware, tapi ini satu-satunya cara yang ditemukan.

    Returns: [{"uid": int, "pin": str, "nama": str, "group": str}, ...]
    """
    device_url = f"http://{device_ip}"
    html = _run_curl([
        device_url + "/csl/user", *_COMMON_HEADERS,
        "-H", "Referer: " + device_url + "/csl/menu",
        "-b", cookie_file,
    ], timeout=timeout)

    if "location.href='/'" in html or 'location.href="/"' in html:
        raise ZKWebError("Gagal ambil daftar user — session ditolak.", html)

    hasil = []
    # Setiap baris user: <td>...</td><td>PIN</td><td>Nama</td><td>Card</td><td>Group</td>
    # <td>Privilege</td><td><a href='/csl/user?action=modify&uid=N'>...
    row_pattern = re.compile(
        r"<td width=15%>(\d+)</td>\s*<td width=15%>([^<]*)</td>.*?"
        r"uid=(\d+)",
        re.IGNORECASE | re.DOTALL,
    )
    for m in row_pattern.finditer(html):
        pin, nama, uid = m.group(1), m.group(2).strip(), m.group(3)
        hasil.append({"uid": int(uid), "pin": pin, "nama": nama})
    return hasil


def set_user_group(
    device_ip: str, cookie_file: str,
    uid: int, pin: str, nama: str,
    group: int, privilege: int = 0, password: str = "", card: str = "0",
    timeout: int = 10,
) -> bool:
    """
    Assign Group ke satu user (usegrouptz=0 — pakai TZ dari Group,
    bukan TZ manual per-user).
    """
    device_url = f"http://{device_ip}"
    nama_singkat = (nama or "")[:8]  # device ini batas nama maks 8 karakter

    payload = (
        f"upin={uid}&upin2={pin}&uname={nama_singkat}"
        f"&uprivilege={privilege}&ugroup={group}&usegrouptz=0"
        f"&upwd={password}&ucard={card}"
    )

    resp = _run_curl([
        device_url + "/csl/user?action=save&id=modify", *_COMMON_HEADERS,
        "-H", "Content-Type: application/x-www-form-urlencoded",
        "-H", "Origin: " + device_url,
        "-H", f"Referer: {device_url}/csl/user?action=modify&uid={uid}",
        "-b", cookie_file, "-c", cookie_file,
        "--data-raw", payload,
    ], timeout=timeout)

    if "location.href='/'" in resp or 'location.href="/"' in resp:
        raise ZKWebError(f"Set Group user PIN {pin} gagal — session ditolak.", resp)
    return True


def sync_class_schedule(
    device_ip: str, username: str, password: str,
    tzid: int, gid: int, jadwal_mingguan: dict, pin_list: list,
    timeout: int = 10,
) -> dict:
    """
    Fungsi orkestrasi tingkat tinggi — 1 panggilan buat:
      1. Definisikan 1 TZ (jadwal_mingguan)
      2. Definisikan 1 Group, semua 3 slot TZ-nya = tzid di atas
      3. Assign Group itu ke semua user di pin_list

    Login CUMA SEKALI untuk semua langkah (efisien, tidak login berkali-kali).
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        cookie_file = os.path.join(tmpdir, "sync_cookies.txt")
        _login_get_cookiejar(device_ip, username, password, cookie_file, timeout)

        set_timezone(device_ip, cookie_file, tzid, jadwal_mingguan, timeout)
        set_group(device_ip, cookie_file, gid, tzid, tzid, tzid, timeout)

        semua_user = list_users(device_ip, cookie_file, timeout)
        pin_ke_uid = {u["pin"]: (u["uid"], u["nama"]) for u in semua_user}

        berhasil, gagal = [], []
        for pin in pin_list:
            if pin not in pin_ke_uid:
                gagal.append({"pin": pin, "alasan": "PIN tidak ditemukan di device"})
                continue
            uid, nama = pin_ke_uid[pin]
            try:
                set_user_group(device_ip, cookie_file, uid, pin, nama, gid, timeout=timeout)
                berhasil.append(pin)
            except ZKWebError as e:
                gagal.append({"pin": pin, "alasan": str(e).splitlines()[0]})

        return {"tzid": tzid, "gid": gid, "berhasil": berhasil, "gagal": gagal}