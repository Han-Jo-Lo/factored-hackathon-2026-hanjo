"""
Capa Bronze: valida los 3 CSV fuente contra el contrato de datos
(contracts_schemas.py), separa filas validas de filas sospechosas
(con motivo explicito), y escribe el resultado en Parquet.

No transforma el significado de los datos (eso es Silver) -- solo
responde: "esto que llego, cumple lo minimo para poder confiar en ello?"

Principios aplicados (ver conversacion):
  - Procesamiento por particion, nunca todo en memoria de una vez
    (evita el problema de 1.4 GB en RAM que viste en el profiling).
  - Idempotente: reprocesar una particion SOBREESCRIBE su propio
    archivo de salida -- correr esto 2 veces no duplica nada.
  - Nunca se descarta una fila en silencio: toda fila que no pasa el
    contrato va a cuarentena con su motivo, nunca desaparece sin dejar rastro.
  - Cada corrida deja un registro de lineage (manifest.jsonl) con
    cuantas filas entraron, cuantas pasaron, cuantas se pusieron en
    cuarentena y por que -- esto es lo auditable, no el razonamiento
    interno de ningun modelo.

Requiere: pip install pandera pandas pyarrow
"""

import glob
import json
import logging
import os
import re
from datetime import datetime, timezone

import pandas as pd
import pandera.pandas as pa

from contracts.schemas import (
    CAMPAIGNS_SCHEMA,
    FX_SCHEMA,
    SENDS_SCHEMA,
    check_orphan_campaign_ids,
    check_was_opened_estructural,
)

# ---------------------------------------------------------------------------
# Rutas -- calibradas a la reubicacion confirmada: data/raw/ contiene los
# 3 CSV fuente (campaigns.csv, daily_exchange_rates.csv, campaign_sends/
# con particiones year=YYYY/month=MM/day=DD/).
# ---------------------------------------------------------------------------
RAW_DIR = "data/raw"
BRONZE_DIR = "data/bronze"
QUARANTINE_DIR = os.path.join(BRONZE_DIR, "_quarantine")
LINEAGE_PATH = os.path.join(BRONZE_DIR, "_lineage", "manifest.jsonl")

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("bronze_run.log")],
)
logger = logging.getLogger("bronze")


# ---------------------------------------------------------------------------
# Utilidades transversales
# ---------------------------------------------------------------------------
def extract_process_date_from_path(path: str) -> str:
    """
    Extrae la fecha de particion (YYYY-MM-DD) del path del archivo.
    Este es el UNICO lugar del pipeline que conoce el layout fisico
    de carpetas -- si tu convencion real es distinta a las 2 de abajo,
    aqui es donde se ajusta, en ningun otro lado.

    Soporta:
      1) .../process_date=2026-01-15/archivo.csv
      2) .../year=2026/month=01/day=15/archivo.csv
    """
    m = re.search(r"process_date=(\d{4}-\d{2}-\d{2})", path)
    if m:
        return m.group(1)

    m_year = re.search(r"year=(\d{4})", path)
    m_month = re.search(r"month=(\d{2})", path)
    m_day = re.search(r"day=(\d{2})", path)
    if m_year and m_month and m_day:
        return f"{m_year.group(1)}-{m_month.group(1)}-{m_day.group(1)}"

    raise ValueError(
        f"No pude extraer process_date del path: {path}. "
        f"Ajusta extract_process_date_from_path() a tu convencion real de carpetas."
    )


