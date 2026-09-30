from langchain.agents.middleware import SummarizationMiddleware

from middleware.routing import SIMPLE_MODEL

# Comprime el historial de forma segura (respeta pares tool_call/tool_result)
# usando un resumen generado por un modelo barato, en vez de cortar mensajes
# a la fuerza como haría una ventana deslizante casera.
context_summarizer = SummarizationMiddleware(
    model=SIMPLE_MODEL,          # el resumen no necesita el modelo caro
    trigger=("messages", 20),    # se activa cuando el historial supera 20 mensajes
    keep=("messages", 6),        # los últimos 6 mensajes se mantienen intactos
)
