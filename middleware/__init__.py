"""
Ensambla la lista final de middleware, EN EL ORDEN CORRECTO.

Por qué este orden importa (ver Ejercicios 8, 11 y 14 del curso):

  observability_model   <- afuera: mide latencia total (routing + fallback)
      dynamic_model_router
          model_fallback
  context_summarizer     <- hook antes del ciclo, no anida con los de arriba

  observability_tool     <- afuera: registra TODO, incluidas denegaciones
      tool_authorization  <- bloquea antes de gastar un retry o tocar el cache
          tool_cache        <- evita ejecutar si ya tenemos el resultado
              retry_tool
                  sanitize_tool_output  <- inspecciona el resultado real

Este módulo es el ÚNICO lugar donde se decide ese orden. main.py no debería
tener que volver a razonarlo -- solo importa ALL_MIDDLEWARE.
"""
#from middleware.observability import observability_model, observability_tool
from middleware.routing import dynamic_model_router, model_fallback
from middleware.summarization import context_summarizer
from middleware.security import tool_authorization, sanitize_tool_output
#from middleware.caching import tool_cache
from middleware.retry import retry_tool

ALL_MIDDLEWARE = [
    #observability_model,
    dynamic_model_router,
    model_fallback,
    context_summarizer,
    #observability_tool,
    tool_authorization,
    #tool_cache,
    retry_tool,
    sanitize_tool_output,
]
