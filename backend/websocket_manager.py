# backend/websocket_manager.py
from typing import List
from fastapi import WebSocket

conexoes_ativas: List[WebSocket] = []
