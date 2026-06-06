"""
Script live streaming kamera ke dashboard Smart Door Lock.
Mendukung:
  - Webcam lokal      : KAMERA_URL=0
  - IP Camera RTSP    : KAMERA_URL=rtsp://user:pass@192.168.1.100:554/stream
  - IP Camera MJPEG   : KAMERA_URL=http://192.168.1.100:8080/video
  - File video (test) : KAMERA_URL=test.mp4

Jalankan di PC yang ada di lab (bukan di server):
    python stream_kamera.py

Konfigurasi di .env:
    SERVER_URL  = https://nama-project.up.railway.app
    KAMERA_URL  = 0                    (webcam) ATAU rtsp://... (IP cam)
    RUANGAN_ID  = 1
    STREAM_FPS  = 10
    STREAM_W    = 640
    STREAM_H    = 480
    JPEG_QUALITY = 65                  (50-90, lebih rendah = lebih hemat bandwidth)
"""

import cv2
import asyncio
import websockets
import time
import os
import sys
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

# ── Konfigurasi ──────────────────────────────────────────
SERVER_URL   = os.getenv("SERVER_URL",    "http://localhost:8000")
KAMERA_URL   = os.getenv("KAMERA_URL",   os.getenv("KAMERA_ID", "0"))
RUANGAN_ID   = int(os.getenv("RUANGAN_ID",   "1"))
STREAM_FPS   = int(os.getenv("STREAM_FPS",   "10"))
STREAM_W     = int(os.getenv("STREAM_W",     "640"))
STREAM_H     = int(os.getenv("STREAM_H",     "480"))
JPEG_QUALITY = int(os.getenv("JPEG_QUALITY", "65"))

# Konversi ke WebSocket URL
WS_URL      = SERVER_URL.replace("https://", "wss://").replace("http://", "ws://")
WS_ENDPOINT = f"{WS_URL}/ws/stream/{RUANGAN_ID}"

FRAME_INTERVAL = 1.0 / STREAM_FPS


def parse_kamera_source():
    """
    Parse KAMERA_URL menjadi source yang bisa dibuka OpenCV.
    - "0", "1", "2" → int (webcam index)
    - "rtsp://..."   → string (IP cam RTSP)
    - "http://..."   → string (IP cam MJPEG)
    - path file      → string (video file)
    """
    src = KAMERA_URL.strip()
    if src.isdigit():
        return int(src)
    return src


def buka_kamera():
    """Buka koneksi ke kamera, return VideoCapture atau None."""
    source = parse_kamera_source()
    tipe   = "Webcam" if isinstance(source, int) else \
             "RTSP"   if str(source).startswith("rtsp") else \
             "HTTP"   if str(source).startswith("http") else "File"

    print(f"[KAMERA] Tipe     : {tipe}")
    print(f"[KAMERA] Source   : {source}")

    if tipe in ("RTSP", "HTTP"):
        # Untuk IP Camera — gunakan backend FFMPEG yang lebih stabil
        cap = cv2.VideoCapture(source, cv2.CAP_FFMPEG)
        # Kurangi buffer untuk mengurangi delay (real-time)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
    else:
        cap = cv2.VideoCapture(source)

    if not cap.isOpened():
        print(f"[KAMERA] ✗ Gagal membuka: {source}")
        if tipe == "RTSP":
            print("  Tips RTSP:")
            print("  - Pastikan format: rtsp://user:pass@IP:554/path")
            print("  - Cek username/password kamera")
            print("  - Cek port (biasanya 554 atau 8554)")
        elif tipe == "HTTP":
            print("  Tips HTTP MJPEG:")
            print("  - Pastikan format: http://IP:port/video atau /mjpeg")
            print("  - Cek apakah kamera support HTTP stream")
        return None

    # Set resolusi
    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  STREAM_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, STREAM_H)

    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"[KAMERA] ✓ Terbuka → {actual_w}×{actual_h}")
    return cap


