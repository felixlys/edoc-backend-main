from fastapi import APIRouter, WebSocket
from app.utils.ws_manager import manager
import asyncio

router = APIRouter()

@router.websocket("/ws/unread")
async def websocket_unread(ws: WebSocket):
    await manager.connect(ws)

    try:
        while True:
            # Terima ping dari client (tiap 10 detik)
            try:
                msg = await asyncio.wait_for(ws.receive_text(), timeout=40)
            except asyncio.TimeoutError:
                # jika client tidak kirim apa² → kirim ping
                await ws.send_text("ping")
                continue

            # Jika menerima ping → balas pong
            if msg == "ping":
                await ws.send_text("pong")

    except Exception:
        await manager.disconnect(ws)


