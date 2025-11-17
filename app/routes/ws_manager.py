from fastapi import WebSocket
import json

class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active_connections.append(ws)

    async def disconnect(self, ws: WebSocket):
        try:
            await ws.close()
        except:
            pass
        if ws in self.active_connections:
            self.active_connections.remove(ws)

    async def broadcast(self, message: dict):
        dead_connections = []
        data = json.dumps(message)

        for ws in self.active_connections:
            try:
                await ws.send_text(data)
            except:
                dead_connections.append(ws)

        # bersihkan koneksi mati
        for ws in dead_connections:
            await self.disconnect(ws)


manager = ConnectionManager()
