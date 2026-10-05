"""
Entrada estructurada para el tool del agente sobre campaign_channel_performance.
 
Principio de diseno (punto 3 del framework -- permisos y politicas FUERA
del texto generado por el modelo): el LLM nunca escribe SQL. Solo llena
este formulario validado por Pydantic; este archivo es el UNICO lugar
que traduce esos campos a una consulta real. Los nombres de columna y
valores de filtro nunca se concatenan como texto libre proveniente del
LLM -- se usan listas cerradas (Enum) o parametros ligados (?).
 
Requiere: pip install pydantic duckdb pandas
"""
 
import re
from enum import Enum
from typing import Optional
 
import duckdb
import pandas as pd
from pydantic import BaseModel, Field, field_validator,ConfigDict

from app.auth import apply_role_ceiling_to_args
 
GOLD_TABLE_PATH = "data/gold/campaign_channel_performance.parquet"
 
 
# ---------------------------------------------------------------------------
# Enums: listas cerradas -- el LLM elige ENTRE estas opciones, nunca escribe
# un nombre de columna o valor libremente.
# ---------------------------------------------------------------------------
class Canal(str, Enum):
    email = "Email"
    sms = "SMS"
    push = "Push"
    whatsapp = "WhatsApp"
    voice = "Voice"
 
 
class DimensionAgrupacion(str, Enum):
    campaign_id = "campaign_id"
    campaign_name = "campaign_name"
    send_channel = "send_channel"
    mes = "mes"
 
 
class Metrica(str, Enum):
    total_enviados = "total_enviados"
    conversiones_reales = "conversiones_reales"
    conversiones_creditadas = "conversiones_creditadas"
    valor_creditado_usd = "valor_creditado_usd"
    costo_total_usd = "costo_total_usd"
    roi = "roi"
    pct_cobertura_costo = "pct_cobertura_costo"
 
 
class Orden(str, Enum):
    roi_desc = "roi_desc"
    roi_asc = "roi_asc"
    valor_desc = "valor_desc"
    conversiones_desc = "conversiones_desc"
    sin_orden = "sin_orden"
 
 
# ---------------------------------------------------------------------------
# El formulario estructurado que el LLM llena
# ---------------------------------------------------------------------------
class ConsultaAtribucionInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    campaign_ids: Optional[list[str]] = Field(
        default=None,
        description="IDs de campana a filtrar, ej. ['CMP0032']. None = todas las campanas.",
    )
    send_channels: Optional[list[Canal]] = Field(
        default=None,
        description="Canales a filtrar. None = todos los canales.",
    )
    mes_inicio: Optional[str] = Field(
        default=None, description="Mes inicial del rango, formato YYYY-MM."
    )
    mes_fin: Optional[str] = Field(
        default=None, description="Mes final del rango, formato YYYY-MM."
    )
    agrupar_por: list[DimensionAgrupacion] = Field(
        default_factory=lambda: [
            DimensionAgrupacion.campaign_id,
            DimensionAgrupacion.send_channel,
        ],
        description="Dimensiones por las que agregar el resultado.",
    )
    metricas: list[Metrica] = Field(
        default_factory=lambda: [Metrica.roi, Metrica.pct_cobertura_costo, Metrica.conversiones_reales],
        description="Metricas a devolver.",
    )
    cobertura_minima: float = Field(
        default=70.0,
        ge=0, le=100,
        description=(
            "Umbral minimo de pct_cobertura_costo para incluir una fila. "
            "Protege contra mostrar ROI calculado con datos de costo muy incompletos."
        ),
    )
    orden: Orden = Field(default=Orden.sin_orden)
    limite: int = Field(default=20, ge=1, le=50, description="Maximo de filas a devolver (tope duro: 50).")
 
    @field_validator("mes_inicio", "mes_fin")
    @classmethod
    def validar_formato_mes(cls, v):
        if v is not None and not re.fullmatch(r"\d{4}-\d{2}", v):
            raise ValueError("El mes debe tener formato YYYY-MM, ej. '2026-03'.")
        return v
 
 
