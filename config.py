from langgraph.checkpoint.memory import InMemorySaver

SYSTEM_PROMPT = """
You are a city information assistant.

Rules:
-Always respond in Spanish.
-Be concise.
-Never invent factual information.
-Use tools whenever factual information is required.
-When asked to analyze a city, you MUST call classify_city using its
 population and temperature after retrieving them, before giving your
 final answer.
"""

# Checkpointer: guarda un snapshot del state después de cada paso del grafo,
# indexado por thread_id. En memoria (se pierde al reiniciar el proceso) --
# en producción usarías SqliteSaver, PostgresSaver o similar.
checkpointer = InMemorySaver()

# HITL: pausa la ejecución antes de correr classify_city, esperando
# aprobación humana. Requiere el checkpointer de arriba para persistir el
# state mientras se espera la decisión.
INTERRUPT_ON = {
    "classify_city": {
        "allowed_decisions": ["approve", "edit", "reject"],
        "description": "El agente quiere clasificar la ciudad. ¿Apruebas, editas o rechazas?",
    }
}
