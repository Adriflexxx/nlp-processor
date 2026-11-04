"""Graphiques du rapport (matplotlib, sans affichage)."""

from __future__ import annotations

import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

# Palette qualitative sobre, lisible en clair et en impression.
COULEURS = ["#2E5EAA", "#E07B39", "#3C9D5D", "#B8455B", "#7A5BA6", "#8C7A3B", "#4C9DB0", "#7F7F7F"]


def _valide(valeur) -> bool:
    return valeur is not None and not (isinstance(valeur, float) and math.isnan(valeur))


def _court(texte: str, n: int = 38) -> str:
    return texte if len(texte) <= n else texte[: n - 1] + "…"


class GraphiquesMatplotlib:
    def courbes_couverture(self, series: dict[str, list[dict]], chemin: Path) -> Path:
        fig, ax = plt.subplots(figsize=(8, 5.5))
        for i, (nom, points) in enumerate(series.items()):
            retenus = [p for p in points if _valide(p["precision_top1"]) and _valide(p["couverture"])]
            xs = [p["couverture"] for p in retenus]
            ys = [p["precision_top1"] for p in retenus]
            ax.plot(xs, ys, label=_court(nom), color=COULEURS[i % len(COULEURS)], linewidth=1.8)
        ax.set_xlabel("Couverture (part des demandes avec une proposition)")
        ax.set_ylabel("Précision top 1 des demandes couvertes")
        ax.set_title("Couverture / précision (jeu de test)")
        ax.set_xlim(0, 1.01)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, loc="lower left")
        fig.tight_layout()
        fig.savefig(chemin, dpi=120)
        plt.close(fig)
        return chemin

    def fiabilite(self, series: dict[str, dict], chemin: Path) -> Path:
        fig, ax = plt.subplots(figsize=(6, 6))
        ax.plot([0, 1], [0, 1], linestyle="--", color="#999999", linewidth=1, label="calibration parfaite")
        for i, (nom, donnees) in enumerate(series.items()):
            tranches = donnees.get("tranches", [])
            ax.plot(
                [t["confiance"] for t in tranches], [t["exactitude"] for t in tranches],
                marker="o", color=COULEURS[i % len(COULEURS)], label=f"{_court(nom, 30)} (ECE {donnees.get('ece') or 0:.3f})",
            )
        ax.set_xlabel("Confiance moyenne (probabilité top 1)")
        ax.set_ylabel("Exactitude observée")
        ax.set_title("Fiabilité des probabilités (jeu de test)")
        ax.set_xlim(0, 1)
        ax.set_ylim(0, 1)
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8, loc="upper left")
        fig.tight_layout()
        fig.savefig(chemin, dpi=120)
        plt.close(fig)
        return chemin

    def confusion(self, matrice: list[list[int]], titres: list[str], chemin: Path) -> Path:
        n = len(titres)
        fig, ax = plt.subplots(figsize=(max(6, 0.55 * n + 3), max(5, 0.5 * n + 2)))
        image = ax.imshow(matrice, cmap="Blues")
        ax.set_xticks(range(n), [_court(t, 28) for t in titres], rotation=60, ha="right", fontsize=8)
        ax.set_yticks(range(n), [_court(t, 28) for t in titres], fontsize=8)
        ax.set_xlabel("Titre prédit")
        ax.set_ylabel("Titre vrai")
        ax.set_title("Titres les plus confondus (jeu de test)")
        maximum = max((max(ligne) for ligne in matrice), default=0)
        for i in range(n):
            for j in range(n):
                if matrice[i][j]:
                    couleur = "white" if matrice[i][j] > maximum / 2 else "#1a1a1a"
                    ax.text(j, i, matrice[i][j], ha="center", va="center", fontsize=7, color=couleur)
        fig.colorbar(image, ax=ax, fraction=0.03)
        fig.tight_layout()
        fig.savefig(chemin, dpi=120)
        plt.close(fig)
        return chemin
