import cv2
import os
import time
import requests
import threading
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Konfigurasi ──────────────────────────────────────────
SERVER_URL  = os.getenv("SERVER_URL", "127.0.0.1:8000")
KAMERA_ID   = int(os.getenv("KAMERA_ID"))
RUANGAN_ID  = int(os.getenv("RUANGAN_ID"))
DURASI_SEG  = int(os.getenv("DURASI_SEG"))
OUTPUT_DIR  = Path(os.getenv("OUTPUT_DIR"))
OUTPUT_DIR.mkdir(exist_ok=True)

# ── Video settings ───────────────────────────────────────
FRAME_WIDTH  = 640
FRAME_HEIGHT = 480
FPS          = 15


def cek_ffmpeg() -> bool:
    """Cek apakah FFmpeg tersedia di sistem."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-version"],
            capture_output=True, text=True
        )
        return result.returncode == 0
    except FileNotFoundError:
        return False


def konversi_h264(input_path: Path, output_path: Path) -> bool:
    """
    Konversi video dari mp4v ke H.264 menggunakan FFmpeg.
    H.264 didukung semua browser modern.
    """
    try:
        cmd = [
            "ffmpeg",
            "-i", str(input_path),       # input file
            "-vcodec", "libx264",         # codec H.264
            "-acodec", "aac",             # audio codec
            "-preset", "ultrafast",       # kecepatan encode (ultrafast = cepat, ukuran agak besar)
            "-crf", "28",                 # kualitas (18=tinggi, 28=sedang, 35=rendah)
            "-movflags", "+faststart",    # optimasi untuk streaming web
            "-y",                         # overwrite output jika ada
            str(output_path)
        ]
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            print(f"[FFMPEG] Error: {result.stderr[-300:]}")
            return False
        return True
    except Exception as e:
        print(f"[FFMPEG] Exception: {e}")
        return False


def upload_video(
    file_path: Path,
    waktu_mulai: datetime,
    waktu_selesai: datetime
):
    """Upload segmen video ke server dalam thread terpisah."""
    try:
        print(f"[UPLOAD] Mengirim {file_path.name} ke server...")
        with open(file_path, "rb") as f:
            resp = requests.post(
                f"{SERVER_URL}/kamera/upload",
                data={
                    "ruangan_id":    str(RUANGAN_ID),
                    "waktu_mulai":   waktu_mulai.isoformat(),
                    "waktu_selesai": waktu_selesai.isoformat(),
                },
                files={"video": (file_path.name, f, "video/mp4")},
                timeout=180
            )
        if resp.status_code == 200:
            result = resp.json()
            print(f"[UPLOAD] ✓ Berhasil — ID: {result.get('rekaman_id')} | "
                  f"Ukuran: {result.get('ukuran_mb')} MB")
        else:
            print(f"[UPLOAD] ✗ Gagal — {resp.status_code}: {resp.text[:200]}")
    except Exception as e:
        print(f"[UPLOAD] ✗ Error: {e}")
    finally:
        # Hapus file setelah upload (raw dan converted)
        for f in [file_path, file_path.with_suffix(".raw.mp4")]:
            try:
                if f.exists():
                    f.unlink()
                    print(f"[CLEANUP] {f.name} dihapus")
            except Exception:
                pass


def proses_dan_upload(
    raw_path: Path,
    waktu_mulai: datetime,
    waktu_selesai: datetime,
    gunakan_ffmpeg: bool
):
    """Konversi (jika perlu) lalu upload."""
    if gunakan_ffmpeg:
        # Nama file output H.264
        h264_path = raw_path.with_suffix("").with_suffix(".mp4")
        print(f"[FFMPEG] Mengkonversi ke H.264: {h264_path.name}...")

        ok = konversi_h264(raw_path, h264_path)
        if ok:
            print(f"[FFMPEG] ✓ Konversi selesai")
            # Hapus raw file
            try:
                raw_path.unlink()
            except Exception:
                pass
            upload_video(h264_path, waktu_mulai, waktu_selesai)
        else:
            print(f"[FFMPEG] ✗ Konversi gagal, upload file raw sebagai fallback")
            # Rename raw ke mp4 dan upload
            raw_path.rename(raw_path.with_suffix("").with_suffix(".mp4"))
            upload_video(
                raw_path.with_suffix("").with_suffix(".mp4"),
                waktu_mulai,
                waktu_selesai
            )
    else:
        # Tanpa FFmpeg, langsung upload file raw
        final_path = raw_path.parent / raw_path.name.replace(".raw.mp4", ".mp4")
        raw_path.rename(final_path)
        upload_video(final_path, waktu_mulai, waktu_selesai)


def main():
    print("=" * 55)
    print("  Smart Door Lock — Kamera Monitoring")
    print("=" * 55)
    print(f"  Server    : {SERVER_URL}")
    print(f"  Kamera ID : {KAMERA_ID}")
    print(f"  Ruangan   : {RUANGAN_ID}")
    print(f"  Durasi    : {DURASI_SEG} detik/segmen")

    # Cek FFmpeg
    gunakan_ffmpeg = cek_ffmpeg()
    if gunakan_ffmpeg:
        print(f"  FFmpeg    : ✓ Tersedia (H.264)")
    else:
        print(f"  FFmpeg    : ✗ Tidak ditemukan (video mungkin tidak bisa diputar di browser)")
    print("=" * 55)
    print("  Tekan Ctrl+C untuk berhenti\n")

    # Cek koneksi server
    try:
        resp = requests.get(f"{SERVER_URL}/health", timeout=5)
        if resp.status_code == 200:
            print("[SERVER] ✓ Server online\n")
        else:
            print(f"[SERVER] ⚠ Status {resp.status_code}\n")
    except Exception:
        print("[SERVER] ✗ Tidak bisa terhubung ke server\n")
        return

    # Buka kamera
    print(f"[KAMERA] Membuka kamera index {KAMERA_ID}...")
    cap = cv2.VideoCapture(KAMERA_ID)

    if not cap.isOpened():
        print(f"[KAMERA] ✗ Gagal membuka kamera index {KAMERA_ID}")
        print("  Pastikan kamera terhubung dan tidak dipakai aplikasi lain")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  FRAME_WIDTH)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, FRAME_HEIGHT)
    cap.set(cv2.CAP_PROP_FPS, FPS)

    actual_w   = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h   = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    actual_fps = cap.get(cv2.CAP_PROP_FPS) or FPS
    print(f"[KAMERA] ✓ {actual_w}x{actual_h} @ {actual_fps:.0f}fps\n")

    # Gunakan XVID sebagai codec raw (lebih kompatibel dengan FFmpeg input)
    fourcc = cv2.VideoWriter_fourcc(*"XVID") if gunakan_ffmpeg \
             else cv2.VideoWriter_fourcc(*"mp4v")

    segmen = 0

    try:
        while True:
            segmen += 1
            ts_mulai   = datetime.now(timezone.utc)
            ts_mulai_l = datetime.now()

            # Raw file pakai ekstensi .raw.mp4 supaya mudah dibedakan
            if gunakan_ffmpeg:
                nama_raw  = f"rekaman_{RUANGAN_ID}_{ts_mulai_l.strftime('%Y%m%d_%H%M%S')}.raw.mp4"
                ext_raw   = ".avi"  # XVID lebih baik disimpan sebagai .avi
                nama_raw  = nama_raw.replace(".raw.mp4", ".raw.avi")
                raw_path  = OUTPUT_DIR / nama_raw
                fourcc    = cv2.VideoWriter_fourcc(*"XVID")
            else:
                nama_raw  = f"rekaman_{RUANGAN_ID}_{ts_mulai_l.strftime('%Y%m%d_%H%M%S')}.raw.mp4"
                raw_path  = OUTPUT_DIR / nama_raw
                fourcc    = cv2.VideoWriter_fourcc(*"mp4v")

            writer = cv2.VideoWriter(
                str(raw_path), fourcc,
                actual_fps, (actual_w, actual_h)
            )

            print(f"[REC] ▶ Segmen {segmen} → {raw_path.name}")
            frame_count = 0
            t_start     = time.time()

            while (time.time() - t_start) < DURASI_SEG:
                ret, frame = cap.read()
                if not ret:
                    time.sleep(0.05)
                    continue

                # Timestamp overlay di frame
                ts_text = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
                overlay_y = frame.shape[0] - 8
                # Background hitam
                cv2.rectangle(
                    frame,
                    (0, frame.shape[0] - 22),
                    (frame.shape[1], frame.shape[0]),
                    (0, 0, 0), -1
                )
                # Teks putih
                cv2.putText(
                    frame,
                    f"Ruang Multimedia Polsri  |  {ts_text}",
                    (8, overlay_y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.42, (255, 255, 255), 1, cv2.LINE_AA
                )

                writer.write(frame)
                frame_count += 1

            writer.release()
            ts_selesai = datetime.now(timezone.utc)

            ukuran_mb = raw_path.stat().st_size / (1024 * 1024)
            print(f"[REC] ■ Segmen {segmen} selesai — "
                  f"{frame_count} frame | {ukuran_mb:.2f} MB (raw)")

            # Konversi + upload di thread terpisah
            t = threading.Thread(
                target=proses_dan_upload,
                args=(raw_path, ts_mulai, ts_selesai, gunakan_ffmpeg),
                daemon=True
            )
            t.start()

    except KeyboardInterrupt:
        print("\n\n[INFO] Dihentikan (Ctrl+C)")
    finally:
        cap.release()
        print("[KAMERA] Kamera dilepas")


if __name__ == "__main__":
    main()