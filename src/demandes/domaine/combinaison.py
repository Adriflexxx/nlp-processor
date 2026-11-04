"""Combinaisons de modèles de base et modes de décision."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

MODELES_TFIDF = ("svm_tfidf", "rl_tfidf")
MODELES_EMB = ("svm_emb", "rl_emb", "knn_emb")
MODELES_LINEAIRES = ("svm_tfidf", "rl_tfidf", "svm_emb", "rl_emb")
TOUS_LES_MODELES = MODELES_TFIDF + MODELES_EMB


class Mode(StrEnum):
    SEUL = "seul"
    MOYENNE = "moyenne"
    META = "meta"


@dataclass(frozen=True, slots=True)
class Combinaison:
    mode: Mode
    modeles: tuple[str, ...]
    libelle: str = field(default="", compare=False)

    def __post_init__(self) -> None:
        inconnus = [m for m in self.modeles if m not in TOUS_LES_MODELES]
        if inconnus:
            raise ValueError(f"modèles inconnus : {inconnus}")
        if not self.modeles:
            raise ValueError("une combinaison demande au moins un modèle")
        if self.mode is Mode.SEUL and len(self.modeles) != 1:
            raise ValueError("le mode « seul » prend exactement un modèle")
        if self.mode is not Mode.SEUL and len(self.modeles) < 2:
            raise ValueError(f"le mode « {self.mode} » demande au moins deux modèles")
        if len(set(self.modeles)) != len(self.modeles):
            raise ValueError("un modèle apparaît deux fois")

    @property
    def nom(self) -> str:
        """Identifiant stable, utilisé pour les fichiers : mode + modèles dans l'ordre canonique."""
        ordonnes = sorted(self.modeles, key=TOUS_LES_MODELES.index)
        return f"{self.mode}__{'+'.join(ordonnes)}"

    @property
    def fait_appel_au_llm(self) -> bool:
        """En production, la branche embedding demande une fiche IAG et un embedding par mail."""
        return any(m in MODELES_EMB for m in self.modeles)

    @property
    def cout(self) -> int:
        """Lourdeur relative, pour préférer la combinaison la plus simple à résultat égal."""
        return len(self.modeles) + (2 if self.fait_appel_au_llm else 0) + (1 if self.mode is Mode.META else 0)


def combinaisons_standard(meilleur_tfidf: str, meilleur_emb: str) -> list[Combinaison]:
    """Les 13 combinaisons évaluées automatiquement.

    `meilleur_tfidf` / `meilleur_emb` : meilleur modèle de chaque branche en validation croisée.
    """
    combis = [Combinaison(Mode.SEUL, (m,), f"{m} seul") for m in TOUS_LES_MODELES]
    groupes = [
        (MODELES_TFIDF, "branche TF-IDF"),
        (("svm_emb", "rl_emb"), "branche embedding"),
        ((meilleur_tfidf, meilleur_emb), "meilleur de chaque branche"),
        (MODELES_LINEAIRES, "4 modèles linéaires"),
    ]
    for modeles, libelle in groupes:
        for mode in (Mode.MOYENNE, Mode.META):
            combis.append(Combinaison(mode, tuple(modeles), f"{libelle} ({mode})"))
    return combis


def lire_combinaison(mode: str, modeles: list[str] | tuple[str, ...]) -> Combinaison:
    return Combinaison(Mode(mode), tuple(modeles))