def encode_frame(frame) -> bytes:
    """
    Encode frame ke JPEG bytes dengan overlay timestamp.
    """
    h, w = frame.shape[:2]
    ts   = datetime.now().strftime("%d/%m/%Y %H:%M:%S")

    # Background strip hitam di bawah
    cv2.rectangle(frame, (0, h - 24), (w, h), (0, 0, 0), -1)
    cv2.putText(
        frame,
        f"Ruangan {RUANGAN_ID}  |  {ts}",
        (8, h - 7),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45, (255, 255, 255), 1, cv2.LINE_AA
    )

    _, jpeg = cv2.imencode(
        '.jpg', frame,
        [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY]
    )
    return jpeg.tobytes()


async def stream_loop():
    """Loop utama: buka kamera → connect WebSocket → kirim frame."""
    print("=" * 58)
    print("  Smart Door Lock — Live Stream Kamera IP")
    print("=" * 58)
    print(f"  Server      : {SERVER_URL}")
    print(f"  WebSocket   : {WS_ENDPOINT}")
    print(f"  Ruangan ID  : {RUANGAN_ID}")
    print(f"  FPS target  : {STREAM_FPS}")
    print(f"  Kualitas    : {JPEG_QUALITY}%")
    print("=" * 58)
    print("  Tekan Ctrl+C untuk berhenti\n")

    reconnect_delay = 2

    while True:
        # ── Buka kamera ──────────────────────────────────
        cap = buka_kamera()
        if cap is None:
            print(f"[KAMERA] Coba lagi dalam {reconnect_delay} detik...")
            await asyncio.sleep(reconnect_delay)
            reconnect_delay = min(reconnect_delay * 2, 30)
            continue

        reconnect_delay = 2

        # ── Connect WebSocket ─────────────────────────────
        try:
            print(f"\n[WS] Menghubungkan ke server...")
            async with websockets.connect(
                WS_ENDPOINT,
                ping_interval   = 20,
                ping_timeout    = 10,
                max_size        = 10 * 1024 * 1024,
                additional_headers = {"Origin": SERVER_URL}
            ) as ws:
                print(f"[WS] ✓ Terhubung! Mulai streaming...\n")
                reconnect_delay = 2

                frame_count = 0
                fps_count   = 0
                t_fps       = time.time()
                t_last_ok   = time.time()

                while True:
                    t_frame = time.time()

                    ret, frame = cap.read()
                    if not ret:
                        print("[KAMERA] ⚠ Frame gagal dibaca")

                        # Coba reconnect kamera (IP cam bisa putus)
                        cap.release()
                        await asyncio.sleep(2)
                        cap = buka_kamera()
                        if cap is None:
                            break
                        continue

                    # Encode dan kirim
                    jpeg = encode_frame(frame)
                    await ws.send(jpeg)

                    frame_count += 1
                    fps_count   += 1
                    t_last_ok    = time.time()

                    # Tampilkan stats tiap 5 detik
                    elapsed = time.time() - t_fps
                    if elapsed >= 5.0:
                        actual_fps  = fps_count / elapsed
                        kb_per_frame = len(jpeg) / 1024
                        print(
                            f"[STREAM] ▶ {actual_fps:.1f} fps | "
                            f"{kb_per_frame:.1f} KB/frame | "
                            f"Total: {frame_count} frame"
                        )
                        fps_count = 0
                        t_fps     = time.time()

                    # Jaga interval FPS
                    elapsed_frame = time.time() - t_frame
                    sleep_time    = FRAME_INTERVAL - elapsed_frame
                    if sleep_time > 0:
                        await asyncio.sleep(sleep_time)

        except websockets.exceptions.ConnectionClosed as e:
            print(f"\n[WS] Koneksi terputus: {e}")
        except ConnectionRefusedError:
            print(f"\n[WS] ✗ Server tidak bisa dihubungi")
            print(f"      Pastikan server Railway berjalan")
        except Exception as e:
            print(f"\n[WS] Error: {type(e).__name__}: {e}")
        finally:
            if cap:
                cap.release()
                print("[KAMERA] Kamera dilepas")

        # Reconnect otomatis
        print(f"[WS] Reconnect dalam {reconnect_delay} detik...")
        await asyncio.sleep(reconnect_delay)
        reconnect_delay = min(reconnect_delay * 2, 30)


async def main():
    try:
        await stream_loop()
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n[INFO] Dihentikan (Ctrl+C)")
        print("[INFO] Script selesai")