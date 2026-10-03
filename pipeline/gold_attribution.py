"""
Construye las 2 tablas Gold de atribucion:

  1) attribution_scores: 1 fila por (touch, conversion a la que aporta
     credito). Usa la regla BASELINE last-touch (100% del credito al
     touch mas reciente dentro de la ventana de 7 dias antes de la
     conversion). Cuando exista train_model.py, este script se correra
     de nuevo con metodo_atribucion="modelo_logistico_v1" -- el resto
     del sistema (tabla 2, agente) no cambia de forma.

  2) campaign_channel_performance: agregado por campaign_id x canal x
     mes, listo para que el agente lo consulte via SQL. Incluye ROI,
     con su % de cobertura de costo siempre al lado (nunca se imputa
     send_cost faltante -- decision confirmada).

Lee de: data/silver/
Escribe en: data/gold/

Requiere: pip install pandas pyarrow numpy
"""

import glob
import json
import logging
import os
from datetime import datetime, timezone

import numpy as np
import pandas as pd

# ---------------------------------------------------------------------------
SILVER_DIR = "data/silver"
GOLD_DIR = "data/gold"
LINEAGE_PATH = os.path.join(GOLD_DIR, "_lineage", "manifest.jsonl")

ATTRIBUTION_WINDOW_DAYS = 10  # misma ventana confirmada para la tabla de entrenamiento
METODO_ATRIBUCION = "baseline_last_touch"
MODEL_VERSION = "baseline_v1"

COLUMNAS_SENDS = [
    "send_id", "customer_id", "campaign_id", "send_channel",
    "send_date", "process_date",
    "had_conversion", "conversion_date", "conversion_value", "send_cost",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("gold_attribution_run.log")],
)
logger = logging.getLogger("gold_attribution")


