"""
X606-S SOAP Service - V3 (Compatible dengan format XML asli ZK Web Server)
Lokasi: app/services/x606_service.py

Insight dari debug:
- PIN device (internal) != PIN2 (registration ID)
- GetUserInfo query pakai PIN device, bukan PIN2
- SetUserInfo dengan PIN tertentu, device assign PIN device baru
- Response success: "Successfully!" atau "1</Result>"
- TZ1=0 = no restriction (all day)
- GetAttLog "All" return semua log (kosong jika belum ada scan)
"""
import http.client
import re
from datetime import datetime, time, timedelta
from typing import Optional, List, Dict
from fastapi import HTTPException

from sqlalchemy.orm import Session
from sqlalchemy import and_

from app.models.x606_models import (
    X606Device, X606JadwalKBM, X606JadwalPeserta, AbsensiX606,
    X606UserCache, StatusAbsensiX606, HariEnum
)
from app.models.models import User, Ruangan


class X606SOAPClient:
    """Client SOAP lightweight untuk X606-S (raw XML over HTTP/1.0 TCP)."""

    def __init__(self, ip: str, com_key: str = "0", timeout: int = 5):
        self.ip = ip
        self.com_key = com_key
        self.timeout = timeout

    def _send(self, xml_payload: str) -> str:
        try:
            conn = http.client.HTTPConnection(self.ip, 80, timeout=self.timeout)
            headers = {"Content-Type": "text/xml", "Content-Length": len(xml_payload)}
            conn.request("POST", "/iWsService", body=xml_payload, headers=headers)
            resp = conn.getresponse()
            body = resp.read().decode("utf-8", errors="ignore")
            conn.close()
            return body
        except TimeoutError:
            raise HTTPException(status_code=504, detail=f"Timeout koneksi ke {self.ip}:80")
        except ConnectionRefusedError:
            raise HTTPException(
                status_code=503,
                detail=f"Perangkat {self.ip} menolak koneksi. Pastikan port 80 terbuka.",
            )
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Koneksi error: {str(e)}")

    def _is_success(self, xml: str) -> bool:
        """Cek apakah response mengandung indikasi sukses."""
        xml_lower = xml.lower()
        return any(marker in xml_lower for marker in ["successfully", "succeed", "1</result>"])

    def _parse_value(self, xml: str, tag: str) -> Optional[str]:
        """Parsing manual seperti Parse_Data() di PHP."""
        patterns = [
            f"<{tag}[^>]*>([^<]*)</{tag}>",
            f"<{tag}>([^<]*)</{tag}>",
        ]
        for pattern in patterns:
            match = re.search(pattern, xml, re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    def _parse_rows(self, xml: str, response_tag: str) -> List[Dict[str, str]]:
        """Parse semua <Row> dari response SOAP."""
        rows = []
        pattern = f"<{response_tag}[^>]*>(.*?)</{response_tag}>"
        match = re.search(pattern, xml, re.DOTALL | re.IGNORECASE)
        if not match:
            return rows

        content = match.group(1)
        row_matches = re.findall(r"<Row[^>]*>(.*?)</Row>", content, re.DOTALL | re.IGNORECASE)

        for row_xml in row_matches:
            row = {}
            tags = re.findall(r"<([^/][^>\s]*)[^>]*>([^<]*)</\1>", row_xml, re.IGNORECASE)
            for tag, val in tags:
                row[tag] = val.strip()
            rows.append(row)
        return rows

    # --- USER MANAGEMENT ---
    def get_all_users(self) -> List[Dict[str, str]]:
        xml = f'<GetAllUserInfo><ArgComKey xsi:type="xsd:integer">{self.com_key}</ArgComKey></GetAllUserInfo>'
        return self._parse_rows(self._send(xml), "GetAllUserInfoResponse")

    def get_user(self, pin: str) -> Optional[Dict[str, str]]:
        """Get user by PIN device (internal PIN), bukan PIN2."""
        xml = f'<GetUserInfo><ArgComKey xsi:type="xsd:integer">{self.com_key}</ArgComKey><Arg><PIN xsi:type="xsd:integer">{pin}</PIN></Arg></GetUserInfo>'
        rows = self._parse_rows(self._send(xml), "GetUserInfoResponse")
        return rows[0] if rows else None

    def set_user(self, pin: str, name: str, **kwargs) -> bool:
        """Set user dengan PIN (akan menjadi PIN2 di device)."""
        opts = "".join([f"<{k}>{v}</{k}>" for k, v in kwargs.items()])
        xml = f'<SetUserInfo><ArgComKey xsi:type="xsd:integer">{self.com_key}</ArgComKey><Arg><PIN>{pin}</PIN><Name>{name}</Name>{opts}</Arg></SetUserInfo>'
        return self._is_success(self._send(xml))

    def delete_user(self, pin: str) -> bool:
        """Delete user by PIN device (internal PIN)."""
        xml = f'<DeleteUser><ArgComKey xsi:type="xsd:integer">{self.com_key}</ArgComKey><Arg><PIN xsi:type="xsd:integer">{pin}</PIN></Arg></DeleteUser>'
        return self._is_success(self._send(xml))

    def clear_all_users(self) -> bool:
        xml = f'<ClearData><ArgComKey xsi:type="xsd:integer">{self.com_key}</ArgComKey><Arg><Value xsi:type="xsd:integer">3</Value></Arg></ClearData>'
        return self._is_success(self._send(xml))

    # --- FINGERPRINT ---
    def get_fingerprint(self, pin: str, finger_id: int) -> Optional[Dict[str, str]]:
        xml = f'<GetUserTemplate><ArgComKey xsi:type="xsd:integer">{self.com_key}</ArgComKey><Arg><PIN xsi:type="xsd:integer">{pin}</PIN><FingerID xsi:type="xsd:integer">{finger_id}</FingerID></Arg></GetUserTemplate>'
        rows = self._parse_rows(self._send(xml), "GetUserTemplateResponse")
        return rows[0] if rows else None

    def set_fingerprint(self, pin: str, finger_id: int, template: str, size: int = None, valid: int = 1) -> bool:
        if size is None: size = len(template)
        xml = f'<SetUserTemplate><ArgComKey xsi:type="xsd:integer">{self.com_key}</ArgComKey><Arg><PIN xsi:type="xsd:integer">{pin}</PIN><FingerID xsi:type="xsd:integer">{finger_id}</FingerID><Size>{size}</Size><Valid>{valid}</Valid><Template>{template}</Template></Arg></SetUserTemplate>'
        return self._is_success(self._send(xml))

    def delete_fingerprint(self, pin: str) -> bool:
        xml = f'<DeleteTemplate><ArgComKey xsi:type="xsd:integer">{self.com_key}</ArgComKey><Arg><PIN xsi:type="xsd:integer">{pin}</PIN></Arg></DeleteTemplate>'
        return self._is_success(self._send(xml))

    def clear_all_fingerprints(self) -> bool:
        xml = f'<ClearData><ArgComKey xsi:type="xsd:integer">{self.com_key}</ArgComKey><Arg><Value xsi:type="xsd:integer">2</Value></Arg></ClearData>'
        return self._is_success(self._send(xml))

    # --- ATTENDANCE LOG ---
    def get_logs(self, pin: str = "All") -> List[Dict[str, str]]:
        """Get logs. PIN bisa "All" atau PIN device spesifik."""
        xml = f'<GetAttLog><ArgComKey xsi:type="xsd:integer">{self.com_key}</ArgComKey><Arg><PIN xsi:type="xsd:integer">{pin}</PIN></Arg></GetAttLog>'
        return self._parse_rows(self._send(xml), "GetAttLogResponse")

    def clear_logs(self) -> bool:
        xml = f'<ClearData><ArgComKey xsi:type="xsd:integer">{self.com_key}</ArgComKey><Arg><Value xsi:type="xsd:integer">1</Value></Arg></ClearData>'
        return self._is_success(self._send(xml))

    # --- SYSTEM ---
    def refresh_db(self) -> bool:
        xml = f'<RefreshDB><ArgComKey xsi:type="xsd:integer">{self.com_key}</ArgComKey></RefreshDB>'
        return self._is_success(self._send(xml))

    def restart(self) -> bool:
        xml = f'<Restart><ArgComKey xsi:type="xsd:integer">{self.com_key}</ArgComKey></Restart>'
        return self._is_success(self._send(xml))

    def get_time(self) -> Dict[str, str]:
        xml = f'<GetDate><ArgComKey xsi:type="xsd:integer">{self.com_key}</ArgComKey></GetDate>'
        r = self._send(xml)
        return {"date": self._parse_value(r, "Date") or "", "time": self._parse_value(r, "Time") or ""}

    def set_time(self, date: str, time_str: str) -> bool:
        xml = f'<SetDate><ArgComKey xsi:type="xsd:integer">{self.com_key}</ArgComKey><Arg><Date xsi:type="xsd:string">{date}</Date><Time xsi:type="xsd:string">{time_str}</Time></Arg></SetDate>'
        return self._is_success(self._send(xml))

    def get_option(self, name: str) -> Optional[str]:
        xml = f'<GetOption><ArgComKey xsi:type="xsd:integer">{self.com_key}</ArgComKey><Arg><Name xsi:type="xsd:string">{name}</Name></Arg></GetOption>'
        return self._parse_value(self._send(xml), "Value")

    def set_option(self, name: str, value: str) -> bool:
        xml = f'<SetOption><ArgComKey xsi:type="xsd:integer">{self.com_key}</ArgComKey><Arg><Name xsi:type="xsd:string">{name}</Name><Value xsi:type="xsd:string">{value}</Value></Arg></SetOption>'
        return self._is_success(self._send(xml))


class X606LabService:
    """Business Logic untuk Smart Lock Lab Multimedia 2."""

    def __init__(self, db: Session):
        self.db = db

    def get_jadwal_aktif(self, ruangan_id: int, check_time: datetime = None) -> Optional[X606JadwalKBM]:
        if check_time is None:
            check_time = datetime.now()
        hari_map = {
            "Monday": "Senin", "Tuesday": "Selasa", "Wednesday": "Rabu",
            "Thursday": "Kamis", "Friday": "Jumat", "Saturday": "Sabtu", "Sunday": "Minggu"
        }
        hari_ini = hari_map[check_time.strftime("%A")]
        jam_now = check_time.time()
        return self.db.query(X606JadwalKBM).filter(
            and_(
                X606JadwalKBM.ruangan_id == ruangan_id,
                X606JadwalKBM.hari == hari_ini,
                X606JadwalKBM.jam_mulai <= jam_now,
                X606JadwalKBM.jam_selesai >= jam_now,
                X606JadwalKBM.is_active == True
            )
        ).first()

    def check_user_access(self, user_id: int, ruangan_id: int, check_time: datetime = None) -> Dict:
        if check_time is None:
            check_time = datetime.now()
        jadwal = self.get_jadwal_aktif(ruangan_id, check_time)
        if not jadwal:
            return {"can_access": False, "reason": "Tidak ada jadwal KBM aktif saat ini di lab ini.", "jadwal": None}
        peserta = self.db.query(X606JadwalPeserta).filter(
            X606JadwalPeserta.jadwal_id == jadwal.id,
            X606JadwalPeserta.user_id == user_id
        ).first()
        if not peserta:
            return {
                "can_access": False,
                "reason": f"Anda tidak terdaftar di jadwal {jadwal.nama_matakuliah} ({jadwal.kelas}) saat ini.",
                "jadwal": jadwal
            }
        return {"can_access": True, "reason": "Akses diizinkan.", "jadwal": jadwal}

    def process_scan_log(self, device_id: str, pin: str, scan_time: datetime,
                         verified: str, status: str) -> AbsensiX606:
        """
        Process scan log. PIN dari device adalah PIN device (internal).
        Cari cache berdasarkan PIN device.
        """
        cache = self.db.query(X606UserCache).filter(
            X606UserCache.device_id == device_id,
            X606UserCache.pin == pin
        ).first()

        if not cache:
            absensi = AbsensiX606(
                user_id=0, ruangan_id=0, device_id=device_id,
                waktu_scan=scan_time, verified=verified, status_scan=status,
                status_absensi=StatusAbsensiX606.TIDAK_TERJADWAL,
                is_valid_jadwal=False,
                keterangan=f"PIN {pin} tidak terdaftar di sistem"
            )
            self.db.add(absensi)
            self.db.commit()
            return absensi

        user_id = cache.user_id
        device = self.db.query(X606Device).filter(X606Device.device_id == device_id).first()
        ruangan_id = device.ruangan_id if device else 0

        access = self.check_user_access(user_id, ruangan_id, scan_time)
        jadwal = access["jadwal"]

        if not jadwal:
            status_absensi = StatusAbsensiX606.TIDAK_TERJADWAL
            keterangan = "Scan di luar jadwal KBM"
        elif not access["can_access"]:
            status_absensi = StatusAbsensiX606.TIDAK_TERJADWAL
            keterangan = access["reason"]
        else:
            toleransi = timedelta(minutes=5)
            batas_terlambat = datetime.combine(scan_time.date(), jadwal.jam_mulai) + toleransi
            if scan_time > batas_terlambat:
                status_absensi = StatusAbsensiX606.TERLAMBAT
                keterangan = f"Terlambat {int((scan_time - batas_terlambat).total_seconds() / 60)} menit"
            else:
                status_absensi = StatusAbsensiX606.HADIR
                keterangan = "Tepat waktu"

        absensi = AbsensiX606(
            user_id=user_id, ruangan_id=ruangan_id, device_id=device_id,
            jadwal_id=jadwal.id if jadwal else None,
            waktu_scan=scan_time, verified=verified, status_scan=status,
            status_absensi=status_absensi,
            is_valid_jadwal=access["can_access"],
            keterangan=keterangan
        )
        self.db.add(absensi)
        self.db.commit()
        self.db.refresh(absensi)
        return absensi

    def pull_logs_from_device(self, device_id: str) -> Dict:
        device = self.db.query(X606Device).filter(X606Device.device_id == device_id).first()
        if not device:
            return {"success": False, "message": "Device tidak ditemukan"}
        client = X606SOAPClient(ip=device.ip_address, com_key=device.com_key)
        try:
            logs = client.get_logs("All")
        except Exception as e:
            return {"success": False, "message": f"Gagal koneksi ke device: {str(e)}"}

        new_records, invalid_scans = 0, 0
        for log in logs:
            pin = log.get("PIN", "")
            dt_str = log.get("DateTime", "")
            verified = log.get("Verified", "")
            status = log.get("Status", "")
            if not pin or not dt_str:
                continue
            try:
                scan_time = datetime.strptime(dt_str, "%Y-%m-%d %H:%M:%S")
            except ValueError:
                continue

            exists = self.db.query(AbsensiX606).filter(
                AbsensiX606.device_id == device_id,
                AbsensiX606.waktu_scan == scan_time,
                AbsensiX606.user_id == (
                    self.db.query(X606UserCache.user_id)
                    .filter(X606UserCache.device_id == device_id, X606UserCache.pin == pin)
                    .scalar_subquery()
                )
            ).first()
            if exists:
                continue

            absensi = self.process_scan_log(device_id, pin, scan_time, verified, status)
            new_records += 1
            if not absensi.is_valid_jadwal:
                invalid_scans += 1

        device.last_sync = datetime.now()
        self.db.commit()
        return {
            "success": True, "device_id": device_id,
            "new_records": new_records, "invalid_scans": invalid_scans,
            "message": f"Berhasil pull {new_records} log ({invalid_scans} tidak valid)"
        }

    def sync_users_to_device(self, device_id: str, jadwal_id: int) -> Dict:
        device = self.db.query(X606Device).filter(X606Device.device_id == device_id).first()
        jadwal = self.db.query(X606JadwalKBM).filter(X606JadwalKBM.id == jadwal_id).first()
        if not device or not jadwal:
            return {"success": False, "message": "Device atau jadwal tidak ditemukan"}

        client = X606SOAPClient(ip=device.ip_address, com_key=device.com_key)
        tz_start = jadwal.jam_mulai.strftime("%H%M")
        tz_end = jadwal.jam_selesai.strftime("%H%M")
        timezone = f"{tz_start}-{tz_end}"

        peserta = self.db.query(X606JadwalPeserta).filter(X606JadwalPeserta.jadwal_id == jadwal_id).all()
        success_count, failed_count = 0, 0

        for p in peserta:
            user = p.user
            # Gunakan x606_pin jika sudah ada, atau generate dari user_id
            pin_request = p.x606_pin or str(p.user_id).zfill(5)
            kwargs = {"Privilege": "0", "TZ1": timezone, "TZ2": "", "TZ3": ""}
            try:
                if client.set_user(pin_request, user.nama, **kwargs):
                    # Setelah set, get_all_users untuk mapping PIN device
                    all_users = client.get_all_users()
                    pin_device = None
                    for u in all_users:
                        if u.get("PIN2") == pin_request or u.get("Name") == user.nama:
                            pin_device = u.get("PIN")
                            break

                    # Update cache dengan PIN device yang benar
                    if pin_device:
                        cache = self.db.query(X606UserCache).filter(
                            X606UserCache.device_id == device_id, X606UserCache.pin == pin_device
                        ).first()
                        if not cache:
                            cache = X606UserCache(
                                device_id=device_id, pin=pin_device, user_id=p.user_id, name=user.nama
                            )
                            self.db.add(cache)
                        else:
                            cache.name = user.nama
                            cache.last_sync = datetime.now()

                        # Update x606_pin di peserta dengan PIN request (untuk referensi)
                        if not p.x606_pin:
                            p.x606_pin = pin_request

                    success_count += 1
                else:
                    failed_count += 1
            except Exception as e:
                failed_count += 1

        client.refresh_db()
        self.db.commit()
        return {
            "success": True,
            "message": f"Sync selesai: {success_count} berhasil, {failed_count} gagal",
            "timezone_applied": timezone, "device_id": device_id
        }

    def clear_users_from_device(self, device_id: str) -> Dict:
        """Hapus semua user dari device (kecuali admin/default)."""
        device = self.db.query(X606Device).filter(X606Device.device_id == device_id).first()
        if not device:
            return {"success": False, "message": "Device tidak ditemukan"}
        client = X606SOAPClient(ip=device.ip_address, com_key=device.com_key)

        # Get all users dari device
        all_users = client.get_all_users()
        deleted_count = 0

        for u in all_users:
            pin = u.get("PIN")
            name = u.get("Name", "")
            # Skip admin/default user (PIN 1 biasanya admin)
            if pin and pin != "1":
                try:
                    if client.delete_user(pin):
                        deleted_count += 1
                except Exception:
                    pass

        # Hapus juga dari cache
        self.db.query(X606UserCache).filter(X606UserCache.device_id == device_id).delete()
        self.db.commit()

        return {
            "success": True,
            "message": f"{deleted_count} user dihapus dari device",
            "device_id": device_id
        }