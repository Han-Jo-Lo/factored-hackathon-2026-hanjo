"""
Capa Gold: construye la tabla de entrenamiento para el modelo de
atribucion (regresion logistica vs. baseline last-touch).

Esta tabla es insumo EXCLUSIVO de train_model.py -- no es para consultas
de negocio ad-hoc (esa es una capa Gold distinta, pospuesta segun lo
acordado).

Decisiones de diseno ya confirmadas en la conversacion:
  - Ventana de atribucion: 7 dias.
  - Etiquetado Opcion A: un touch se etiqueta 1 si el mismo cliente
    convierte en los 7 dias siguientes (sin importar cual touch especifico
    "causo" la conversion).
  - Split temporal 80/20 (no aleatorio) para evitar fuga de informacion.
  - Purga en la frontera del split: los touches cuya ventana de 7 dias
    cruza la fecha de corte se EXCLUYEN de train y test (su etiqueta
    podria depender de informacion del lado contrario del corte).

Nota de escala: esto carga el historico completo en memoria (a diferencia
de Bronze/Silver, que procesan una particion a la vez) porque las features
de secuencia necesitan ver TODO el historial de cada cliente, que cruza
cientos de particiones diarias. Con 2M filas y columnas reducidas, esto
es manejable en memoria. Si el volumen creciera un orden de magnitud, el
siguiente paso natural seria mover este calculo a SQL con funciones de
ventana en DuckDB en vez de pandas -- lo dejamos anotado como limite de
capacidad conocido, no lo resolvemos ahora por proporcionalidad.

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

ATTRIBUTION_WINDOW_DAYS = 10   # confirmado en la conversacion
TEST_SIZE_FRACTION = 0.20     # confirmado: ultimo 20% cronologico como test

# Solo las columnas que este calculo realmente necesita -- reduce memoria
# frente a cargar las 22+ columnas completas de Silver.
COLUMNAS_NECESARIAS = [
    "send_id", "customer_id", "campaign_id", "send_channel",
    "send_date", "process_date",
    "had_conversion", "conversion_date", "conversion_value",
]

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler(), logging.FileHandler("gold_run.log")],
)
logger = logging.getLogger("gold")


def _write_lineage(record: dict):
    os.makedirs(os.path.dirname(LINEAGE_PATH), exist_ok=True)
    record["processed_at"] = datetime.now(timezone.utc).isoformat()
    with open(LINEAGE_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, default=str) + "\n")


# ---------------------------------------------------------------------------
def load_silver_sends() -> pd.DataFrame:
    pattern = os.path.join(SILVER_DIR, "campaign_sends", "process_date=*", "data.parquet")
    files = sorted(glob.glob(pattern))
    logger.info(f"Cargando {len(files)} particiones de Silver (solo columnas necesarias)")

    partes = [pd.read_parquet(f, columns=COLUMNAS_NECESARIAS) for f in files]
    df = pd.concat(partes, ignore_index=True)
    logger.info(f"Total cargado: {len(df):,} filas")
    return df


def drop_customers_sin_id(df: pd.DataFrame) -> pd.DataFrame:
    """
    Un touch sin customer_id no puede participar en el modelo de atribucion
    (no hay 'secuencia de cliente' a la que asignarlo). Se excluye aqui,
    de forma explicita y contada -- no se imputa un customer_id falso.
    """
    n_antes = len(df)
    df = df.dropna(subset=["customer_id"]).copy()
    n_dropped = n_antes - len(df)
    logger.info(f"Filas sin customer_id excluidas: {n_dropped} ({n_dropped / n_antes * 100:.3f}%)")
    return df, n_dropped


# ---------------------------------------------------------------------------
def compute_sequence_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Para cada touch, calcula (dentro del historial de SU MISMO cliente):
      - posicion_en_secuencia: 1er, 2do, 3er... touch cronologico del cliente.
      - dias_desde_touch_anterior: gap en dias con el touch previo del cliente.
      - touches_previos_7d: cuantos touches recibio ese cliente en los 7 dias
        anteriores a este (sin contar el propio).
    """
    df = df.sort_values(["customer_id", "send_date"]).reset_index(drop=True)

    df["posicion_en_secuencia"] = df.groupby("customer_id").cumcount() + 1

    df["dias_desde_touch_anterior"] = (
        df.groupby("customer_id")["send_date"].diff().dt.total_seconds() / 86400
    )

    # Conteo con ventana de tiempo por grupo -- requiere indice de fecha
    # ordenado ascendente DENTRO de cada grupo (ya lo esta, por el sort de arriba).
    df_idx = df.set_index("send_date")
    rolling_counts = df_idx.groupby("customer_id")["send_id"].rolling(
        f"{ATTRIBUTION_WINDOW_DAYS}D"
    ).count()
    # La ventana incluye la fila actual -- se resta 1 para dejar solo los "previos".
    df["touches_previos_7d"] = rolling_counts.values - 1

    return df


