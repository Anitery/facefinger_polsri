"""
X606-S SOAP Client
Berdasarkan SOAP Development Manual v2.0
Komunikasi via raw XML/HTTP ke device port 80
"""
import http.client
import re
from typing import List, Dict, Optional


class X606SOAPClient:
    """Client SOAP lightweight untuk Solution X606-S."""

    def __init__(self, ip: str, com_key: str = "0", timeout: int = 8):
        self.ip      = ip
        self.com_key = com_key
        self.timeout = timeout

    def _send(self, xml: str) -> str:
        """Kirim XML ke /iWsService port 80 device."""
        try:
            conn = http.client.HTTPConnection(
                self.ip, 80, timeout=self.timeout
            )
            body_bytes = xml.encode("utf-8")
            headers = {
                "Content-Type":   "text/xml",
                "Content-Length": str(len(body_bytes)),
            }
            conn.request("POST", "/iWsService",
                         body=body_bytes, headers=headers)
            resp = conn.getresponse()
            result = resp.read().decode("utf-8", errors="ignore")
            conn.close()
            return result
        except Exception as e:
            raise ConnectionError(
                f"Gagal konek ke {self.ip}:80 — {e}"
            )

    def _ok(self, xml: str) -> bool:
        """Cek apakah response sukses."""
        return any(m in xml.lower() for m in [
            "successfully", "succeed",
            "1</result>", "<result>1"
        ])

    def _rows(self, xml: str, tag: str) -> List[Dict[str, str]]:
        """Parse semua <Row> dari response SOAP."""
        rows = []
        block = re.search(
            f"<{tag}[^>]*>(.*?)</{tag}>",
            xml, re.DOTALL | re.IGNORECASE
        )
        if not block:
            return rows
        for row in re.findall(
            r"<Row[^>]*>(.*?)</Row>",
            block.group(1), re.DOTALL | re.IGNORECASE
        ):
            d = {}
            for tag_name, val in re.findall(
                r"<([^/\s>]+)[^>]*>([^<]*)</\1>", row, re.IGNORECASE
            ):
                d[tag_name] = val.strip()
            rows.append(d)
        return rows

    def _val(self, xml: str, tag: str) -> Optional[str]:
        """Parse satu nilai dari tag."""
        m = re.search(
            f"<{tag}[^>]*>([^<]*)</{tag}>", xml, re.IGNORECASE
        )
        return m.group(1).strip() if m else None

    # ── User management ──────────────────────────────────

    def get_all_users(self) -> List[Dict[str, str]]:
        """Ambil semua user dari device."""
        xml = (
            f'<GetAllUserInfo>'
            f'<ArgComKey xsi:type="xsd:integer">{self.com_key}</ArgComKey>'
            f'</GetAllUserInfo>'
        )
        return self._rows(self._send(xml), "GetAllUserInfoResponse")

    def set_user(self, pin: str, name: str,
                privilege: str = "0",
                tz1: int = 1,
                tz2: int = 1, tz3: int = 1) -> bool:
        """
        tz1/tz2/tz3 = ID Zona Waktu (1-50) yang sudah dikonfigurasi
        via software GUI (Pengaturan > Akses Kontrol > Zona Waktu).
        Bukan string rentang jam — device mengabaikan/fallback jika
        diberi format selain ID integer.
        """
        xml = (
            f'<SetUserInfo>'
            f'<ArgComKey xsi:type="xsd:integer">{self.com_key}</ArgComKey>'
            f'<Arg>'
            f'<PIN>{pin}</PIN>'
            f'<Name>{name}</Name>'
            f'<Privilege>{privilege}</Privilege>'
            f'<TZ1>{tz1}</TZ1>'
            f'<TZ2>{tz2}</TZ2>'
            f'<TZ3>{tz3}</TZ3>'
            f'</Arg>'
            f'</SetUserInfo>'
        )
        return self._ok(self._send(xml))

    def delete_user(self, pin: str) -> bool:
        """Hapus user dari device berdasarkan PIN."""
        xml = (
            f'<DeleteUser>'
            f'<ArgComKey xsi:type="xsd:integer">{self.com_key}</ArgComKey>'
            f'<Arg>'
            f'<PIN xsi:type="xsd:integer">{pin}</PIN>'
            f'</Arg>'
            f'</DeleteUser>'
        )
        return self._ok(self._send(xml))

    def clear_all_users(self) -> bool:
        """Hapus SEMUA user dari device (Value=3)."""
        xml = (
            f'<ClearData>'
            f'<ArgComKey xsi:type="xsd:integer">{self.com_key}</ArgComKey>'
            f'<Arg><Value xsi:type="xsd:integer">3</Value></Arg>'
            f'</ClearData>'
        )
        return self._ok(self._send(xml))

    # ── Attendance logs ──────────────────────────────────

    def get_logs(self, pin: str = "All") -> List[Dict[str, str]]:
        """
        Ambil log absensi. pin="All" untuk semua user.
        Return: [{PIN, DateTime, Verified, Status, WorkCode}, ...]
        
        Verified: 1/2/3=fingerprint, 4/5/6=face, 0/15=password
        Status  : 0=masuk, 1=keluar
        """
        xml = (
            f'<GetAttLog>'
            f'<ArgComKey xsi:type="xsd:integer">{self.com_key}</ArgComKey>'
            f'<Arg>'
            f'<PIN xsi:type="xsd:integer">{pin}</PIN>'
            f'</Arg>'
            f'</GetAttLog>'
        )
        return self._rows(self._send(xml), "GetAttLogResponse")

    def clear_logs(self) -> bool:
        """Hapus semua log dari device (Value=1)."""
        xml = (
            f'<ClearData>'
            f'<ArgComKey xsi:type="xsd:integer">{self.com_key}</ArgComKey>'
            f'<Arg><Value xsi:type="xsd:integer">1</Value></Arg>'
            f'</ClearData>'
        )
        return self._ok(self._send(xml))

    # ── System ───────────────────────────────────────────

    def refresh_db(self) -> bool:
        """
        WAJIB dipanggil setelah set_user/delete_user
        agar perubahan aktif di device.
        """
        xml = (
            f'<RefreshDB>'
            f'<ArgComKey xsi:type="xsd:integer">{self.com_key}</ArgComKey>'
            f'</RefreshDB>'
        )
        return self._ok(self._send(xml))

    def get_time(self) -> Dict[str, str]:
        """Ambil waktu dari device — juga dipakai untuk test koneksi."""
        xml = (
            f'<GetDate>'
            f'<ArgComKey xsi:type="xsd:integer">{self.com_key}</ArgComKey>'
            f'</GetDate>'
        )
        r = self._send(xml)
        return {
            "date": self._val(r, "Date") or "",
            "time": self._val(r, "Time") or "",
        }

    def set_time(self, date_str: str, time_str: str) -> bool:
        """Sinkronisasi waktu device dengan waktu server."""
        xml = (
            f'<SetDate>'
            f'<ArgComKey xsi:type="xsd:integer">{self.com_key}</ArgComKey>'
            f'<Arg>'
            f'<Date xsi:type="xsd:string">{date_str}</Date>'
            f'<Time xsi:type="xsd:string">{time_str}</Time>'
            f'</Arg>'
            f'</SetDate>'
        )
        return self._ok(self._send(xml))

    def restart(self) -> bool:
        """Restart device."""
        xml = (
            f'<Restart>'
            f'<ArgComKey xsi:type="xsd:integer">{self.com_key}</ArgComKey>'
            f'</Restart>'
        )
        return self._ok(self._send(xml))

    def ping(self) -> Dict[str, str]:
        """Test koneksi — return waktu device jika berhasil."""
        return self.get_time()