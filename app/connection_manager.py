from typing import List
from fastapi import WebSocket

class ConnectionManager:
    def __init__(self):
        # Lista o diccionario para mantener las conexiones WebSocket activas
        self.active_connection:List[WebSocket]=[]

    async def connect(self,websocket:WebSocket):
        # Acepta el handshake del WebSocket
        await websocket.accept()
        self.active_connection.append(websocket)

    def disconnect(self,websocket:WebSocket):
        self.active_connection.remove(websocket)

    async def send_personal_message(self,message:str,websocket:WebSocket):
        await websocket.send_text(message)

    async def broadcast(self,message:str):
        for connection in self.active_connection:
            await connection.send_text(message)