def _write_lineage(record: dict):
    os.makedirs(os.path.dirname(LINEAGE_PATH), exist_ok=True)
    record["processed_at"] = datetime.now(timezone.utc).isoformat()
    with open(LINEAGE_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


# ---------------------------------------------------------------------------
def load_silver_sends() -> pd.DataFrame:
    pattern = os.path.join(SILVER_DIR, "campaign_sends", "process_date=*", "data.parquet")
    files = sorted(glob.glob(pattern))
    logger.info(f"Cargando {len(files)} particiones de Silver")
    partes = [pd.read_parquet(f, columns=COLUMNAS_SENDS) for f in files]
    df = pd.concat(partes, ignore_index=True)
    logger.info(f"Total cargado: {len(df):,} filas")
    return df


def load_campaign_names() -> pd.DataFrame:
    df = pd.read_parquet(os.path.join(SILVER_DIR, "campaigns.parquet"),
                          columns=["campaign_id", "campaign_name"])
    return df


# ---------------------------------------------------------------------------
# 1) attribution_scores: reparte credito con la regla baseline last-touch
# ---------------------------------------------------------------------------
def build_attribution_scores(df: pd.DataFrame):
    n_total = len(df)

    # No se puede atribuir sin identidad de cliente -- se excluye, contado.
    df_con_cliente = df.dropna(subset=["customer_id"]).copy()
    n_sin_cliente = n_total - len(df_con_cliente)
    logger.info(f"Touches sin customer_id excluidos de atribucion: {n_sin_cliente}")

    # --- Anclas: una fila por conversion real ---
    anchors = (
        df_con_cliente.loc[df_con_cliente["had_conversion"],
                            ["customer_id", "send_id", "conversion_date", "conversion_value"]]
        .dropna(subset=["conversion_date"])
        .rename(columns={"send_id": "conversion_send_id"})
    )
    logger.info(f"Conversiones (anclas) encontradas: {len(anchors):,}")

    touches = df_con_cliente[
        ["customer_id", "send_id", "send_date", "campaign_id", "send_channel"]
    ]

    # --- Cruce por cliente (acotado: solo clientes que convirtieron aportan
    # filas al cruce, la mayoria de clientes nunca aparece aqui) ---
    pares = touches.merge(anchors, on="customer_id", how="inner")

    ventana_inicio = pares["conversion_date"] - pd.Timedelta(days=ATTRIBUTION_WINDOW_DAYS)
    dentro_de_ventana = (
        (pares["send_date"] >= ventana_inicio) & (pares["send_date"] <= pares["conversion_date"])
    )
    pares = pares[dentro_de_ventana].copy()
    logger.info(f"Pares (touch, conversion) dentro de la ventana de {ATTRIBUTION_WINDOW_DAYS} dias: "
                f"{len(pares):,}")

    # --- Regla baseline: 100% del credito al touch MAS RECIENTE de cada
    # grupo de conversion. Empate (2 touches con el mismo send_date exacto):
    # idxmax() se queda con el primero encontrado -- supuesto documentado,
    # ajustable si el negocio prefiere repartir el credito entre empatados.
    pares["credito_atribuido"] = 0.0
    idx_ultimo_touch = pares.groupby("conversion_send_id")["send_date"].idxmax()
    pares.loc[idx_ultimo_touch, "credito_atribuido"] = 1.0

    pares["metodo_atribucion"] = METODO_ATRIBUCION
    pares["model_version"] = MODEL_VERSION
    pares["scored_at"] = datetime.now(timezone.utc)

    columnas_finales = [
        "send_id", "conversion_send_id", "customer_id", "campaign_id", "send_channel",
        "conversion_value", "credito_atribuido",
        "metodo_atribucion", "model_version", "scored_at",
    ]
    return pares[columnas_finales], n_sin_cliente


# ---------------------------------------------------------------------------
# 2) campaign_channel_performance: agregado listo para el agente
# ---------------------------------------------------------------------------
def build_campaign_channel_performance(
    df_sends: pd.DataFrame, df_scores: pd.DataFrame, df_campaigns: pd.DataFrame
) -> pd.DataFrame:
    df_sends = df_sends.copy()
    df_sends["mes"] = df_sends["send_date"].dt.to_period("M").astype(str)

    # --- Metricas de embudo: sobre TODA la poblacion (no requieren cliente) ---
    funnel = df_sends.groupby(["campaign_id", "send_channel", "mes"]).agg(
        total_enviados=("send_id", "count"),
        conversiones_reales=("had_conversion", "sum"),
        costo_total_usd=("send_cost", "sum"),
        pct_cobertura_costo=("send_cost", lambda s: s.notna().mean() * 100),
    ).reset_index()

    # --- Credito atribuido: SOLO sobre los touches que participaron en
    # algun grupo de conversion (la mayoria de touches no aportan credito). ---
    fechas_touch = df_sends[["send_id", "send_date"]].drop_duplicates("send_id")
    df_scores = df_scores.merge(fechas_touch, on="send_id", how="left")
    df_scores["mes"] = df_scores["send_date"].dt.to_period("M").astype(str)

    df_scores["valor_creditado_usd"] = df_scores["credito_atribuido"] * df_scores["conversion_value"]

    credito_agg = df_scores.groupby(["campaign_id", "send_channel", "mes"]).agg(
        conversiones_creditadas=("credito_atribuido", "sum"),
        valor_creditado_usd=("valor_creditado_usd", "sum"),
    ).reset_index()

    # --- Union de ambos agregados ---
    perf = funnel.merge(credito_agg, on=["campaign_id", "send_channel", "mes"], how="left")
    perf["conversiones_creditadas"] = perf["conversiones_creditadas"].fillna(0.0)
    perf["valor_creditado_usd"] = perf["valor_creditado_usd"].fillna(0.0)

    # --- ROI: nulo si no hay costo conocido, nunca inf ---
    perf["roi"] = np.where(
        perf["costo_total_usd"] > 0,
        perf["valor_creditado_usd"] / perf["costo_total_usd"],
        np.nan,
    )

    perf["metodo_atribucion_usado"] = METODO_ATRIBUCION

    perf = perf.merge(df_campaigns, on="campaign_id", how="left")

    columnas_finales = [
        "campaign_id", "campaign_name", "send_channel", "mes",
        "total_enviados", "conversiones_reales",
        "conversiones_creditadas", "valor_creditado_usd",
        "costo_total_usd", "pct_cobertura_costo", "roi",
        "metodo_atribucion_usado",
    ]
    return perf[columnas_finales]


# ---------------------------------------------------------------------------
def main():
    logger.info("=== Inicio corrida gold_attribution ===")

    df_sends = load_silver_sends()
    df_campaigns = load_campaign_names()

    df_scores, n_sin_cliente = build_attribution_scores(df_sends)
    df_perf = build_campaign_channel_performance(df_sends, df_scores, df_campaigns)

    os.makedirs(GOLD_DIR, exist_ok=True)
    df_scores.to_parquet(os.path.join(GOLD_DIR, "attribution_scores.parquet"), index=False)
    df_perf.to_parquet(os.path.join(GOLD_DIR, "campaign_channel_performance.parquet"), index=False)

    logger.info(f"attribution_scores: {len(df_scores):,} filas escritas")
    logger.info(f"campaign_channel_performance: {len(df_perf):,} filas escritas")
    logger.info(f"ROI no calculable (sin costo conocido): {df_perf['roi'].isna().sum()} de {len(df_perf)} filas")

    _write_lineage({
        "table": "attribution_scores",
        "n_rows": len(df_scores),
        "n_touches_sin_customer_id_excluidos": int(n_sin_cliente),
        "metodo_atribucion": METODO_ATRIBUCION,
        "model_version": MODEL_VERSION,
        "attribution_window_days": ATTRIBUTION_WINDOW_DAYS,
    })
    _write_lineage({
        "table": "campaign_channel_performance",
        "n_rows": len(df_perf),
        "n_roi_no_calculable": int(df_perf["roi"].isna().sum()),
    })

    logger.info("=== Fin corrida gold_attribution ===")


if __name__ == "__main__":
    main()