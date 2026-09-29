from enum import Enum
from typing import Optional
import duckdb
import pandas as pd
from pydantic import BaseModel,Field,field_validator

GOLD_TABLE_PATH = "data/gold/campaign_channel_performance.parquet"

class Canal(str,Enum):
    email="Email"
    sms="SMS"
    push="Push"
    whatsapp="WhatsApp"
    voice="Voice"

class DimensionAgrupacion(str,Enum):
    campaign_id="campaign_id"
    campaig_name="campaign_name"
    send_channel="send_channel"
    mes="mes"

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

class ConsultaAtribucionInput(BaseModel):
    campaigns_id:Optional[list[str]]=Field(
        default=None,
        description="IDs de campana a filtrar, ej. ['CMP0032']. None = todas las campanas."
    )
    send_channel:Optional[list[Canal]]=Field(
        default=None,
        description="Canales a filtrar. None = todos los canales."
    )
    mes_inicio:Optional[str]=Field(
        None,
        description="Mes inicial del rango, formato YYYY-MM."
    )
    mes_fin:Optional[str]=Field(
        None,
        description="Mes final del rango, formato YYYY-MM."
    )
    agrupar_por:list[DimensionAgrupacion]=Field(
        default_factory=lambda:[DimensionAgrupacion.campaig_name,DimensionAgrupacion.send_channel],
        description="Dimensiones por las que agregar el resultado"
    )
    metricas:list[Metrica]=Field(
        default_factory=lambda:[Metrica.roi,Metrica.pct_cobertura_costo,Metrica.conversiones_reales],
        description="Metricas a devolver"
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
