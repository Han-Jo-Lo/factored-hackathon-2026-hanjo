"""
Pruebas unitarias del tool de atribucion.
 
Principio clave: se reemplaza (mock) query_campaign_performance para que
los tests sean rapidos, deterministas, y no dependan de que exista
data/gold/... en disco -- eso es lo que hace que sean pruebas UNITARIAS
(prueban el formateo y la traduccion de errores, no el pipeline completo).
 
IMPORTANTE sobre monkeypatch: se reemplaza "tools.agent_tools.query_campaign_performance"
(donde el nombre se USA y se busca en tiempo de ejecucion), no
"tools.queries.query_campaign_performance" (donde se DEFINE). Parchar el
lugar de definicion no tiene efecto si agent_tools ya importo su propia
referencia con "from tools.queries import query_campaign_performance".
"""
import pandas as pd
import pytest
from tools.agent_tools import campaign_performance_tool
from pydantic import ValidationError



def test_sql_tool_with_valid_result(monkeypatch):
    df_falso=pd.DataFrame({"campaign_id":["CMP0032"],"roi":[3.2]})
    monkeypatch.setattr("tools.agent_tools.query_campaign_performance",lambda params:df_falso)

    resultado=campaign_performance_tool.invoke({"send_channels":["Email"]})

    assert "CMP0032" in resultado

def test_sql_tool_with_pydatinc_validationerror():
    with pytest.raises(ValidationError):
        campaign_performance_tool.invoke({"SEND_CHANNELS":["Telegram"]})

def test_sql_tool_with_pydatinc_wrong_value_error():
    with pytest.raises(ValidationError):
        campaign_performance_tool.invoke({"send_channels":["Telegram"]})

def test_sql_tool_without_result(monkeypatch):
    monkeypatch.setattr("tools.agent_tools.query_campaign_performance", lambda params: pd.DataFrame())
 
    resultado = campaign_performance_tool.invoke({"campaign_ids":["CMP9999"]})
 
    assert "no devolvio resultados" in resultado.lower()
