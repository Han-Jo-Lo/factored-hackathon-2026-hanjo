"""
Capa Silver: toma la salida validada de Bronze y aplica las reglas de
negocio acordadas:
  - Normaliza texto de pais (acentos/mayusculas) para poder mapear a moneda.
  - Resuelve moneda local por campana via country -> currency (mapeo propio,
    documentado como supuesto derivado, NO fuente oficial).
  - Convierte conversion_value y send_cost a moneda local EN COLUMNAS NUEVAS
    (conversion_value_local, send_cost_local) -- el valor original en USD
    NUNCA se sobreescribe (decision del proyecto).
  - budget NO se convierte (decision confirmada: es un monto de planeacion
    a nivel de campana completa, se mantiene solo en USD).
  - Usa la tasa del exchange_rate (no buy/sell) del mismo process_date de
    cada fila, con forward-fill acotado (FX_MAX_STALE_DAYS) si faltara.

Lee de: data/bronze/
Escribe en: data/silver/

Requiere: pip install pandas pyarrow
"""

import glob
import json
import logging
import os
import re
import unicodedata
from datetime import datetime, timezone

import pandas as pd

# ---------------------------------------------------------------------------
BRONZE_DIR = "data/bronze"
SILVER_DIR = "data/silver"
LINEAGE_PATH = os.path.join(SILVER_DIR, "_lineage", "manifest.jsonl")

FX_SOURCE_CURRENCY = "USD"
FX_MAX_STALE_DAYS = 5  # politica de recencia acordada: forward-fill acotado

# Mapeo pais -> moneda, construido por nosotros (documentado como supuesto
# derivado -- no existe una tabla oficial de mapeo en el dataset fuente).
COUNTRY_CURRENCY_MAP = {
    "Mexico": "MXN",
    "Colombia": "COP",
    "Argentina": "ARS",
}

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("silver_run.log")],
)
logger = logging.getLogger("silver")


# ---------------------------------------------------------------------------
def normalize_country(value) -> str | None:
    """
    Quita acentos y homogeneiza casing, para que 'México' y 'Mexico'
    (visto en la evidencia real: campaigns.target_country vs
    campaign_sends.open_country) mapeen a la misma clave de moneda.
    """
    if pd.isna(value):
        return None
    text = str(value).strip()
    text = "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))
    return text.title()


