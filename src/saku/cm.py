"""Codecs 2 et 3 (mélange de contextes en entiers) : choix entre la version C et la référence.

La version C est compilée à la première utilisation, dans le cache de l'utilisateur, sous un
nom qui dépend de l'empreinte du source : un source modifié donne une autre bibliothèque. Sans
compilateur, la référence Python prend le relais (même résultat, beaucoup plus lente).

`SAKU_CM=reference` force la référence Python.
"""

from __future__ import annotations

import ctypes
import hashlib
import logging
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path
from types import ModuleType

from saku import cm3_reference, cm_reference

journal = logging.getLogger("saku")
DOSSIER_C = Path(__file__).resolve().parent / "_cm"
OPTIONS = ("-std=c99", "-O2", "-fPIC", "-shared", "-fno-strict-aliasing")


def _cache() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "saku"


class _Moteur:
    """Un codec de mélange de contextes : sa version C (compilée à la demande) et sa référence."""

    def __init__(self, fichier: str, prefixe: str, version: int, reference: ModuleType) -> None:
        self.source = DOSSIER_C / fichier
        self.prefixe = prefixe
        self.version = version
        self.reference = reference
        self._bibliotheque: ctypes.CDLL | None = None
        self._essaye = False
        # Plusieurs fils compressent en meme temps : un seul charge, les autres attendent.
        # Sans ce verrou, un fil arrive pendant le chargement et se rabat sur la reference.
        self._verrou = threading.Lock()

    def _compiler(self) -> Path | None:
        compilateur = shutil.which(os.environ.get("CC", "cc"))
        if compilateur is None or not self.source.exists():
            return None
        source = self.source.read_bytes()
        empreinte = hashlib.sha256(source + " ".join(OPTIONS).encode()).hexdigest()[:16]
        cible = _cache() / f"lib{self.prefixe.replace('_', '')}-{empreinte}.so"
        if cible.exists():
            return cible
        cible.parent.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(dir=cible.parent) as dossier:
            provisoire = Path(dossier) / cible.name
            resultat = subprocess.run(  # noqa: S603 — compilateur trouvé par which, arguments fixes
                [compilateur, *OPTIONS, "-o", str(provisoire), str(self.source)],
                capture_output=True,
                text=True,
                check=False,
            )
            if resultat.returncode != 0:
                journal.warning(
                    "%s : compilation C impossible : %s", self.prefixe, resultat.stderr[-500:]
                )
                return None
            os.replace(provisoire, cible)
        return cible

    def _charger(self) -> ctypes.CDLL | None:
        if self._essaye:
            return self._bibliotheque
        with self._verrou:
            if not self._essaye:
                self._bibliotheque = self._charger_sans_verrou()
                self._essaye = True
        return self._bibliotheque

    def _charger_sans_verrou(self) -> ctypes.CDLL | None:
        if os.environ.get("SAKU_CM") == "reference":
            return None
        chemin = self._compiler()
        if chemin is None:
            journal.warning(
                "%s : version C indisponible, référence Python utilisée (lente)", self.prefixe
            )
            return None
        bib = ctypes.CDLL(str(chemin))
        octets = ctypes.POINTER(ctypes.c_uint8)
        compresser = getattr(bib, f"{self.prefixe}_compresser")
        compresser.argtypes = [
            ctypes.c_char_p,
            ctypes.c_size_t,
            ctypes.POINTER(octets),
            ctypes.POINTER(ctypes.c_size_t),
        ]
        compresser.restype = ctypes.c_int
        decompresser = getattr(bib, f"{self.prefixe}_decompresser")
        decompresser.argtypes = [ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t]
        decompresser.restype = ctypes.c_int
        liberer = getattr(bib, f"{self.prefixe}_liberer")
        liberer.argtypes = [ctypes.c_void_p]
        liberer.restype = None
        version = getattr(bib, f"{self.prefixe}_version")
        version.restype = ctypes.c_int
        if version() != self.version:
            journal.warning("%s : version C inattendue, référence Python utilisée", self.prefixe)
            return None
        return bib

    def disponible(self) -> bool:
        """Vrai si la version C est compilée et chargée."""
        return self._charger() is not None

    def compresser_c(self, clair: bytes) -> bytes:
        bib = self._charger()
        if bib is None:
            raise RuntimeError(f"{self.prefixe} : version C indisponible")
        sortie = ctypes.POINTER(ctypes.c_uint8)()
        taille = ctypes.c_size_t()
        if getattr(bib, f"{self.prefixe}_compresser")(
            clair, len(clair), ctypes.byref(sortie), ctypes.byref(taille)
        ):
            raise MemoryError(f"{self.prefixe} : allocation impossible")
        try:
            return ctypes.string_at(sortie, taille.value)
        finally:
            getattr(bib, f"{self.prefixe}_liberer")(sortie)

    def decompresser_c(self, charge: bytes, taille_claire: int) -> bytes:
        bib = self._charger()
        if bib is None:
            raise RuntimeError(f"{self.prefixe} : version C indisponible")
        if taille_claire < 0:
            raise ValueError("taille_claire négative")
        tampon = ctypes.create_string_buffer(max(taille_claire, 1))
        if getattr(bib, f"{self.prefixe}_decompresser")(charge, len(charge), tampon, taille_claire):
            raise MemoryError(f"{self.prefixe} : allocation impossible")
        return tampon.raw[:taille_claire]

    def compresser(self, clair: bytes) -> bytes:
        return self.compresser_c(clair) if self.disponible() else self.reference.compresser(clair)

    def decompresser(self, charge: bytes, taille_claire: int) -> bytes:
        if taille_claire < 0:
            raise ValueError("taille_claire négative")
        if self.disponible():
            return self.decompresser_c(charge, taille_claire)
        return self.reference.decompresser(charge, taille_claire)


CODEC_2 = _Moteur("cm.c", "saku_cm", 1, cm_reference)
CODEC_3 = _Moteur("cm3.c", "saku_cm3", 2, cm3_reference)

# Raccourcis historiques : le codec 2.
disponible = CODEC_2.disponible
compresser_c = CODEC_2.compresser_c
decompresser_c = CODEC_2.decompresser_c
compresser = CODEC_2.compresser
decompresser = CODEC_2.decompresser
