from typing import Callable

from langchain.chat_models import init_chat_model
from langchain.agents.middleware import wrap_model_call, ModelRequest, ModelResponse



SIMPLE_MODEL = init_chat_model("openai:gpt-4o-mini")
COMPLEX_MODEL = init_chat_model("openai:gpt-4o")
FALLBACK_MODEL = init_chat_model("openai:gpt-4o-mini")  # más barato y disponible casi siempre

# Palabras clave que sugieren razonamiento multi-paso o comparación.
COMPLEXITY_KEYWORDS = (
    "compara", "compare", "analiza", "analyze", "analize",
    "clasifica", "classify", "varias", "múltiples", "diferencia",
)

KNOWN_CITIES = ("bogota", "bogotá", "cali", "medellin", "medellín", "barranquilla")


def _is_complex(text: str) -> bool:
    text = text.lower()

    # Señal 1: menciona más de una ciudad conocida -> comparación.
    cities_mentioned = sum(1 for city in KNOWN_CITIES if city in text)
    if cities_mentioned >= 2:
        return True

    # Señal 2: usa lenguaje de análisis/comparación.
    if any(keyword in text for keyword in COMPLEXITY_KEYWORDS):
        return True

    return False


@wrap_model_call
def dynamic_model_router(
    request: ModelRequest,
    handler: Callable[[ModelRequest], ModelResponse],
) -> ModelResponse:
    """Elige el modelo según la complejidad del último mensaje del usuario."""

    messages = request.state["messages"]
    last_user_text = ""
    for message in reversed(messages):
        role = getattr(message, "type", None) or message.get("role")
        if role in ("human", "user"):
            content = getattr(message, "content", None) or message.get("content", "")
            last_user_text = content
            break

    chosen_model = COMPLEX_MODEL if _is_complex(last_user_text) else SIMPLE_MODEL
   

    return handler(request.override(model=chosen_model))


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
