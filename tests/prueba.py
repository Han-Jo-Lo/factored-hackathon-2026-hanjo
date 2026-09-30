"""
Pruebas manuales del tool antes de conectarlo a un agente real.
Corre: python test_agent_tools.py
"""

import json

from tools.agent_tools import campaign_performance_tool

# ---------------------------------------------------------------------------
# 1) Invocacion normal -- .invoke() con un diccionario es EXACTAMENTE como
#    un agente real llama al tool (no llames a la funcion de Python
#    directo, porque te saltarias la validacion de Pydantic que pasa por
#    el mismo camino que seguiria el LLM).
# ---------------------------------------------------------------------------
print("=== Caso normal ===")
resultado = campaign_performance_tool.invoke({
    "send_channels": ["WhatsApp"],
    "mes_inicio": "2026-01",
    "mes_fin": "2026-03",
    "agrupar_por": ["campaign_id", "campaign_name"],
    "metricas": ["roi", "conversiones_reales", "pct_cobertura_costo"],
    "cobertura_minima": 70,
    "orden": "roi_desc",
    "limite": 5,
})
print(resultado)

# ---------------------------------------------------------------------------
# 2) Caso limite: un filtro que no deberia matchear ninguna fila --
#    confirma que _formatear_resultado() avisa claro, no devuelve una
#    tabla vacia ambigua.
# ---------------------------------------------------------------------------
print("\n=== Caso sin resultados ===")
print(campaign_performance_tool.invoke({"campaign_ids": ["CMP9999"]}))

# ---------------------------------------------------------------------------
# 3) Caso de validacion: un valor fuera del Enum debe rechazarse ANTES de
#    tocar la base de datos -- esto prueba que la proteccion de Pydantic
#    funciona de verdad, no solo en teoria.
# ---------------------------------------------------------------------------
print("\n=== Caso de validacion (deberia fallar limpio) ===")
try:
    campaign_performance_tool.invoke({"send_channels": ["Telegram"]})
except Exception as e:
    print(f"Rechazado correctamente: {type(e).__name__}: {e}")

# ---------------------------------------------------------------------------
# 4) Lo que el LLM realmente ve de este tool -- util para depurar si el
#    agente "no entiende" cuando usarlo: revisa si la descripcion es clara
#    y si el esquema de argumentos se ve como esperas.
# ---------------------------------------------------------------------------
print("\n=== Lo que el LLM ve de este tool ===")
print("name:", campaign_performance_tool.name)
print("description:", campaign_performance_tool.description)
print("args (JSON Schema):")
print(json.dumps(campaign_performance_tool.args, indent=2, ensure_ascii=False))