def compute_label(df: pd.DataFrame) -> pd.DataFrame:
    """
    Etiqueta (Opcion A, confirmada): 1 si el cliente tiene una conversion
    en los ATTRIBUTION_WINDOW_DAYS siguientes al send_date de este touch.

    Se usa merge_asof direction='forward' -- IMPORTANTE (lección aprendida
    con el bug de Silver): ambos frames deben ordenarse SOLO por la columna
    'on' (send_date / conversion_date), nunca agrupando primero por 'by'.
    """
    conversiones = (
        df[df["had_conversion"]][["customer_id", "conversion_date"]]
        .dropna()
        .sort_values("conversion_date")
        .reset_index(drop=True)
    )

    df_sorted = df.sort_values("send_date").reset_index(drop=True)

    merged = pd.merge_asof(
        df_sorted,
        conversiones.rename(columns={"conversion_date": "siguiente_conversion"}),
        left_on="send_date",
        right_on="siguiente_conversion",
        by="customer_id",
        direction="forward",
        tolerance=pd.Timedelta(days=ATTRIBUTION_WINDOW_DAYS),
    )
    merged["label_convirtio_en_7d"] = merged["siguiente_conversion"].notna().astype(int)
    merged = merged.drop(columns=["siguiente_conversion"])
    return merged


def apply_temporal_split(df: pd.DataFrame):
    """
    Split 80/20 cronologico (NO aleatorio) + purga anti-leakage en la
    frontera: cualquier touch cuya ventana de 7 dias hacia adelante cruce
    la fecha de corte se excluye de train Y de test, porque su etiqueta
    pudo haberse calculado con informacion del lado contrario del corte.
    """
    fechas_unicas = np.sort(df["process_date"].unique())
    idx_corte = int(len(fechas_unicas) * (1 - TEST_SIZE_FRACTION))
    fecha_corte = pd.Timestamp(fechas_unicas[idx_corte])

    buffer = pd.Timedelta(days=ATTRIBUTION_WINDOW_DAYS)

    condiciones = [
        df["send_date"] < (fecha_corte - buffer),   # train: lejos del corte
        df["send_date"] >= fecha_corte,             # test: despues del corte
    ]
    opciones = ["train", "test"]
    df["split"] = np.select(condiciones, opciones, default="purged_buffer")

    resumen = df["split"].value_counts().to_dict()
    logger.info(f"Fecha de corte: {fecha_corte.date()}. Split: {resumen}")
    return df, str(fecha_corte.date()), resumen


# ---------------------------------------------------------------------------
def main():
    logger.info("=== Inicio corrida gold ===")

    df = load_silver_sends()
    df, n_sin_customer = drop_customers_sin_id(df)

    df = compute_sequence_features(df)
    df = compute_label(df)
    df, fecha_corte, resumen_split = apply_temporal_split(df)

    columnas_finales = [
        "send_id", "customer_id", "campaign_id", "send_channel",
        "send_date", "process_date",
        "posicion_en_secuencia", "dias_desde_touch_anterior", "touches_previos_7d",
        "had_conversion", "conversion_value",
        "label_convirtio_en_7d", "split",
    ]
    df_final = df[columnas_finales]

    os.makedirs(GOLD_DIR, exist_ok=True)
    out_path = os.path.join(GOLD_DIR, "attribution_training_table.parquet")
    df_final.to_parquet(out_path, index=False)

    balance_clases = df_final.groupby("split")["label_convirtio_en_7d"].mean().to_dict()

    logger.info(f"Tabla final escrita en {out_path}: {len(df_final):,} filas")
    logger.info(f"Balance de clases (tasa de label=1) por split: {balance_clases}")

    _write_lineage({
        "table": "attribution_training_table",
        "n_input_rows": len(df) + n_sin_customer,
        "n_output_rows": len(df_final),
        "n_dropped_sin_customer_id": int(n_sin_customer),
        "fecha_corte_split": fecha_corte,
        "attribution_window_days": ATTRIBUTION_WINDOW_DAYS,
        "conteo_por_split": resumen_split,
        "balance_clases_por_split": balance_clases,
    })

    logger.info("=== Fin corrida gold ===")


if __name__ == "__main__":
    main()