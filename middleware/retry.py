from typing import Callable
from langchain.agents.middleware import wrap_tool_call, ToolCallRequest
from langchain_core.messages import ToolMessage
from errors import TransientToolError, PermanentToolError
import logging
import time

logger=logging.getLogger("agent.tools")

MAX_RETRIES = 3
BACKOFF_BASE_SECONDS=0.5

@wrap_tool_call
def retry_tool(
    request: ToolCallRequest,
    handler: Callable[[ToolCallRequest], ToolMessage],
) -> ToolMessage:
    
    tool_name=request.tool_call.get("name","desconocido")

    for attempt in range(MAX_RETRIES):
        try:
            resultado=handler(request)

            if attempt >0:
                logger.info(f"[{tool_name}] exito en el intento {attempt + 1}")

            return resultado

        except PermanentToolError as e:
            
            logger.warning(f"[{tool_name}] error permanente: {e}")
            return ToolMessage(
                content=f"Error permanente en la herramienta: {e}",
                tool_call_id=request.tool_call["id"],
                status="error",
            )

        except TransientToolError as e:
            
            es_ultimo_intento = attempt == MAX_RETRIES - 1
            logger.warning(
                f"[{tool_name}] error transitorio en intento {attempt + 1}/{MAX_RETRIES}: {e}"
            )

            if es_ultimo_intento:
                logger.error(f"[{tool_name}] agotados los {MAX_RETRIES} reintentos")
                return ToolMessage(
                    content=f"No se pudo ejecutar la herramienta tras {MAX_RETRIES} intentos: {e}",
                    tool_call_id=request.tool_call["id"],
                    status="error",
                )
            time.sleep(BACKOFF_BASE_SECONDS * (2 ** attempt))

        except Exception as e:
            
            logger.exception(f"[{tool_name}] error inesperado no clasificado")
            return ToolMessage(
                content=f"Error inesperado ejecutando la herramienta: {e}",
                tool_call_id=request.tool_call["id"],
                status="error",
            )