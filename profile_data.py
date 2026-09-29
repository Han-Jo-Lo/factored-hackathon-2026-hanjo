"""
Profiling de las 3 tablas reales del proyecto.

Este script SOLO imprime estadisticas agregadas (conteos, porcentajes,
min/max, distribuciones) -- nunca filas individuales -- para poder
calibrar el generador sintetico sin necesidad de compartir los datos
reales completos.

Edita las rutas de PATH_* abajo segun donde tengas tus CSV, luego corre:
    python profile_data.py

Copia la salida completa de la consola y pegala en el chat.
"""

import glob
import os

import pandas as pd

pd.set_option("display.max_columns", None)
pd.set_option("display.width", 120)

# ---------------------------------------------------------------------------
# EDITA ESTAS RUTAS SEGUN TU ESTRUCTURA REAL
# ---------------------------------------------------------------------------
PATH_CAMPAIGNS = "/home/hanjo/Documents/Python_Scripts/hackathon/data/raw.csv"
PATH_FX = "/home/hanjo/Documents/Python_Scripts/hackathon/data/raw/daily_exchange_rates.csv"
# Si campaign_sends esta particionado en carpetas por dia, apunta al patron glob:
PATH_SENDS_GLOB = "/home/hanjo/Documents/Python_Scripts/hackathon/data/raw/campaign_sends/**/*.csv"


def line(title):
    print("\n" + "=" * 70)
    print(title)
    print("=" * 70)


def profile_generic(df: pd.DataFrame, name: str):
    line(f"{name}: forma general")
    print(f"filas: {len(df):,}  columnas: {df.shape[1]}")
    print(f"memoria aproximada: {df.memory_usage(deep=True).sum() / 1e6:.1f} MB")

    line(f"{name}: tipos de dato")
    print(df.dtypes)

    line(f"{name}: % de nulos por columna")
    nulls = (df.isnull().mean() * 100).round(2)
    print(nulls[nulls > 0].sort_values(ascending=False) if nulls.sum() > 0 else "sin nulos")

    line(f"{name}: describe() numerico")
    print(df.describe(include="number").T)

    line(f"{name}: cardinalidad de columnas tipo texto/categoria")
    for col in df.select_dtypes(include=["object"]).columns:
        n_unique = df[col].nunique(dropna=True)
        print(f"  {col}: {n_unique} valores unicos")
        if n_unique <= 20:
            print(df[col].value_counts(dropna=False).to_string())
        print()


def profile_campaigns(path):
    if not os.path.exists(path):
        print(f"[omitido] no encontre {path}")
        return None
    df = pd.read_csv(path)
    profile_generic(df, "campaigns")

    line("campaigns: duplicados de campaign_id")
    print(f"duplicados: {df['campaign_id'].duplicated().sum()}")

    return df


def profile_fx(path):
    if not os.path.exists(path):
        print(f"[omitido] no encontre {path}")
        return None
    df = pd.read_csv(path, parse_dates=["date"])
    profile_generic(df, "daily_exchange_rates")

    line("daily_exchange_rates: cobertura de fechas")
    date_min, date_max = df["date"].min(), df["date"].max()
    total_calendar_days = (date_max - date_min).days + 1
    dias_presentes = df["date"].nunique()
    print(f"rango: {date_min.date()} a {date_max.date()}")
    print(f"dias calendario en el rango: {total_calendar_days}")
    print(f"dias con al menos una tasa: {dias_presentes}")
    print(f"dias faltantes: {total_calendar_days - dias_presentes} "
          f"({(1 - dias_presentes / total_calendar_days) * 100:.1f}%)")

    line("daily_exchange_rates: monedas cubiertas")
    print(df.groupby(["source_currency", "target_currency"]).size())

    return df


def profile_sends(glob_pattern, df_campaigns):
    files = sorted(glob.glob(glob_pattern, recursive=True))
    if not files:
        print(f"[omitido] no encontre archivos con el patron {glob_pattern}")
        return None

    print(f"encontrados {len(files)} archivos de particion")

    # Volumen por particion (sin cargar todo en memoria de una vez)
    line("campaign_sends: volumen por particion")
    counts = []
    for f in files:
        n = sum(1 for _ in open(f, encoding="utf-8")) - 1  # -1 por el header
        counts.append(n)
    s = pd.Series(counts)
    print(f"total de filas (suma de particiones): {s.sum():,}")
    print(f"filas por particion -> min: {s.min()}, mediana: {s.median():.0f}, "
          f"max: {s.max()}, promedio: {s.mean():.1f}")

    # Carga completa para el resto de metricas (ajusta si el volumen real es muy grande)
    df = pd.concat([pd.read_csv(f) for f in files], ignore_index=True)
    profile_generic(df, "campaign_sends")

    line("campaign_sends: duplicados de send_id")
    print(f"duplicados: {df['send_id'].duplicated().sum()}")

    if df_campaigns is not None:
        line("campaign_sends: FKs huerfanas hacia campaigns")
        huerfanos = ~df["campaign_id"].isin(df_campaigns["campaign_id"])
        print(f"campaign_id huerfano: {huerfanos.sum()} filas "
              f"({huerfanos.mean() * 100:.3f}%)")

    # --- Columnas booleanas: reportar nulos explicitamente antes de operar ---
    # Si una columna booleana tiene nulos, pandas la sube a float64 (True/False/NaN)
    # y el operador `~` (invertir) falla sobre float. Por eso primero medimos
    # los nulos (es un hallazgo de calidad real) y luego normalizamos a bool
    # de forma EXPLICITA para el calculo del embudo, dejando claro el supuesto.
    flag_cols = ["was_delivered", "was_opened", "was_clicked", "had_conversion"]

    line("campaign_sends: nulos en columnas booleanas del embudo")
    for col in flag_cols:
        if col not in df.columns:
            print(f"  {col}: columna no encontrada")
            continue
        n_nulls = df[col].isnull().sum()
        print(f"  {col}: dtype={df[col].dtype}, nulos={n_nulls} "
              f"({n_nulls / len(df) * 100:.3f}%)")

    line("campaign_sends: consistencia logica embudo (delivered -> opened -> clicked -> conversion)")
    print("Nota: para este calculo, un booleano nulo se trata como False "
          "(supuesto explicito -- ajustar si el negocio define lo contrario).")

    delivered = df["was_delivered"].fillna(False).astype(bool)
    opened = df["was_opened"].fillna(False).astype(bool)
    clicked = df["was_clicked"].fillna(False).astype(bool)
    converted = df["had_conversion"].fillna(False).astype(bool)

    print(f"was_delivered=True: {delivered.sum()}")
    print(f"was_opened=True: {opened.sum()}")
    print(f"  de estos, was_opened=True con was_delivered=False (inconsistente): "
          f"{(opened & (~delivered)).sum()}")
    print(f"was_clicked=True: {clicked.sum()}")
    print(f"  de estos, was_clicked=True con was_opened=False (inconsistente): "
          f"{(clicked & (~opened)).sum()}")
    print(f"had_conversion=True: {converted.sum()}")
    print(f"  de estos, had_conversion=True con was_clicked=False (inconsistente): "
          f"{(converted & (~clicked)).sum()}")

    return df


def main():
    df_campaigns = profile_campaigns(PATH_CAMPAIGNS)
    profile_fx(PATH_FX)
    profile_sends(PATH_SENDS_GLOB, df_campaigns)


if __name__ == "__main__":
    main()