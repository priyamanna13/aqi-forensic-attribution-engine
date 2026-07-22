"""WebSocket connection manager for live spike push notifications."""
from __future__ import annotations

import asyncio
import logging
from typing import Any
from fastapi import WebSocket, WebSocketDisconnect

log = logging.getLogger("api.ws")


class ConnectionManager:
    def __init__(self):
        self.active_connections: list[WebSocket] = []

    async def connect(self, websocket: WebSocket):
        await websocket.accept()
        self.active_connections.append(websocket)
        log.info(f"WebSocket client connected. Total clients: {len(self.active_connections)}")

    def disconnect(self, websocket: WebSocket):
        if websocket in self.active_connections:
            self.active_connections.remove(websocket)
            log.info(f"WebSocket client disconnected. Total clients: {len(self.active_connections)}")

    async def broadcast(self, message: dict[str, Any]):
        """Push a spike payload to all connected clients."""
        if not self.active_connections:
            return
        log.info(f"Broadcasting message to {len(self.active_connections)} connected WebSocket clients...")
        for connection in list(self.active_connections):
            try:
                await connection.send_json(message)
            except Exception as exc:
                log.warning(f"Failed to send to WebSocket client: {exc}")
                self.disconnect(connection)

    def broadcast_sync(self, message: dict[str, Any]):
        """Thread-safe synchronous wrapper to broadcast from background threads or sync endpoints."""
        if not self.active_connections:
            return
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.broadcast(message))
            else:
                loop.run_until_complete(self.broadcast(message))
        except RuntimeError:
            new_loop = asyncio.new_event_loop()
            try:
                new_loop.run_until_complete(self.broadcast(message))
            finally:
                new_loop.close()


manager = ConnectionManager()
