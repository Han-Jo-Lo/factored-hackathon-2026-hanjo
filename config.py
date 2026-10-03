from redis import Redis
from langgraph.checkpoint.redis import RedisSaver
from redisvl.exceptions import RedisSearchError
from dotenv import load_dotenv
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



# HITL: pausa la ejecución antes de correr classify_city, esperando
# aprobación humana. Requiere el checkpointer de arriba para persistir el
# state mientras se espera la decisión.
INTERRUPT_ON = {
    "classify_city": {
        "allowed_decisions": ["approve", "edit", "reject"],
        "description": "El agente quiere clasificar la ciudad. ¿Apruebas, editas o rechazas?",
    }
}
