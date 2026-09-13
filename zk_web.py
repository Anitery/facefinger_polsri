"""
zk_web.py — Client Open Door untuk ZK Web Server (X606-S)
=========================================================
Port dari prototype hasil reverse-engineering (curl.exe berhasil,
requests.Session() Python GAGAL walau alur & payload identik — dites
langsung di hardware asli). Modul ini SENGAJA memakai `curl` sebagai
subprocess, bukan `requests`, karena itu satu-satunya yang terbukti
jalan di device ini.

Alur (semua wajib, urutan persis — device sensitif terhadap urutan):
    1. GET  /                  -> device kirim Set-Cookie: SessionID=...
    2. GET  /csl/login         -> halaman login (pakai cookie di atas)
    3. POST /csl/check         -> username=<u>&userpwd=<p>
    4. GET  /csl/header        -> (tidak wajib secara fungsional, tapi
    5. GET  /csl/menu             direplikasi supaya identik dgn browser)
    6. GET  /form/Device?act=9 -> trigger Open Door

Jalankan di lingkungan yang PUNYA akses jaringan langsung ke device
(STB/laptop bridge) — bukan di server utama, kalau server dan device
tidak satu jaringan.

Butuh `curl` terpasang. Sudah ada bawaan di hampir semua distro Linux
(termasuk yang dipakai STB) dan Windows 10/11 modern.
"""

import subprocess
import tempfile
import os
import shutil

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 SmartDoorLockBridge/1.0"
)

_COMMON_HEADERS = [
    "-H", "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "-H", "Accept-Encoding: gzip, deflate",
    "-H", "Accept-Language: id-ID,id;q=0.9",
    "-H", "Cache-Control: no-cache",
    "-H", "Pragma: no-cache",
    "-H", "User-Agent: " + USER_AGENT,
]


class ZKWebError(Exception):
    """Dilempar saat login/open-door gagal. Membawa cuplikan respons
    device asli supaya gampang didiagnosa."""
    def __init__(self, message: str, response_snippet: str = ""):
        self.response_snippet = response_snippet
        super().__init__(f"{message}\n--- Respons device ---\n{response_snippet[:500]}")


def _curl_bin() -> str:
    """Cari binary curl — 'curl' di Linux/Mac, fallback 'curl.exe' di Windows."""
    for candidate in ("curl", "curl.exe"):
        if shutil.which(candidate):
            return candidate
    raise ZKWebError("Binary 'curl' tidak ditemukan di sistem ini. Install curl dulu.")


def _run_curl(args: list, timeout: int = 10) -> str:
    curl = _curl_bin()
    result = subprocess.run(
        [curl] + args,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    return result.stdout


def open_door(device_ip: str, username: str, password: str, timeout: int = 10) -> bool:
    """
    Login ke web panel X606-S lalu trigger Open Door (act=9).
    Return True kalau device konfirmasi 'Door has been Opened'.
    Melempar ZKWebError (bukan return False diam-diam) kalau gagal,
    supaya penyebabnya kelihatan jelas.
    """
    device_url = f"http://{device_ip}"

    with tempfile.TemporaryDirectory() as tmpdir:
        cookie_file = os.path.join(tmpdir, "doorlock_cookies.txt")

        # STEP 1 — GET / (di sinilah device kirim Set-Cookie SessionID)
        _run_curl([
            device_url + "/",
            *_COMMON_HEADERS,
            "-c", cookie_file,
        ], timeout=timeout)

        # STEP 2 — GET /csl/login
        _run_curl([
            device_url + "/csl/login",
            *_COMMON_HEADERS,
            "-H", "Referer: " + device_url + "/",
            "-b", cookie_file,
            "-c", cookie_file,
        ], timeout=timeout)

        # STEP 3 — POST /csl/check (login sesungguhnya)
        payload = f"username={username}&userpwd={password}"
        check_resp = _run_curl([
            device_url + "/csl/check",
            *_COMMON_HEADERS,
            "-H", "Content-Type: application/x-www-form-urlencoded",
            "-H", "Origin: " + device_url,
            "-H", "Referer: " + device_url + "/csl/login",
            "-b", cookie_file,
            "-c", cookie_file,
            "--data-raw", payload,
        ], timeout=timeout)

        if "userpwd" in check_resp.lower() and "frameset" not in check_resp.lower():
            raise ZKWebError(
                "Login ditolak device — kemungkinan username/password admin panel salah.",
                check_resp,
            )

        # STEP 4 & 5 — replikasi alur browser (tidak wajib secara fungsional,
        # tapi disertakan supaya sama persis dengan yang terbukti berhasil)
        _run_curl([
            device_url + "/csl/header",
            *_COMMON_HEADERS,
            "-H", "Referer: " + device_url + "/csl/check",
            "-b", cookie_file,
        ], timeout=timeout)

        _run_curl([
            device_url + "/csl/menu",
            *_COMMON_HEADERS,
            "-H", "Referer: " + device_url + "/csl/check",
            "-b", cookie_file,
        ], timeout=timeout)

        # STEP 6 — GET /form/Device?act=9 (INI yang benar-benar buka pintu)
        door_resp = _run_curl([
            device_url + "/form/Device?act=9",
            *_COMMON_HEADERS,
            "-H", "Referer: " + device_url + "/csl/menu",
            "-b", cookie_file,
        ], timeout=timeout)

        if "door has been opened" in door_resp.lower():
            return True

        if "location.href='/'" in door_resp or 'location.href="/"' in door_resp:
            raise ZKWebError(
                "Device menolak session sebagai belum login (redirect ke halaman utama).",
                door_resp,
            )

        raise ZKWebError(
            "Device merespons tapi TIDAK mengonfirmasi pintu terbuka.",
            door_resp,
        )