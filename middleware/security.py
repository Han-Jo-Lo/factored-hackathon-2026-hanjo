from typing import Callable

from langchain.agents.middleware import wrap_tool_call, ToolCallRequest
from langchain_core.messages import ToolMessage
import logging

logger=logging.getLogger("agent.security")


#from logging_config import logger

# Tools que este agente NUNCA debería ejecutar, sin importar qué diga el
# prompt del usuario o lo que el modelo "decida". Esta es una barrera de
# código -- no depende de que el modelo respete el system_prompt, y por
# tanto no la puede desactivar un prompt injection.
DENIED_TOOLS = {"execute", "write_file", "edit_file"}


@wrap_tool_call
def tool_authorization(
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], ToolMessage],
) -> ToolMessage:
    tool_name = request.tool_call["name"]

    if tool_name in DENIED_TOOLS:
        
        logger.warning(f"[{tool_name}] DENEGADA no autorizado" )
         
        return ToolMessage(
            content=f"Acción no autorizada: '{tool_name}' no está permitida para este agente.",
            tool_call_id=request.tool_call["id"],
            status="error",
        )

    return handler(request)


SUSPICIOUS_PATTERNS = (
    "ignore previous instructions",
    "ignora las instrucciones anteriores",
    "ignore all previous",
    "you are now",
    "eres ahora",
    "system:",
)


@wrap_tool_call
def sanitize_tool_output(
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], ToolMessage],
) -> ToolMessage:
    """Detecta intentos de prompt injection escondidos en resultados de tools.

    Si una tool consulta una fuente externa (ej. una API real de clima),
    esa fuente podría estar comprometida y devolver texto diseñado para
    manipular al modelo cuando el resultado se reinyecta como contexto.
    """
    result = handler(request)
    content = str(result.content).lower()

    if any(pattern in content for pattern in SUSPICIOUS_PATTERNS):
        tool_name = request.tool_call["name"]
        logger.error(f"[{tool_name}] DENEGADA posible prompt injection" )
        return ToolMessage(
            content="[Resultado bloqueado: se detectó un posible intento de manipulación]",
            tool_call_id=request.tool_call["id"],
            status="error",
        )

    return result
