from dotenv import load_dotenv
from deepagents import create_deep_agent
from langgraph.types import Command

from tools import ALL_TOOLS
from middleware import ALL_MIDDLEWARE
from config import SYSTEM_PROMPT, checkpointer, INTERRUPT_ON
from logging_config import logger

load_dotenv()


def build_agent():
    return create_deep_agent(
        model="openai:gpt-4o-mini",
        tools=ALL_TOOLS,
        system_prompt=SYSTEM_PROMPT,
        skills=["./skills/"],
        checkpointer=checkpointer,
        interrupt_on=INTERRUPT_ON,
        middleware=ALL_MIDDLEWARE,
    )


if __name__ == "__main__":
    agent = build_agent()

    # El thread_id identifica una conversación específica. Todas las llamadas
    # con el mismo thread_id comparten historial gracias al checkpointer.
    config = {"configurable": {"thread_id": "conversacion-1"}}

    result = agent.invoke(
        {
            "messages": [
                {
                    "role": "user",
                    "content": "Analiza y clasifica bogota y cali usando su clima y poblacion.",
                }
            ]
        },
        config=config,
    )

    print(result["messages"][-1].content)

    # --- Human-in-the-Loop: manejo del interrupt ---------------------------
    if "__interrupt__" in result:
        logger.info("HITL pausa detectada: %s", result["__interrupt__"])

        # Simulamos que un humano revisó la solicitud y la aprueba.
        result = agent.invoke(
            Command(resume={"decisions": [{"type": "approve"}]}),
            config=config,
        )
        print(result["messages"][-1].content)

    # Segunda llamada, MISMO thread_id: el agente debería recordar que ya
    # hablamos de Bogotá y Cali, sin que se lo repitamos.
    result2 = agent.invoke(
        {
            "messages": [
                {"role": "user", "content": "¿de cuáles ciudades te pregunté antes?"}
            ]
        },
        config=config,
    )

    print(result2["messages"][-1].content)
