"""
Manager untuk mengelola koneksi WebSocket live streaming.
Setiap ruangan punya pool koneksi sendiri.
"""
from fastapi import WebSocket
from typing import Dict, Set
import asyncio


class StreamManager:
    def __init__(self):
        # Dict: ruangan_id → set of WebSocket connections (viewers)
        self.viewers: Dict[int, Set[WebSocket]] = {}
        # Dict: ruangan_id → apakah ada streamer aktif
        self.streamers: Dict[int, bool] = {}

    async def connect_viewer(self, ruangan_id: int, ws: WebSocket):
        """Browser dashboard connect untuk menonton stream."""
        await ws.accept()
        if ruangan_id not in self.viewers:
            self.viewers[ruangan_id] = set()
        self.viewers[ruangan_id].add(ws)

    def disconnect_viewer(self, ruangan_id: int, ws: WebSocket):
        """Browser dashboard disconnect."""
        if ruangan_id in self.viewers:
            self.viewers[ruangan_id].discard(ws)

    async def connect_streamer(self, ruangan_id: int, ws: WebSocket):
        """Script Python connect untuk kirim frame."""
        await ws.accept()
        self.streamers[ruangan_id] = True

    def disconnect_streamer(self, ruangan_id: int):
        """Script Python disconnect."""
        self.streamers[ruangan_id] = False

    async def broadcast_frame(self, ruangan_id: int, frame_bytes: bytes):
        """Kirim frame ke semua viewer ruangan ini."""
        if ruangan_id not in self.viewers:
            return

        dead = set()
        for ws in self.viewers[ruangan_id].copy():
            try:
                await ws.send_bytes(frame_bytes)
            except Exception:
                dead.add(ws)

        # Hapus koneksi yang sudah mati
        for ws in dead:
            self.viewers[ruangan_id].discard(ws)

    def get_viewer_count(self, ruangan_id: int) -> int:
        return len(self.viewers.get(ruangan_id, set()))

    def is_streaming(self, ruangan_id: int) -> bool:
        return self.streamers.get(ruangan_id, False)

    def get_all_status(self) -> dict:
        return {
            rid: {
                "streaming": self.streamers.get(rid, False),
                "viewers":   len(viewers)
            }
            for rid, viewers in self.viewers.items()
        }


# Singleton — satu instance untuk seluruh aplikasi
stream_manager = StreamManager()