def _write_lineage(record: dict):
    os.makedirs(os.path.dirname(LINEAGE_PATH), exist_ok=True)
    record["processed_at"] = datetime.now(timezone.utc).isoformat()
    with open(LINEAGE_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


def extract_process_date_from_bronze_path(path: str) -> str:
    """
    Bronze ya normalizo TODAS las particiones a 'process_date=YYYY-MM-DD/',
    sin importar la convencion original de la fuente (year=/month=/day=).
    Por eso Silver solo necesita reconocer UNA convencion, no dos.
    """
    m = re.search(r"process_date=(\d{4}-\d{2}-\d{2})", path)
    if not m:
        raise ValueError(f"No pude extraer process_date de: {path}")
    return m.group(1)


# ---------------------------------------------------------------------------
# 1) campaigns: agrega moneda local resuelta (no reemplaza nada existente)
# ---------------------------------------------------------------------------
def process_campaigns() -> pd.DataFrame:
    df = pd.read_parquet(os.path.join(BRONZE_DIR, "campaigns.parquet"))
    n_input = len(df)

    df["target_country_normalized"] = df["target_country"].apply(normalize_country)
    df["currency_local"] = df["target_country_normalized"].map(COUNTRY_CURRENCY_MAP)

    n_con_pais = df["target_country_normalized"].notna().sum()
    n_con_moneda_resuelta = df["currency_local"].notna().sum()

    os.makedirs(SILVER_DIR, exist_ok=True)
    df.to_parquet(os.path.join(SILVER_DIR, "campaigns.parquet"), index=False)

    cobertura_pais = n_con_pais / n_input * 100
    logger.info(f"[campaigns] {n_input} filas. Cobertura de pais: {cobertura_pais:.1f}% "
                f"({n_con_pais} con pais, {n_con_moneda_resuelta} con moneda resuelta)")

    _write_lineage({
        "table": "campaigns", "partition": None, "n_rows": n_input,
        "pct_con_pais": round(cobertura_pais, 2),
        "pct_moneda_resuelta": round(n_con_moneda_resuelta / n_input * 100, 2),
    })

    # Solo lo que necesita el join de sends: campaign_id -> currency_local
    return df[["campaign_id", "currency_local"]]


# ---------------------------------------------------------------------------
# 2) daily_exchange_rates: filtra a los pares que realmente usamos (USD->local)
# ---------------------------------------------------------------------------
def load_fx_usd_lookup() -> pd.DataFrame:
    fx = pd.read_parquet(os.path.join(BRONZE_DIR, "daily_exchange_rates.parquet"))
    fx_usd = fx[fx["source_currency"] == FX_SOURCE_CURRENCY][
        ["date", "target_currency", "exchange_rate"]
    ].copy()
    fx_usd = fx_usd.sort_values("date").reset_index(drop=True)
    logger.info(f"[fx] lookup USD->local: {len(fx_usd)} filas, monedas: "
                f"{sorted(fx_usd['target_currency'].unique())}")
    return fx_usd


# ---------------------------------------------------------------------------
# 3) campaign_sends: join + conversion, una particion a la vez
# ---------------------------------------------------------------------------
def process_sends_partition(bronze_path: str, df_campaign_currency: pd.DataFrame, fx_usd: pd.DataFrame):
    process_date = extract_process_date_from_bronze_path(bronze_path)

    df = pd.read_parquet(bronze_path)
    n_input = len(df)

    # --- Join con campaigns: resuelve currency_local por fila ---
    df = df.merge(df_campaign_currency, on="campaign_id", how="left")

    # --- Join asof con FX: tasa del mismo dia, o la mas reciente hacia atras
    # dentro de la ventana FX_MAX_STALE_DAYS. Filas sin currency_local (pais
    # desconocido) quedan sin tasa de forma natural -- no es un error, es la
    # limitacion real de cobertura de pais que ya documentamos (55.5% nulo).
    df = df.sort_values("process_date").reset_index(drop=True)
    df = pd.merge_asof(
        df,
        fx_usd.rename(columns={"target_currency": "currency_local", "date": "fx_rate_date"}),
        left_on="process_date",
        right_on="fx_rate_date",
        by="currency_local",
        direction="backward",
        tolerance=pd.Timedelta(days=FX_MAX_STALE_DAYS),
    )
    df = df.rename(columns={"exchange_rate": "fx_rate_used"})
    df["fx_rate_is_stale"] = df["fx_rate_date"] != df["process_date"]

    # --- Columnas NUEVAS en moneda local -- el USD original queda intacto ---
    df["conversion_value_local"] = df["conversion_value"] * df["fx_rate_used"]
    df["send_cost_local"] = df["send_cost"] * df["fx_rate_used"]

    # --- Escritura idempotente, una particion a la vez ---
    partition_dir = os.path.join(SILVER_DIR, "campaign_sends", f"process_date={process_date}")
    os.makedirs(partition_dir, exist_ok=True)
    df.to_parquet(os.path.join(partition_dir, "data.parquet"), index=False)

    n_con_moneda = df["currency_local"].notna().sum()
    n_con_tasa = df["fx_rate_used"].notna().sum()
    n_stale = df["fx_rate_is_stale"].fillna(False).sum()

    logger.info(f"[campaign_sends] {process_date}: {n_input} filas, "
                f"{n_con_moneda} con moneda resuelta, {n_con_tasa} con tasa encontrada, "
                f"{n_stale} con tasa no exacta del dia (stale)")

    _write_lineage({
        "table": "campaign_sends", "partition": process_date, "n_rows": n_input,
        "pct_moneda_resuelta": round(n_con_moneda / n_input * 100, 2),
        "pct_tasa_encontrada_de_con_moneda": round(
            n_con_tasa / n_con_moneda * 100, 2) if n_con_moneda else None,
        "pct_send_cost_cobertura": round(df["send_cost"].notna().mean() * 100, 2),
    })


def process_all_sends(df_campaign_currency: pd.DataFrame, fx_usd: pd.DataFrame):
    pattern = os.path.join(BRONZE_DIR, "campaign_sends", "process_date=*", "data.parquet")
    files = sorted(glob.glob(pattern))
    logger.info(f"[campaign_sends] {len(files)} particiones de bronze encontradas")

    for f in files:
        try:
            process_sends_partition(f, df_campaign_currency, fx_usd)
        except Exception as e:
            logger.error(f"[campaign_sends] fallo procesando {f}: {e}")
            _write_lineage({
                "table": "campaign_sends", "partition": f,
                "error": str(e), "status": "FAILED",
            })


def main():
    logger.info("=== Inicio corrida silver ===")
    df_campaign_currency = process_campaigns()
    fx_usd = load_fx_usd_lookup()
    process_all_sends(df_campaign_currency, fx_usd)
    logger.info("=== Fin corrida silver ===")


if __name__ == "__main__":
    main()