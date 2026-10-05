from langchain_core.tools import StructuredTool
from tools.queries import ConsultaAtribucionInput, query_campaign_performance
from pydantic import ValidationError
from errors import ToolValidationError
import json
import pandas as pd


def _valor_serializable(valor):
    if valor is None:
        return None
    try:
        if pd.isna(valor):
            return None
    except (TypeError, ValueError):
        pass
    if hasattr(valor, "item"):
        try:
            valor = valor.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(valor, float):
        return round(valor, 4)
    return valor


def _registro(fila: pd.Series) -> dict:
    return {col: _valor_serializable(fila[col]) for col in fila.index}


def _formatear_resultado(df: pd.DataFrame) -> str:

    if len(df) == 0:
        return (
            "La consulta no devolvio resultados. Esto puede significar que "
            "no hay datos para esos filtros, o que el umbral de "
            "cobertura_minima excluyo todas las filas candidatas -- "
            "considera informar esto al usuario en vez de asumir que no "
            "hay actividad en absoluto."
        )

    columnas = list(df.columns)
    lineas = [
        f"Hechos de la consulta: {len(df)} registro(s). "
        f"Campos: {', '.join(columnas)}.",
        "Son observaciones para narrar un hallazgo. "
        "No las conviertas en tabla markdown ni en un inventario completo "
        "salvo que el usuario pida los datos o el desglose.",
    ]
    for i, (_, fila) in enumerate(df.iterrows(), start=1):
        payload = json.dumps(_registro(fila), ensure_ascii=False, default=str)
        lineas.append(f"registro {i}: {payload}")
    return "\n".join(lineas)


def _exec_query_campaign_performance(**kwargs) -> str:
    try:
        params = ConsultaAtribucionInput(**kwargs)
        return _formatear_resultado(query_campaign_performance(params))
    except ValidationError as exc:
        raise ToolValidationError(f"Entrada invalida: {exc.errors()}") from exc


campaign_performance_tool = StructuredTool.from_function(
    func=_exec_query_campaign_performance,
    name="consultar_desempeno_campanas",
    description=(
        "Consulta metricas de desempeno de campanas de marketing: ROI, "
        "conversiones reales, conversiones atribuidas por canal, costo. "
        "Devuelve todos los registros de la consulta como hechos (JSON por fila), "
        "no como tabla. Narra con cifras puntuales; no copies el listado. "
        "Si piden datos o desglose, ahi si puedes tabular esos mismos hechos. "
        "NO uses esto para: tasa de apertura o clic (no disponibles), "
        "moneda local, segmento de cliente, o nivel de detalle diario "
        "(no existen esas columnas en esta fuente)."
    ),
    args_schema=ConsultaAtribucionInput,
)
