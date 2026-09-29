"""
Contrato de datos del proyecto, calibrado contra el profiling real
(ver conversacion / hallazgos de profile_data.py).

Este archivo define QUE es una fila valida para cada tabla. No limpia
ni transforma nada -- eso lo hace bronze.py / silver.py usando estos
esquemas. Aqui solo se declara el contrato.

Instalar: pip install pandera pandas

Como se usa (adelanto, lo construimos en el siguiente paso):
    from contracts.schemas import CAMPAIGNS_SCHEMA
    CAMPAIGNS_SCHEMA.validate(df, lazy=True)  # lazy=True junta TODOS los
                                                # errores en vez de parar
                                                # en el primero -- clave
                                                # para poder cuarentenar
                                                # filas en vez de fallar
                                                # el batch completo.
"""

import pandas as pd
import pandera.pandas as pa
from pandera.pandas import Column, Check, DataFrameSchema

# ---------------------------------------------------------------------------
# Dominios de valores confirmados con datos reales (no inventados)
# ---------------------------------------------------------------------------
CHANNELS_VALIDOS = ["Email", "SMS", "Push", "WhatsApp", "Voice"]
SEND_STATUS_VALIDOS = ["Sent", "Failed", "Bounced", "Blocked"]
CAMPAIGN_STATUS_VALIDOS = ["Planned", "Active", "Paused", "Completed"]
CAMPAIGN_TYPE_VALIDOS = ["Email", "SMS", "Push", "WhatsApp", "Voice", "Mix"]
CAMPAIGN_OBJECTIVE_VALIDOS = ["Acquisition", "Retention", "Cross-sell", "Up-sell", "Reactivation"]

# Canales que NO soportan tracking de apertura (evidencia real: 100% nulo)
CANALES_SIN_TRACKING_APERTURA = ["Voice", "WhatsApp"]

# Monedas que efectivamente usamos de daily_exchange_rates (solo USD -> local)
MONEDAS_VALIDAS = ["USD", "MXN", "COP", "ARS"]


# ---------------------------------------------------------------------------
# 1) campaigns (dimension)
# ---------------------------------------------------------------------------
# Nulabilidad calibrada con el perfil real: target_country 55.5%, target_segment
# 39.5%, budget 15.5%, etc. -- se declaran nullable=True a proposito, porque
# rechazar esas filas descartaria mas de la mitad de las campanas. El nulo
# se propaga como "no disponible", nunca se imputa.
CAMPAIGNS_SCHEMA = DataFrameSchema(
    {
        "campaign_id": Column(str, unique=True, nullable=False),
        "campaign_name": Column(str, nullable=False),
        "description": Column(str, nullable=True),
        "campaign_type": Column(str, Check.isin(CAMPAIGN_TYPE_VALIDOS), nullable=False),
        "campaign_objective": Column(str, Check.isin(CAMPAIGN_OBJECTIVE_VALIDOS), nullable=False),
        "promoted_product": Column(str, nullable=True),
        "target_segment": Column(str, nullable=True),
        "target_country": Column(str, nullable=True),  # 55.5% nulo real -- confirmado, no es error
        "start_date": Column(pa.DateTime, nullable=False),
        "end_date": Column(pa.DateTime, nullable=False),
        "budget": Column(float, Check.ge(0), nullable=True),  # 15.5% nulo real
        "campaign_status": Column(str, Check.isin(CAMPAIGN_STATUS_VALIDOS), nullable=False),
        "expected_conversion_rate": Column(float, Check.in_range(0, 100), nullable=True),
    },
    strict=False,  # no rechaza columnas extra que no conocemos todavia
    coerce=True,   # intenta convertir tipos (ej. texto de fecha -> datetime)
)


# ---------------------------------------------------------------------------
# 2) daily_exchange_rates (referencia)
# ---------------------------------------------------------------------------
# Evidencia real: 0% nulos, 0 huecos de fecha, PK (date, source, target) unica.
# pandera no valida PK compuesta nativamente -- se verifica aparte con un
# chequeo de duplicados sobre esas 3 columnas (funcion abajo).
FX_SCHEMA = DataFrameSchema(
    {
        "date": Column(pa.DateTime, nullable=False),
        "source_currency": Column(str, Check.isin(MONEDAS_VALIDAS), nullable=False),
        "target_currency": Column(str, Check.isin(MONEDAS_VALIDAS), nullable=False),
        "exchange_rate": Column(float, Check.gt(0), nullable=False),
        "buy_rate": Column(float, Check.gt(0), nullable=True),
        "sell_rate": Column(float, Check.gt(0), nullable=True),
        "source": Column(str, nullable=True),
    },
    strict=False,
    coerce=True,
)


