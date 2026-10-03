from config import r,get_redis_saver,SYSTEM_PROMPT,INTERRUPT_ON
from celery_app import app_celery
from langchain.messages import HumanMessage
import json
from deepagents import create_deep_agent
from tools import ALL_TOOLS
from middleware import ALL_MIDDLEWARE

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
        #interrupt_on=INTERRUPT_ON,
        middleware=ALL_MIDDLEWARE,
    )





@app_celery.task()
def ejecutar_agente(thread_id: str, user_id: str, role: str, message: str):
    agent = build_agent()

    config = {
        "configurable": {
            "thread_id": thread_id,
            "user_id": user_id,
            "role": role,
        }
    }

    response = agent.invoke(
        {"messages": [HumanMessage(content=message)]},
        config=config,
    )

    payload = {
        "status": "completed",
        "tipo": "texto",
        "response_text": f"{response['messages'][-1].content}",
    }
    r.publish(f"canal:{thread_id}", json.dumps(payload))
    

