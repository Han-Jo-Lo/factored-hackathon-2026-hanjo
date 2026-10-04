from config import r,get_redis_saver,SYSTEM_PROMPT,INTERRUPT_ON
from worker.celery_app import app_celery
from langchain.messages import HumanMessage
import json
from deepagents import create_deep_agent
from tools import ALL_TOOLS
from middleware import ALL_MIDDLEWARE
from langgraph.types import Command

_checkpointer = None

def build_agent():
    global _checkpointer
    if _checkpointer is None:
        _checkpointer = get_redis_saver()

    return create_deep_agent(
        model="openai:gpt-4o",
        tools=ALL_TOOLS,
        system_prompt=SYSTEM_PROMPT,
        #skills=["./skills/"],
        checkpointer=_checkpointer,
        interrupt_on=INTERRUPT_ON,
        middleware=ALL_MIDDLEWARE,
    )


def _config(thread_id,user_id,role):
    return{
        "configurable":{
            "thread_id":thread_id,
            "user_id":user_id,
            "role":role
        }
    }

def _publicar(thread_id, payload: dict):
    r.publish(f"canal:{thread_id}", json.dumps(payload, default=str))


def _serializar_interrupt(valor):
    if isinstance(valor, (dict, list, str, int, float, bool)) or valor is None:
        return valor
    if hasattr(valor, "model_dump"):
        return valor.model_dump()
    if hasattr(valor, "dict"):
        return valor.dict()
    return str(valor)


def _payload_si_interrupt(response, user_id, role):
    interrupts = response.get("__interrupt__") or []
    if not interrupts:
        return None
    crudo = interrupts[0]
    valor = crudo.value if hasattr(crudo, "value") else crudo
    return {
        "status": "awaiting_approval",
        "tipo": "hitl",
        "user_id": user_id,
        "role": role,
        "allowed": ["approve", "reject"],
        "interrupt": _serializar_interrupt(valor),
    }


def _texto_final(response) -> str:
    messages = response.get("messages") or []
    if not messages:
        return ""
    contenido = getattr(messages[-1], "content", messages[-1])
    return contenido if isinstance(contenido, str) else str(contenido)


def _publicar_resultado_agente(thread_id, user_id, role, response):
    hitl = _payload_si_interrupt(response, user_id, role)
    if hitl:
        _publicar(thread_id, hitl)
        return
    _publicar(thread_id, {
        "status": "completed",
        "tipo": "texto",
        "response_text": _texto_final(response),
    })


@app_celery.task()
def ejecutar_agente(thread_id: str, user_id: str, role: str, message: str):
    agent = build_agent()
    config = _config(thread_id, user_id, role)
    response = agent.invoke(
        {"messages": [HumanMessage(content=message)]},
        config=config,
    )
    _publicar_resultado_agente(thread_id, user_id, role, response)


@app_celery.task()
def reanudar_agente(thread_id, user_id, role, decision: str):
    if decision not in ("approve", "reject"):
        _publicar(thread_id, {"status": "error", "response_text": "decision invalida"})
        return
    agent = build_agent()
    config = _config(thread_id, user_id, role)
    try:
        response = agent.invoke(
            Command(resume={"decisions": [{"type": decision}]}),
            config=config,
        )
    except Exception as exc:
        _publicar(thread_id, {
            "status": "error",
            "response_text": f"No se pudo reanudar (no habia una pausa HITL o fallo el resume): {exc}",
        })
        return
    _publicar_resultado_agente(thread_id, user_id, role, response)
