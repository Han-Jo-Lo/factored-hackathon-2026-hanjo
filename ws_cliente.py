import asyncio
import websockets

async def main():
    uri = "ws://127.0.0.1:8000/ws/analyst_demo"
    async with websockets.connect(uri) as ws:
        print("Conectado. Escribe un mensaje y Enter.")
        print("Vacio + Enter para salir.\n")

        async def escuchar():
            async for msg in ws:
                print("\n<<", msg, "\n>> ", end="", flush=True)

        tarea = asyncio.create_task(escuchar())
        while True:
            linea = await asyncio.to_thread(input, ">> ")
            if linea == "":
                break
            await ws.send(linea)
        tarea.cancel()

asyncio.run(main())