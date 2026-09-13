"""
X606-S Web Panel Client
=========================================================
Ini BUKAN protokol SOAP (/iWsService) yang dipakai x606_soap.py.
Ini adalah API internal panel HTML bawaan device, hasil
reverse-engineering dari Network tab browser:

    1. Cookie SessionID di-generate di SISI KLIEN (bukan dari
       Set-Cookie server!) — nilainya adalah Unix timestamp (detik)
       saat halaman dimuat, kemungkinan besar dibuat oleh gen.js.
       Device tidak pernah mengirim Set-Cookie sama sekali.
    2. GET  /csl/login            -> muat halaman login (cookie di atas
                                      sudah harus terpasang sebelum ini)
    3. POST /csl/check            -> body: username=<u>&userpwd=<p>
                                      (x-www-form-urlencoded), pakai
                                      cookie SessionID yang sama
    4. GET  /form/Device?act=9    -> trigger "Open Door", pakai
                                      cookie yang sama

`requests.Session()` menangani cookie jar antar-request, tapi
SessionID-nya harus KITA set manual di awal (bukan menunggu server).

CATATAN: protokol ini tidak resmi didokumentasikan (beda dari SOAP
manual v2.0), hasil observasi lalu lintas jaringan asli. Kalau
firmware device di-update, kemungkinan act-code atau endpoint bisa
berubah.
"""
import time
import requests
from typing import Optional


class X606WebPanelError(Exception):
    """Dilempar saat login/open-door gagal, membawa cuplikan respons
    device asli supaya gampang didiagnosa (bukan cuma 'gagal')."""
    def __init__(self, message: str, response_snippet: str = ""):
        self.response_snippet = response_snippet
        super().__init__(f"{message}\n--- Respons device ---\n{response_snippet[:500]}")


class X606WebPanelClient:
    def __init__(self, ip: str, username: str, password: str, timeout: int = 8):
        self.ip       = ip
        self.username = username
        self.password = password
        self.timeout  = timeout
        self.base     = f"http://{ip}"

    def _login(self) -> requests.Session:
        s = requests.Session()

        # SessionID di-generate SENDIRI di sini (Unix timestamp detik),
        # meniru apa yang dilakukan gen.js di browser — device TIDAK
        # mengirim Set-Cookie, jadi kalau kita tidak set manual, semua
        # request berikutnya tidak akan punya session sama sekali.
        session_id = str(int(time.time()))
        s.cookies.set("SessionID", session_id, domain=self.ip)

        # Langkah 1: buka halaman login (device mendaftarkan SessionID
        # ini sebagai "belum login" di sisi server)
        s.get(f"{self.base}/csl/login", timeout=self.timeout)

        # Langkah 2: submit kredensial, dengan cookie SessionID yang sama
        r = s.post(
            f"{self.base}/csl/check",
            data={"username": self.username, "userpwd": self.password},
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Origin":  self.base,
                "Referer": f"{self.base}/csl/login",
            },
            timeout=self.timeout,
        )

        # Deteksi dini: kalau balasan /csl/check mengandung form login lagi,
        # kemungkinan besar username/password salah.
        if "userpwd" in r.text.lower() or "csl/login" in r.text.lower():
            raise X606WebPanelError(
                "Login ditolak device — kemungkinan username/password admin panel salah.",
                r.text,
            )
        return s

    def open_door(self) -> bool:
        """Login lalu trigger buka pintu (act=9). Return True kalau
        response mengonfirmasi 'Door has been Opened'. Melempar
        X606WebPanelError (bukan return False diam-diam) kalau gagal,
        supaya penyebabnya kelihatan."""
        s = self._login()
        r = s.get(f"{self.base}/form/Device?act=9", timeout=self.timeout)

        if "door has been opened" in r.text.lower():
            return True

        # Redirect ke '/' via JS artinya device menolak session ini
        # sebagai belum terautentikasi.
        if "location.href='/'" in r.text or 'location.href="/"' in r.text:
            raise X606WebPanelError(
                "Device menolak session sebagai belum login (redirect ke halaman utama). "
                "Kemungkinan cookie SessionID tidak diterima device — cek apakah device masih "
                "versi firmware yang sama saat capture dilakukan.",
                r.text,
            )

        raise X606WebPanelError(
            "Device merespons tapi TIDAK mengonfirmasi pintu terbuka.",
            r.text,
        )

    def test_login(self) -> bool:
        """Cek kredensial valid tanpa membuka pintu — dipakai buat
        validasi konfigurasi di halaman Pengaturan Sistem."""
        try:
            self._login()
            return True
        except X606WebPanelError:
            return False