def check_fx_pk_unica(df) -> bool:
    """PK compuesta (date, source_currency, target_currency) no debe duplicarse."""
    dups = df.duplicated(subset=["date", "source_currency", "target_currency"]).sum()
    return dups == 0


# ---------------------------------------------------------------------------
# 3) campaign_sends (hecho, particionado por process_date)
# ---------------------------------------------------------------------------
# Nulabilidad calibrada con el perfil real:
#   - conversion_date/conversion_value: ~99.4% nulo -- ESTRUCTURAL (solo
#     quien convierte tiene fecha/valor de conversion). No es error.
#   - click_date/click_count: ~94.4% nulo -- estructural (solo quien hizo clic).
#   - send_cost: 15% nulo -- esto SI es un hueco real (decision: se excluye
#     del calculo de costo, nunca se imputa -- ver check_send_cost_cobertura).
#   - was_opened: booleano de 3 estados -- ver check_was_opened_estructural.
SENDS_SCHEMA = DataFrameSchema(
    {
        "send_id": Column(str, unique=True, nullable=False),
        "send_date": Column(pa.DateTime, nullable=False),
        "process_date": Column(pa.DateTime, nullable=False),
        "campaign_id": Column(str, nullable=False),  # FK: se valida aparte contra campaigns
        "customer_id": Column(str, nullable=True),   # confirmado: hay nulos reales, pequenos
        "send_channel": Column(str, Check.isin(CHANNELS_VALIDOS), nullable=False),
        "template_used": Column(str, nullable=True),
        "subject": Column(str, nullable=True),
        "send_status": Column(str, Check.isin(SEND_STATUS_VALIDOS), nullable=False),
        "was_delivered": Column(bool, nullable=False),
        "was_opened": Column(object, nullable=True),  # bool de 3 estados -- ver check aparte
        "open_date": Column(pa.DateTime, nullable=True),
        "was_clicked": Column(bool, nullable=False),
        "click_date": Column(pa.DateTime, nullable=True),
        "click_count": Column(float, Check.ge(1), nullable=True),  # nullable int-like
        "had_conversion": Column(bool, nullable=False),
        "conversion_date": Column(pa.DateTime, nullable=True),
        "conversion_value": Column(float, Check.gt(0), nullable=True),
        "open_device": Column(str, nullable=True),
        "open_country": Column(str, nullable=True),
        "failure_reason": Column(str, nullable=True),
        "send_cost": Column(float, Check.ge(0), nullable=True),  # 15% nulo real, no imputar
    },
    strict=False,
    coerce=True,
)


def check_was_opened_estructural(df) -> pd.DataFrame:
    """
    Devuelve las filas donde was_opened NO es nulo pero deberia serlo
    (canal sin tracking de apertura, o mensaje no entregado). Estas filas
    son sospechosas -- alguien reporto una apertura para algo que, segun
    la regla de negocio confirmada, no puede tener ese dato.
    Un resultado vacio es lo esperado; filas aqui van a cuarentena.
    """
    canal_sin_tracking = df["send_channel"].isin(CANALES_SIN_TRACKING_APERTURA)
    no_entregado = ~df["was_delivered"]
    deberia_ser_nulo = canal_sin_tracking | no_entregado
    viola_regla = deberia_ser_nulo & df["was_opened"].notna()
    return df[viola_regla]


def check_send_cost_cobertura(df) -> float:
    """
    No es un check de rechazo -- es una metrica que se debe reportar
    SIEMPRE junto a cualquier calculo de costo/ROI (decision confirmada:
    opcion A, nunca imputar send_cost faltante).
    """
    return df["send_cost"].notna().mean()


def check_orphan_campaign_ids(df_sends, df_campaigns) -> pd.DataFrame:
    """
    FK logica hacia campaigns (pandera no valida FK entre tablas).
    Evidencia real: 0% huerfanas -- si esto deja de dar vacio, es una
    alerta real de integridad, no un caso esperado.
    """
    huerfanas = ~df_sends["campaign_id"].isin(df_campaigns["campaign_id"])
    return df_sends[huerfanas]