# ---------------------------------------------------------------------------
# Traduccion de la entrada estructurada a SQL seguro
# ---------------------------------------------------------------------------
def _build_query(params: ConsultaAtribucionInput, role: str | None = None):
    """
    Arma el SQL y sus valores de parametro por separado -- los valores
    de filtro SIEMPRE van ligados via '?', nunca concatenados como texto.
    Los nombres de columna solo salen de los Enums de arriba, jamas de
    un string libre del LLM.
    """
    condiciones = ["pct_cobertura_costo >= ?"]
    valores = [params.cobertura_minima]
 
    if params.campaign_ids:
        placeholders = ",".join(["?"] * len(params.campaign_ids))
        condiciones.append(f"campaign_id IN ({placeholders})")
        valores.extend(params.campaign_ids)
 
    if params.send_channels:
        canales = [c.value for c in params.send_channels]
        placeholders = ",".join(["?"] * len(canales))
        condiciones.append(f"send_channel IN ({placeholders})")
        valores.extend(canales)
 
    if params.mes_inicio:
        condiciones.append("mes >= ?")
        valores.append(params.mes_inicio)
 
    if params.mes_fin:
        condiciones.append("mes <= ?")
        valores.append(params.mes_fin)
 
    where_clause = " AND ".join(condiciones)
    dims = [d.value for d in params.agrupar_por]
    group_by_clause = ", ".join(dims) if dims else "1"

    if role:
        capped = apply_role_ceiling_to_args(
            role,
            {
                "limite": params.limite,
                "metricas": [m.value for m in params.metricas],
                "orden": params.orden.value,
            },
        )
    else:
        capped = {
            "limite": params.limite,
            "metricas": [m.value for m in params.metricas],
            "orden": params.orden.value,
        }
    limite = capped["limite"]
    metricas = capped["metricas"]
    orden = Orden(capped["orden"])
 
    # --- Re-agregacion segura ---
    # roi NUNCA se promedia directo (promediar razones ya calculadas es un
    # error clasico) -- se recalcula como SUM(valor)/SUM(costo) sobre el
    # grupo ya colapsado.
    # pct_cobertura_costo se aproxima con un promedio ponderado por
    # total_enviados -- es una APROXIMACION, no un recalculo exacto, porque
    # esta tabla solo guarda el porcentaje por fila, no el conteo absoluto
    # de envios con costo conocido. Limitacion documentada: si se necesita
    # precision exacta aqui, gold_attribution.py deberia guardar tambien
    # el conteo absoluto (no solo el %) para poder sumarlo sin aproximar.
    select_parts = list(dims)
    metric_exprs = {
        "total_enviados": "SUM(total_enviados) AS total_enviados",
        "conversiones_reales": "SUM(conversiones_reales) AS conversiones_reales",
        "conversiones_creditadas": "SUM(conversiones_creditadas) AS conversiones_creditadas",
        "valor_creditado_usd": "SUM(valor_creditado_usd) AS valor_creditado_usd",
        "costo_total_usd": "SUM(costo_total_usd) AS costo_total_usd",
        "roi": "SUM(valor_creditado_usd) / NULLIF(SUM(costo_total_usd), 0) AS roi",
        "pct_cobertura_costo": (
            "SUM(pct_cobertura_costo * total_enviados) / NULLIF(SUM(total_enviados), 0) "
            "AS pct_cobertura_costo"
        ),
    }
    for m in metricas:
        expr = metric_exprs[m]
        if expr not in select_parts:
            select_parts.append(expr)
 
    orden_map = {
        Orden.roi_desc: "roi DESC",
        Orden.roi_asc: "roi ASC",
        Orden.valor_desc: "valor_creditado_usd DESC",
        Orden.conversiones_desc: "conversiones_reales DESC",
    }
    order_clause = f"ORDER BY {orden_map[orden]}" if orden in orden_map else ""
 
    sql = f"""
        SELECT {", ".join(select_parts)}
        FROM read_parquet(?)
        WHERE {where_clause}
        GROUP BY {group_by_clause}
        {order_clause}
        LIMIT {limite}
    """
    valores_finales = [GOLD_TABLE_PATH] + valores
    return sql, valores_finales
 
 
def query_campaign_performance(
    params: ConsultaAtribucionInput, role: str | None = None
) -> pd.DataFrame:
    """
    Punto de entrada del tool. Recibe el objeto validado por Pydantic y,
    si hay sesion, el rol de configurable (nunca del formulario del LLM).
    """
    sql, valores = _build_query(params, role=role)
    con = duckdb.connect()
    try:
        return con.execute(sql, valores).df()
    finally:
        con.close()
 
