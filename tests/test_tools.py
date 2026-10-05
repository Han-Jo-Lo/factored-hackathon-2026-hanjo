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
from pydantic import ValidationError
from tools.agent_tools import campaign_performance_tool
from tools.queries import ConsultaAtribucionInput, Metrica, Orden, _build_query



def test_sql_tool_with_valid_result(monkeypatch):
    df_falso=pd.DataFrame({"campaign_id":["CMP0032"],"roi":[3.2]})
    monkeypatch.setattr("tools.agent_tools.query_campaign_performance",lambda params:df_falso)

    resultado=campaign_performance_tool.invoke({"send_channels":["Email"]})

    assert "CMP0032" in resultado
    assert "registro 1:" in resultado
    assert "| campaign_id |" not in resultado

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


def test_sql_tool_returns_all_rows_as_records_not_markdown(monkeypatch):
    df_falso = pd.DataFrame({
        "campaign_id": ["CMP0032", "CMP0001"],
        "roi": [3.2, 0.4],
        "segmento": ["retail", "pyme"],
    })
    monkeypatch.setattr("tools.agent_tools.query_campaign_performance", lambda params: df_falso)

    resultado = campaign_performance_tool.invoke({"send_channels": ["Email"]})
    assert "registro 1:" in resultado
    assert "registro 2:" in resultado
    assert "CMP0001" in resultado
    assert "segmento" in resultado
    assert "pyme" in resultado
    assert "|---" not in resultado


def test_build_query_viewer_role_caps_sql():
    params = ConsultaAtribucionInput(
        limite=50,
        metricas=[Metrica.roi, Metrica.costo_total_usd],
        orden=Orden.valor_desc,
    )
    sql, _ = _build_query(params, role="marketing_viewer")
    assert "LIMIT 10" in sql
    assert "AS costo_total_usd" not in sql
    assert " AS roi" in sql
    assert "valor_creditado_usd DESC" not in sql

