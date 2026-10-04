from redis import Redis
from langgraph.checkpoint.redis import RedisSaver
from redisvl.exceptions import RedisSearchError
from dotenv import load_dotenv
from requests import request
load_dotenv()
import os

REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))

REDIS_BROKER=f'redis://{REDIS_HOST}:{REDIS_PORT}/0'
REDIS_BACKEND=f'redis://{REDIS_HOST}:{REDIS_PORT}/0'

r=Redis(host=REDIS_HOST,port=REDIS_PORT,decode_responses=True)

SYSTEM_PROMPT = """
You are a data analyst assistant.

Rules:
-Always respond in Spanish.
-Be concise.
-Never invent factual information.
-Use tools whenever factual information is required.
"""

def get_redis_saver()->RedisSaver:
    cliente=Redis(host=REDIS_HOST, port=REDIS_PORT, db=0)
    memory_saver=RedisSaver(redis_client=cliente)
    try:
        memory_saver.setup()
    except RedisSearchError as e:
        if "already exists" not in str(e).lower():
            raise
    return memory_saver

COBERTURA_MINIMA_HITL=70.0

def cobertura_requiere_aprobacion(request)->bool:
    args=request.tool_call.get("args") or {}
    raw=args.get("cobertura_minima",COBERTURA_MINIMA_HITL)
    try:
        umbral=float(raw)
    except (TypeError,ValueError):
        return False
    return umbral<COBERTURA_MINIMA_HITL

INTERRUPT_ON = {
    "consultar_desempeno_campanas":{
        "allowed_decisions": ["approve", "reject"],
        "description":(
            "Consulta con cobertura_minima por debajo de 70. "
            "El ROI puede estar sesgado. ¿Apruebas o rechazas?"
        ),
        "when":cobertura_requiere_aprobacion
    }
}
