from typing import Callable

from langchain.chat_models import init_chat_model
from langchain.agents.middleware import wrap_model_call, ModelRequest, ModelResponse



SIMPLE_MODEL = init_chat_model("openai:gpt-4o-mini")
COMPLEX_MODEL = init_chat_model("openai:gpt-4o")
FALLBACK_MODEL = init_chat_model("openai:gpt-4o-mini")  # más barato y disponible casi siempre


@wrap_model_call
def model_fallback(
    request: ModelRequest,
    handler: Callable[[ModelRequest], ModelResponse],
) -> ModelResponse:
    """Si el modelo elegido falla, reintenta UNA vez con un modelo de respaldo."""

    try:
        return handler(request)
    except Exception as e:
        
        return handler(request.override(model=FALLBACK_MODEL))