def _write_lineage(record: dict):
    """Registro append-only: nunca se sobreescribe el historial de corridas anteriores."""
    os.makedirs(os.path.dirname(LINEAGE_PATH), exist_ok=True)
    record["processed_at"] = datetime.now(timezone.utc).isoformat()
    with open(LINEAGE_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


def _split_valid_invalid(df: pd.DataFrame, schema: pa.DataFrameSchema):
    """
    Corre la validacion en modo lazy (junta TODOS los errores de una vez,
    no se detiene en el primero) y devuelve (filas_validas, filas_invalidas).
    Las invalidas llevan una columna 'quarantine_reason' legible.

    IMPORTANTE: se debe usar el DataFrame que devuelve schema.validate(),
    no el original -- ahi es donde coerce=True aplica de verdad las
    conversiones de tipo (ej. texto -> datetime). Ignorar el valor de
    retorno deja las columnas de fecha como texto en el Parquet de salida,
    lo que luego rompe cualquier operacion que exija tipo fecha real
    (como pd.merge_asof en Silver).
    """
    try:
        validated = schema.validate(df, lazy=True)
        return validated, validated.iloc[0:0].assign(quarantine_reason=pd.Series(dtype=str))
    except pa.errors.SchemaErrors as err:
        fc = err.failure_cases
        bad_idx = sorted(set(i for i in fc["index"].dropna().astype(int) if i in df.index))
        df_bad = df.loc[bad_idx].copy()

        reasons = (
            fc.dropna(subset=["index"])
            .assign(index=lambda x: x["index"].astype(int))
            .groupby("index")["check"]
            .apply(lambda s: "; ".join(sorted(set(s.astype(str)))))
        )
        df_bad["quarantine_reason"] = df_bad.index.map(reasons)

        df_good_raw = df.drop(index=bad_idx)
        # Revalida solo las filas buenas para obtener los tipos ya coercionados.
        # No deberia volver a fallar (ya se removieron las filas problematicas),
        # pero se protege por si acaso con un fallback al valor sin coercionar.
        try:
            df_good = schema.validate(df_good_raw, lazy=True)
        except pa.errors.SchemaErrors:
            df_good = df_good_raw
        return df_good, df_bad


def _save_quarantine(df_bad: pd.DataFrame, subdir: str):
    if len(df_bad) == 0:
        return
    qdir = os.path.join(QUARANTINE_DIR, subdir)
    os.makedirs(qdir, exist_ok=True)
    df_bad.to_csv(os.path.join(qdir, "quarantine.csv"), index=False)


# ---------------------------------------------------------------------------
# 1) campaigns (dimension) -- tabla pequena, se reprocesa completa cada corrida
# ---------------------------------------------------------------------------
def process_campaigns() -> pd.DataFrame:
    path = os.path.join(RAW_DIR, "marketing_campaigns.csv")
    logger.info(f"[campaigns] leyendo {path}")
    df = pd.read_csv(path)
    n_input = len(df)

    df_good, df_bad = _split_valid_invalid(df, CAMPAIGNS_SCHEMA)

    os.makedirs(BRONZE_DIR, exist_ok=True)
    df_good.to_parquet(os.path.join(BRONZE_DIR, "campaigns.parquet"), index=False)
    _save_quarantine(df_bad, "campaigns")

    logger.info(f"[campaigns] {len(df_good)} validas, {len(df_bad)} en cuarentena (de {n_input})")
    _write_lineage({
        "table": "campaigns", "partition": None,
        "n_input": n_input, "n_valid": len(df_good), "n_quarantined": len(df_bad),
    })
    return df_good


# ---------------------------------------------------------------------------
# 2) daily_exchange_rates (referencia)
# ---------------------------------------------------------------------------
def process_fx() -> pd.DataFrame:
    path = os.path.join(RAW_DIR, "daily_exchange_rates.csv")
    logger.info(f"[fx] leyendo {path}")
    df = pd.read_csv(path)
    n_input = len(df)

    # PK compuesta: pandera no la valida nativamente -- se resuelve aqui.
    pk_cols = ["date", "source_currency", "target_currency"]
    dup_mask = df.duplicated(subset=pk_cols, keep="first")
    df_dup = df[dup_mask].copy()
    if len(df_dup) > 0:
        df_dup["quarantine_reason"] = "duplicate_primary_key"
    df_dedup = df[~dup_mask]

    df_good, df_bad_schema = _split_valid_invalid(df_dedup, FX_SCHEMA)
    df_bad = pd.concat([df_bad_schema, df_dup], ignore_index=True)

    os.makedirs(BRONZE_DIR, exist_ok=True)
    df_good.to_parquet(os.path.join(BRONZE_DIR, "daily_exchange_rates.parquet"), index=False)
    _save_quarantine(df_bad, "daily_exchange_rates")

    logger.info(f"[fx] {len(df_good)} validas, {len(df_bad)} en cuarentena "
                f"({len(df_dup)} por PK duplicada, de {n_input})")
    _write_lineage({
        "table": "daily_exchange_rates", "partition": None,
        "n_input": n_input, "n_valid": len(df_good), "n_quarantined": len(df_bad),
        "n_duplicate_pk": int(len(df_dup)),
    })
    return df_good


# ---------------------------------------------------------------------------
# 3) campaign_sends (hecho, particionado por dia) -- se procesa 1 particion
#    a la vez, nunca todo el historico en memoria simultaneamente.
# ---------------------------------------------------------------------------
def process_sends_partition(csv_path: str, df_campaigns: pd.DataFrame):
    process_date = extract_process_date_from_path(csv_path)

    df = pd.read_csv(csv_path)
    n_input = len(df)

    # 1) Contrato de esquema (tipos, dominios, rangos)
    df_good, df_bad_schema = _split_valid_invalid(df, SENDS_SCHEMA)

    # 2) Reglas de negocio cruzadas (no expresables como columna aislada)
    df_bad_opened = check_was_opened_estructural(df_good)
    if len(df_bad_opened) > 0:
        df_bad_opened = df_bad_opened.copy()
        df_bad_opened["quarantine_reason"] = "was_opened_no_deberia_tener_valor"
        df_good = df_good.drop(index=df_bad_opened.index)

    df_bad_orphan = check_orphan_campaign_ids(df_good, df_campaigns)
    if len(df_bad_orphan) > 0:
        df_bad_orphan = df_bad_orphan.copy()
        df_bad_orphan["quarantine_reason"] = "campaign_id_huerfano"
        df_good = df_good.drop(index=df_bad_orphan.index)

    df_bad_all = pd.concat([df_bad_schema, df_bad_opened, df_bad_orphan], ignore_index=True)

    # 3) Escritura idempotente: sobreescribe SOLO esta particion, nunca
    #    duplica si se vuelve a correr el mismo dia.
    partition_dir = os.path.join(BRONZE_DIR, "campaign_sends", f"process_date={process_date}")
    os.makedirs(partition_dir, exist_ok=True)
    df_good.to_parquet(os.path.join(partition_dir, "data.parquet"), index=False)

    _save_quarantine(df_bad_all, os.path.join("campaign_sends", f"process_date={process_date}"))

    reason_counts = (
        df_bad_all["quarantine_reason"].value_counts().to_dict() if len(df_bad_all) else {}
    )
    logger.info(f"[campaign_sends] {process_date}: {len(df_good)} validas, "
                f"{len(df_bad_all)} cuarentena (de {n_input})")

    _write_lineage({
        "table": "campaign_sends", "partition": process_date,
        "n_input": n_input, "n_valid": len(df_good), "n_quarantined": len(df_bad_all),
        "quarantine_reasons": reason_counts,
    })


def process_all_sends(df_campaigns: pd.DataFrame, only_dates=None):
    """
    only_dates: lista opcional de fechas 'YYYY-MM-DD' para procesar solo
    esas particiones (lectura incremental -- ej. solo lo nuevo desde la
    ultima corrida). Si es None, procesa todas las particiones encontradas.
    """
    pattern = os.path.join(RAW_DIR, "campaign_sends", "**", "*.csv")
    files = sorted(glob.glob(pattern, recursive=True))
    logger.info(f"[campaign_sends] {len(files)} particiones encontradas")

    for f in files:
        if only_dates is not None:
            pd_date = extract_process_date_from_path(f)
            if pd_date not in only_dates:
                continue
        try:
            process_sends_partition(f, df_campaigns)
        except Exception as e:
            # Un fallo en 1 particion NO debe tumbar el resto del historico.
            logger.error(f"[campaign_sends] fallo procesando {f}: {e}")
            _write_lineage({
                "table": "campaign_sends", "partition": f,
                "error": str(e), "status": "FAILED",
            })


def main():
    logger.info("=== Inicio corrida bronze ===")
    df_campaigns = process_campaigns()
    process_fx()
    process_all_sends(df_campaigns)
    logger.info("=== Fin corrida bronze ===")


if __name__ == "__main__":
    main()