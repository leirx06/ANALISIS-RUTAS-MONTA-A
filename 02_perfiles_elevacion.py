"""
Paso 2: perfiles de elevación (altitud frente a distancia) de cada ruta.

Lee output/puntos.csv (generado en el paso 1) y dibuja un gráfico por ruta
dentro de una misma figura ("small multiples"): así se comparan formas de ruta
sin que unas tapen a otras.
"""
from pathlib import Path
from math import ceil

import matplotlib.pyplot as plt
import pandas as pd

BASE = Path(__file__).parent
puntos = pd.read_csv(BASE / "output/puntos.csv", parse_dates=["time"])
resumen = pd.read_csv(BASE / "output/resumen.csv", parse_dates=["fecha"])

# Orden cronológico (de la más antigua a la más reciente)
rutas = resumen.sort_values("fecha")["ruta"].tolist()

COLOR = "#1f6f5c"      # verde bosque para la línea
RELLENO = "#1f6f5c"
PUNTO_ALTO = "#a66b2c"

if not rutas:
    raise SystemExit("No hay rutas para dibujar en output/resumen.csv")

columnas = min(2, len(rutas))
filas = ceil(len(rutas) / columnas)
fig, ejes = plt.subplots(filas, columnas, figsize=(12, 3.25 * filas), squeeze=False)
ejes = ejes.flatten()

for ax, nombre in zip(ejes, rutas):
    d = puntos[puntos["ruta"] == nombre]
    r = resumen[resumen["ruta"] == nombre].iloc[0]

    # Suavizamos un poco la altitud (media móvil de 15 puntos) para quitar el ruido del GPS
    ele = d["ele"].rolling(15, center=True, min_periods=1).mean()

    ax.fill_between(d["dist_acum_km"], ele, ele.min() - 20, color=RELLENO, alpha=0.18)
    ax.plot(d["dist_acum_km"], ele, color=COLOR, linewidth=1.6)

    # Marcamos el punto más alto
    i_max = ele.idxmax()
    ax.scatter(d.loc[i_max, "dist_acum_km"], ele[i_max], color=PUNTO_ALTO, zorder=3, s=25)
    ax.annotate(f"{ele[i_max]:.0f} m", (d.loc[i_max, "dist_acum_km"], ele[i_max]),
                textcoords="offset points", xytext=(0, 7), ha="center", fontsize=8,
                color=PUNTO_ALTO)

    # Título en dos líneas: nombre y fecha arriba, estadísticas debajo (así no tapan la línea)
    ax.set_title(
        f"{nombre}  ·  {r['fecha']:%d/%m/%Y}\n"
        f"{r['distancia_km']:.1f} km  |  +{r['desnivel_pos_m']:.0f} m / -{r['desnivel_neg_m']:.0f} m",
        fontsize=10, loc="left", fontweight="bold", linespacing=1.5,
    )

    ax.set_ylim(ele.min() - 20, ele.max() + 0.12 * (ele.max() - ele.min()) + 10)
    ax.set_xlim(0, d["dist_acum_km"].max())
    ax.set_xlabel("Distancia (km)", fontsize=8)
    ax.set_ylabel("Altitud (m)", fontsize=8)
    ax.tick_params(labelsize=8)
    ax.grid(alpha=0.25)
    for lado in ("top", "right"):
        ax.spines[lado].set_visible(False)

# Ocultamos los huecos sobrantes
for ax in ejes[len(rutas):]:
    ax.axis("off")

fig.suptitle("Perfiles de elevación de mis rutas de montaña", fontsize=15, fontweight="bold", y=0.995)
fig.text(0.5, 0.005, "Cada gráfico tiene su propia escala de altitud. Fuente: archivos GPX de Strava.",
         ha="center", fontsize=8, color="#666")
fig.tight_layout(rect=(0, 0.015, 1, 0.985))
fig.savefig(BASE / "output/perfiles_elevacion.png", dpi=150)
print("Guardado output/perfiles_elevacion.png")
