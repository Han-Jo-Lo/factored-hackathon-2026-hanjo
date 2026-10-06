from fastapi import FastAPI,WebSocket,WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from config import REDIS_HOST,REDIS_PORT
from app.connection_manager import ConnectionManager
from worker.tasks import ejecutar_agente,reanudar_agente
from app.auth import resolve_test_session, bind_visitor_thread
import asyncio
import redis.asyncio as aioredis
import json


app = FastAPI()

manager=ConnectionManager()

redis_async=aioredis.Redis(host=REDIS_HOST,port=REDIS_PORT,decode_responses=True)
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"


@app.websocket('/ws/{client_id}')
async def websocket_endpoint(websocket:WebSocket,client_id:str):
    claims = resolve_test_session(client_id)
    if claims is None:
        await websocket.accept()
        await websocket.close(code=4401)
        return

    visitor_id = websocket.query_params.get("vid")
    session = bind_visitor_thread(claims, visitor_id)
    if session is None:
        await websocket.accept()
        await websocket.close(code=4401)
        return

    thread_id = session["thread_id"]
    await manager.connect(websocket)

    # 🌟 FUNCIÓN INTERNA: Escuchador de Redis Pub/Sub
    #async def — declara una función especial
    #Esto le dice a Python: "esta función puede pausarse 
    # y dejar que otras cosas ocurran mientras espera algo".
    async def redis_listener():
        #Crea una suscripción Pub/Sub
        pubsub_client = aioredis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        pubsub = pubsub_client.pubsub()
        canal = f"canal:{thread_id}"
        await pubsub.subscribe(canal)
        try:
            async for message in pubsub.listen():
                if message["type"] == "message":
                    await websocket.send_text(message["data"])
        except Exception as e:
            print(f"Error en Pub/Sub para {thread_id}: {e}")
        finally:
            await pubsub.unsubscribe(canal)
            await pubsub_client.aclose()

    listener_task = asyncio.create_task(redis_listener())

    try:
        while True:
            # Espera a que el cliente envíe un mensaje de texto por el WebSocket
            data=await websocket.receive_text()
            if data== "__ping__":
                await manager.send_personal_message("__pong__",websocket)
                continue

            try:
                cuerpo = json.loads(data)
            except json.JSONDecodeError:
                cuerpo = None


            # 2. Delegamos el procesamiento pesado a Celery de forma asíncrona
            # Esto no congela el hilo y responde de inmediato
            if isinstance(cuerpo, dict) and cuerpo.get("type") == "hitl_decision":
                reanudar_agente.delay(
                    thread_id=session["thread_id"],
                    user_id=session["user_id"],
                    role=session["role"],
                    decision=cuerpo.get("decision"),
                )
            else:
                ejecutar_agente.delay(
                    thread_id=session["thread_id"],
                    user_id=session["user_id"],
                    role=session["role"],
                    message=data,
                )

    except WebSocketDisconnect:
        # 3. Limpiamos la conexión si el usuario cierra el navegador o pierde conexión
        manager.disconnect(websocket)
        # 🛑 CRUCIAL: Cancelamos el escuchador de Redis si el cliente se va
        listener_task.cancel()
        # Opcional: log de desconexión
        print(f"Cliente {thread_id} desconectado.")


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")

