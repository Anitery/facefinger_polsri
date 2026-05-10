"""
Script live streaming kamera ke dashboard.
Jalankan bersamaan dengan kamera_capture.py atau sendiri.

    python stream_kamera.py

Konfigurasi di .env:
    SERVER_URL  = http://localhost:8000
    KAMERA_ID   = 0
    RUANGAN_ID  = 1
    STREAM_FPS  = 10   (frame per detik yang dikirim, lebih rendah = lebih hemat bandwidth)
    STREAM_W    = 640
    STREAM_H    = 480
"""

import cv2
import asyncio
import websockets
import time
import os
import sys
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

# ── Konfigurasi ──────────────────────────────────────────
SERVER_URL  = os.getenv("SERVER_URL", "http://localhost:8000")
KAMERA_ID   = int(os.getenv("KAMERA_ID",  "0"))
RUANGAN_ID  = int(os.getenv("RUANGAN_ID", "1"))
STREAM_FPS  = int(os.getenv("STREAM_FPS", "10"))
STREAM_W    = int(os.getenv("STREAM_W",   "640"))
STREAM_H    = int(os.getenv("STREAM_H",   "480"))

# Konversi URL ke WebSocket URL
WS_URL = SERVER_URL.replace("https://", "wss://").replace("http://", "ws://")
WS_ENDPOINT = f"{WS_URL}/ws/stream/{RUANGAN_ID}"

# Interval antar frame (detik)
FRAME_INTERVAL = 1.0 / STREAM_FPS


def buat_frame_jpeg(frame) -> bytes:
    """Encode frame OpenCV ke JPEG bytes."""
    # Tambah timestamp overlay
    ts = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
    h, w = frame.shape[:2]

    # Background hitam di bawah
    cv2.rectangle(frame, (0, h - 24), (w, h), (0, 0, 0), -1)
    cv2.putText(
        frame,
        f"Ruangan {RUANGAN_ID}  |  {ts}",
        (8, h - 7),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.45, (255, 255, 255), 1, cv2.LINE_AA
    )

    # Encode ke JPEG (quality 70 — balance antara kualitas dan bandwidth)
    _, jpeg = cv2.imencode('.jpg', frame, [cv2.IMWRITE_JPEG_QUALITY, 70])
    return jpeg.tobytes()


async def stream_loop():
    """Loop utama: capture frame dan kirim via WebSocket."""
    print("=" * 55)
    print("  Smart Door Lock — Live Stream Kamera")
    print("=" * 55)
    print(f"  Server    : {SERVER_URL}")
    print(f"  WebSocket : {WS_ENDPOINT}")
    print(f"  Kamera ID : {KAMERA_ID}")
    print(f"  Ruangan   : {RUANGAN_ID}")
    print(f"  Target FPS: {STREAM_FPS}")
    print(f"  Resolusi  : {STREAM_W}x{STREAM_H}")
    print("=" * 55)
    print("  Tekan Ctrl+C untuk berhenti\n")

    # Buka kamera
    print(f"[KAMERA] Membuka kamera index {KAMERA_ID}...")
    cap = cv2.VideoCapture(KAMERA_ID)

    if not cap.isOpened():
        print(f"[KAMERA] ✗ Gagal membuka kamera index {KAMERA_ID}")
        return

    cap.set(cv2.CAP_PROP_FRAME_WIDTH,  STREAM_W)
    cap.set(cv2.CAP_PROP_FRAME_HEIGHT, STREAM_H)

    actual_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    actual_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    print(f"[KAMERA] ✓ Terbuka — {actual_w}x{actual_h}\n")

    reconnect_delay = 2  # detik sebelum reconnect

    while True:
        try:
            print(f"[WS] Menghubungkan ke {WS_ENDPOINT}...")
            async with websockets.connect(
                WS_ENDPOINT,
                ping_interval=20,
                ping_timeout=10,
                max_size=10 * 1024 * 1024  # max 10MB per frame
            ) as ws:
                print(f"[WS] ✓ Terhubung — mulai streaming "
                      f"@ {STREAM_FPS} FPS\n")
                reconnect_delay = 2  # reset delay setelah berhasil connect

                frame_count = 0
                t_start     = time.time()

                while True:
                    t_frame = time.time()

                    ret, frame = cap.read()
                    if not ret:
                        print("[KAMERA] ⚠ Gagal baca frame")
                        await asyncio.sleep(0.1)
                        continue

                    # Encode dan kirim
                    jpeg_bytes = buat_frame_jpeg(frame)
                    await ws.send(jpeg_bytes)
                    frame_count += 1

                    # Tampilkan stats tiap 5 detik
                    elapsed = time.time() - t_start
                    if elapsed >= 5.0:
                        actual_fps = frame_count / elapsed
                        print(f"[STREAM] ▶ {actual_fps:.1f} FPS | "
                              f"{len(jpeg_bytes)/1024:.1f} KB/frame | "
                              f"Ruangan {RUANGAN_ID}")
                        frame_count = 0
                        t_start     = time.time()

                    # Jaga interval FPS
                    elapsed_frame = time.time() - t_frame
                    sleep_time    = FRAME_INTERVAL - elapsed_frame
                    if sleep_time > 0:
                        await asyncio.sleep(sleep_time)

        except websockets.exceptions.ConnectionClosed as e:
            print(f"[WS] Koneksi terputus: {e}")
        except ConnectionRefusedError:
            print(f"[WS] ✗ Server tidak bisa dihubungi — "
                  f"pastikan server berjalan")
        except Exception as e:
            print(f"[WS] Error: {e}")

        # Reconnect otomatis
        print(f"[WS] Reconnect dalam {reconnect_delay} detik...")
        await asyncio.sleep(reconnect_delay)
        reconnect_delay = min(reconnect_delay * 2, 30)  # exponential backoff


async def main():
    cap_task = asyncio.create_task(stream_loop())
    try:
        await cap_task
    except asyncio.CancelledError:
        pass


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n[INFO] Dihentikan (Ctrl+C)")
    finally:
        print("[INFO] Script selesai")