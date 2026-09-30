from langchain_core.tools import StructuredTool
from tools.queries import ConsultaAtribucionInput, query_campaign_performance
from pydantic import ValidationError
from errors import ToolValidationError


def _formatear_resultado(df) -> str:

    if len(df) == 0:
        return (
            "La consulta no devolvio resultados. Esto puede significar que "
            "no hay datos para esos filtros, o que el umbral de "
            "cobertura_minima excluyo todas las filas candidatas -- "
            "considera informar esto al usuario en vez de asumir que no "
            "hay actividad en absoluto."
        )
    encabezado = f"Resultado: {len(df)} fila(s).\n\n"
    return encabezado + df.to_markdown(index=False)

def _exec_query_campaign_performance(**kwargs) -> str:
    try:
        return _formatear_resultado(query_campaign_performance(ConsultaAtribucionInput(**kwargs)))
    except ValidationError as exc:
        raise ToolValidationError(f"Entrada invalida: {exc.errors()}") from exc


campaign_performance_tool = StructuredTool.from_function(
    func=_exec_query_campaign_performance,
    name="consultar_desempeno_campanas",
    description=(
        "Consulta metricas de desempeno de campanas de marketing: ROI, "
        "conversiones reales, conversiones atribuidas por canal, costo. "
        "Usa esto para preguntas sobre efectividad de campanas o "
        "atribucion de canal. Los datos estan en USD y a nivel mensual. "
        "NO uses esto para: tasa de apertura o clic (no disponibles), "
        "moneda local, segmento de cliente, o nivel de detalle diario "
        "(no existen esas columnas en esta fuente)."
    ),
    args_schema=ConsultaAtribucionInput,
)


