"""
Paso 1: leer los archivos GPX y convertirlos en tablas (DataFrames) con las que se pueda trabajar.

Un GPX es un XML. Cada <trkpt> es un punto del recorrido con:
  - lat / lon  (atributos)
  - <ele>      altitud en metros
  - <time>     fecha y hora (UTC)
  - hr / cad   pulsaciones y cadencia (solo si el reloj las registró)

Salidas:
  - output/puntos.csv   -> una fila por punto GPS (todas las rutas juntas)
  - output/resumen.csv  -> una fila por ruta con sus estadísticas
"""
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np
import pandas as pd

DATA_DIR = Path(__file__).parent / "data"
OUT_DIR = Path(__file__).parent / "output"
OUT_DIR.mkdir(exist_ok=True)

# Espacios de nombres XML (el GPX los usa y hay que indicarlos para encontrar las etiquetas)
NS = {
    "g": "http://www.topografix.com/GPX/1/1",
    "tp": "http://www.garmin.com/xmlschemas/TrackPointExtension/v1",
}


def leer_gpx(ruta: Path) -> pd.DataFrame:
    """Lee un GPX y devuelve un DataFrame con un punto por fila."""
    arbol = ET.parse(ruta)
    raiz = arbol.getroot()
    nombre = raiz.find("g:trk/g:name", NS).text

    filas = []
    for pt in raiz.iterfind(".//g:trkpt", NS):
        hr = pt.find(".//tp:hr", NS)
        cad = pt.find(".//tp:cad", NS)
        filas.append(
            {
                "lat": float(pt.get("lat")),
                "lon": float(pt.get("lon")),
                "ele": float(pt.find("g:ele", NS).text),
                "time": pt.find("g:time", NS).text,
                # Si el archivo no trae pulsaciones/cadencia, dejamos NaN (vacío)
                "hr": float(hr.text) if hr is not None else np.nan,
                "cad": float(cad.text) if cad is not None else np.nan,
            }
        )

    df = pd.DataFrame(filas)
    df["time"] = pd.to_datetime(df["time"], utc=True)
    df.insert(0, "ruta", nombre)
    return df


def haversine_m(lat1, lon1, lat2, lon2):
    """Distancia en metros entre pares de coordenadas (fórmula de la 'gran circunferencia')."""
    R = 6_371_000  # radio medio de la Tierra en metros
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dlmb = np.radians(lon2) - np.radians(lon1)
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * R * np.arcsin(np.sqrt(a))


def añadir_columnas(df: pd.DataFrame) -> pd.DataFrame:
    """Calcula distancia, tiempo y velocidad entre puntos consecutivos."""
    df = df.copy()
    # Distancia de cada punto al anterior (el primero no tiene anterior -> 0)
    df["dist_m"] = haversine_m(
        df["lat"].shift(), df["lon"].shift(), df["lat"], df["lon"]
    ).fillna(0)
    df["dist_acum_km"] = df["dist_m"].cumsum() / 1000

    # Segundos entre puntos y desde el inicio
    df["dt_s"] = df["time"].diff().dt.total_seconds().fillna(0)
    df["t_min"] = (df["time"] - df["time"].iloc[0]).dt.total_seconds() / 60

    # Velocidad instantánea en km/h (evitamos dividir entre 0)
    df["vel_kmh"] = np.where(df["dt_s"] > 0, df["dist_m"] / df["dt_s"] * 3.6, 0)
    return df


def desnivel(ele: pd.Series, umbral: float = 3.0):
    """
    Desnivel positivo y negativo acumulado.

    Si sumáramos cada pequeña subida del GPS saldría un desnivel inflado por el 'ruido'
    del altímetro. Por eso solo contamos un cambio cuando se aleja al menos `umbral`
    metros del último punto de referencia (técnica de histéresis).
    """
    ref = ele.iloc[0]
    subida = bajada = 0.0
    for e in ele.iloc[1:]:
        if e - ref >= umbral:
            subida += e - ref
            ref = e
        elif ref - e >= umbral:
            bajada += ref - e
            ref = e
    return subida, bajada


def resumen(df: pd.DataFrame) -> dict:
    """Estadísticas de una ruta."""
    subida, bajada = desnivel(df["ele"])
    dist_km = df["dist_acum_km"].iloc[-1]
    total_h = df["dt_s"].sum() / 3600

    # Tiempo en movimiento: solo los intervalos con velocidad > 1 km/h y sin saltos raros
    mov = df[(df["vel_kmh"] > 1) & (df["dt_s"] < 60)]
    mov_h = mov["dt_s"].sum() / 3600

    hr_valida = df.loc[df["hr"] > 40, "hr"]  # hr=0 significa "sin dato"
    return {
        "ruta": df["ruta"].iloc[0],
        "fecha": df["time"].iloc[0].date(),
        "puntos": len(df),
        "distancia_km": round(dist_km, 2),
        "desnivel_pos_m": round(subida),
        "desnivel_neg_m": round(bajada),
        "alt_min_m": round(df["ele"].min()),
        "alt_max_m": round(df["ele"].max()),
        "tiempo_total_h": round(total_h, 2),
        "tiempo_mov_h": round(mov_h, 2),
        "vel_media_mov_kmh": round(dist_km / mov_h, 2) if mov_h else np.nan,
        "pendiente_media_subida_%": round(subida / (dist_km * 1000) * 100, 1),
        "hr_media": round(hr_valida.mean()) if len(hr_valida) else np.nan,
        "hr_max": round(hr_valida.max()) if len(hr_valida) else np.nan,
    }


def perfil_publico(df: pd.DataFrame) -> list[dict[str, float]]:
    """Devuelve una muestra del perfil sin publicar coordenadas ni pulsaciones."""
    indices = np.linspace(0, len(df) - 1, num=min(120, len(df)), dtype=int)
    muestra = df.iloc[indices][["dist_acum_km", "ele"]]
    return [
        {
            "distancia_km": round(float(distancia), 3),
            "altitud_m": round(float(altitud), 1),
        }
        for distancia, altitud in zip(muestra["dist_acum_km"], muestra["ele"])
    ]


def main():
    archivos_gpx = sorted(DATA_DIR.glob("*.gpx"))
    if not archivos_gpx:
        raise SystemExit(f"No se encontraron archivos GPX en {DATA_DIR}")

    tablas = []
    for gpx in archivos_gpx:
        df = añadir_columnas(leer_gpx(gpx))
        tablas.append(df)

    puntos = pd.concat(tablas, ignore_index=True)
    res = pd.DataFrame([resumen(t) for t in tablas]).sort_values("fecha")

    puntos.to_csv(OUT_DIR / "puntos.csv", index=False)
    res.to_csv(OUT_DIR / "resumen.csv", index=False)
    columnas_publicas = [
        "ruta",
        "fecha",
        "distancia_km",
        "desnivel_pos_m",
        "desnivel_neg_m",
        "alt_min_m",
        "alt_max_m",
        "tiempo_total_h",
        "tiempo_mov_h",
    ]
    resumen_publico = res[columnas_publicas].copy()
    resumen_publico["perfil"] = [perfil_publico(df) for df in tablas]
    resumen_publico.to_json(
        OUT_DIR / "resumen.json",
        orient="records",
        force_ascii=False,
        date_format="iso",
    )

    pd.set_option("display.width", 250, "display.max_columns", 30)
    print(res.to_string(index=False))


if __name__ == "__main__":
    sys.exit(main())
