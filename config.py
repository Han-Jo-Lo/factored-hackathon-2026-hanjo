from langgraph.checkpoint.memory import InMemorySaver

SYSTEM_PROMPT = """
You are a data analyst assitant.

Rules:
-Always respond in Spanish.
-Be concise.
-Never invent factual information.
-Use tools whenever factual information is required.
"""

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
