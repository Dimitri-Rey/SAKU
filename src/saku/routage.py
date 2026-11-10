"""Classement des fichiers (section 7 du format) : texte ou autre, et ordre du flux."""

from __future__ import annotations

import codecs
from pathlib import PurePosixPath


class DetecteurTexte:
    """Decide au fil de l'eau si un contenu est du texte UTF-8 valide sans octet nul.

    Fonctionne par morceaux pour classer un gros fichier sans le charger en memoire.
    """

    def __init__(self) -> None:
        self._decodeur = codecs.getincrementaldecoder("utf-8")(errors="strict")
        self._texte = True

    def alimenter(self, morceau: bytes) -> None:
        """Examine le morceau suivant du contenu."""
        if not self._texte:
            return
        if b"\x00" in morceau:
            self._texte = False
            return
        try:
            self._decodeur.decode(morceau)
        except UnicodeDecodeError:
            self._texte = False

    def conclure(self) -> bool:
        """Rend le verdict ; a n'appeler qu'apres le dernier morceau."""
        if self._texte:
            try:
                # Detecte une sequence UTF-8 coupee en fin de fichier.
                self._decodeur.decode(b"", final=True)
            except UnicodeDecodeError:
                self._texte = False
        return self._texte


def est_texte(contenu: bytes) -> bool:
    """Vrai si `contenu` est de l'UTF-8 valide sans octet nul (un contenu vide est du texte)."""
    detecteur = DetecteurTexte()
    detecteur.alimenter(contenu)
    return detecteur.conclure()


def cle_de_flux(chemin: str, texte: bool) -> tuple[bool, str, str]:
    """Cle de tri du flux logique : les textes d'abord, puis (extension en minuscules, chemin)."""
    return (not texte, PurePosixPath(chemin).suffix.lower(), chemin)
