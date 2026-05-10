from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Query
from app.services.stream_manager import stream_manager

router = APIRouter(tags=["Live Stream"])


@router.websocket("/ws/stream/{ruangan_id}")
async def ws_streamer(ruangan_id: int, websocket: WebSocket):
    """
    Endpoint untuk script Python (pengirim frame).
    Script kamera connect ke sini dan kirim frame JPEG.
    """
    await stream_manager.connect_streamer(ruangan_id, websocket)
    print(f"[STREAM] Streamer connected → ruangan {ruangan_id}")

    try:
        while True:
            # Terima frame bytes dari script Python
            frame_bytes = await websocket.receive_bytes()

            # Broadcast ke semua viewer
            await stream_manager.broadcast_frame(ruangan_id, frame_bytes)

    except WebSocketDisconnect:
        print(f"[STREAM] Streamer disconnected → ruangan {ruangan_id}")
    except Exception as e:
        print(f"[STREAM] Streamer error → ruangan {ruangan_id}: {e}")
    finally:
        stream_manager.disconnect_streamer(ruangan_id)


@router.websocket("/ws/view/{ruangan_id}")
async def ws_viewer(ruangan_id: int, websocket: WebSocket):
    """
    Endpoint untuk browser dashboard (penerima frame).
    Dashboard connect ke sini untuk menonton stream.
    """
    await stream_manager.connect_viewer(ruangan_id, websocket)
    viewer_count = stream_manager.get_viewer_count(ruangan_id)
    print(f"[STREAM] Viewer connected → ruangan {ruangan_id} "
          f"(total: {viewer_count})")

    try:
        # Kirim status awal
        is_live = stream_manager.is_streaming(ruangan_id)
        await websocket.send_json({
            "type":    "status",
            "live":    is_live,
            "viewers": viewer_count
        })

        # Keep alive — tunggu sampai disconnect
        while True:
            try:
                # Ping setiap 30 detik untuk cek koneksi masih hidup
                await websocket.receive_text()
            except Exception:
                break

    except WebSocketDisconnect:
        pass
    finally:
        stream_manager.disconnect_viewer(ruangan_id, websocket)
        print(f"[STREAM] Viewer disconnected → ruangan {ruangan_id}")


@router.get("/stream/status")
def get_stream_status():
    """Cek status semua stream yang aktif."""
    return {
        "streams": stream_manager.get_all_status(),
        "total_streaming": sum(
            1 for v in stream_manager.streamers.values() if v
        )
    }