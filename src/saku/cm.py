"""Codec 2 (mélange de contextes en entiers) : choix entre la version C et la référence Python.

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
from pathlib import Path

from saku import cm_reference

journal = logging.getLogger("saku")
SOURCE = Path(__file__).resolve().parent / "_cm" / "cm.c"
OPTIONS = ("-std=c99", "-O2", "-fPIC", "-shared", "-fno-strict-aliasing")
VERSION_SPEC = 1

_bibliotheque: ctypes.CDLL | None = None
_essaye = False


def _cache() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache"
    return Path(base) / "saku"


def _compiler() -> Path | None:
    compilateur = shutil.which(os.environ.get("CC", "cc"))
    if compilateur is None or not SOURCE.exists():
        return None
    source = SOURCE.read_bytes()
    empreinte = hashlib.sha256(source + " ".join(OPTIONS).encode()).hexdigest()[:16]
    cible = _cache() / f"libsakucm-{empreinte}.so"
    if cible.exists():
        return cible
    cible.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=cible.parent) as dossier:
        provisoire = Path(dossier) / cible.name
        resultat = subprocess.run(  # noqa: S603 — compilateur trouvé par which, arguments fixes
            [compilateur, *OPTIONS, "-o", str(provisoire), str(SOURCE)],
            capture_output=True,
            text=True,
            check=False,
        )
        if resultat.returncode != 0:
            journal.warning("codec 2 : compilation C impossible : %s", resultat.stderr[-500:])
            return None
        os.replace(provisoire, cible)
    return cible


def _charger() -> ctypes.CDLL | None:
    global _bibliotheque, _essaye
    if _essaye:
        return _bibliotheque
    _essaye = True
    if os.environ.get("SAKU_CM") == "reference":
        return None
    chemin = _compiler()
    if chemin is None:
        journal.warning("codec 2 : version C indisponible, référence Python utilisée (lente)")
        return None
    bib = ctypes.CDLL(str(chemin))
    octets = ctypes.POINTER(ctypes.c_uint8)
    bib.saku_cm_compresser.argtypes = [
        ctypes.c_char_p,
        ctypes.c_size_t,
        ctypes.POINTER(octets),
        ctypes.POINTER(ctypes.c_size_t),
    ]
    bib.saku_cm_compresser.restype = ctypes.c_int
    bib.saku_cm_decompresser.argtypes = [
        ctypes.c_char_p,
        ctypes.c_size_t,
        ctypes.c_char_p,
        ctypes.c_size_t,
    ]
    bib.saku_cm_decompresser.restype = ctypes.c_int
    bib.saku_cm_liberer.argtypes = [ctypes.c_void_p]
    bib.saku_cm_liberer.restype = None
    bib.saku_cm_version.restype = ctypes.c_int
    if bib.saku_cm_version() != VERSION_SPEC:
        journal.warning("codec 2 : version C inattendue, référence Python utilisée")
        return None
    _bibliotheque = bib
    return bib


def disponible() -> bool:
    """Vrai si la version C est compilée et chargée."""
    return _charger() is not None


def compresser_c(clair: bytes) -> bytes:
    bib = _charger()
    if bib is None:
        raise RuntimeError("version C du codec 2 indisponible")
    sortie = ctypes.POINTER(ctypes.c_uint8)()
    taille = ctypes.c_size_t()
    if bib.saku_cm_compresser(clair, len(clair), ctypes.byref(sortie), ctypes.byref(taille)):
        raise MemoryError("codec 2 : allocation impossible")
    try:
        return ctypes.string_at(sortie, taille.value)
    finally:
        bib.saku_cm_liberer(sortie)


def decompresser_c(charge: bytes, taille_claire: int) -> bytes:
    bib = _charger()
    if bib is None:
        raise RuntimeError("version C du codec 2 indisponible")
    if taille_claire < 0:
        raise ValueError("taille_claire négative")
    tampon = ctypes.create_string_buffer(max(taille_claire, 1))
    if bib.saku_cm_decompresser(charge, len(charge), tampon, taille_claire):
        raise MemoryError("codec 2 : allocation impossible")
    return tampon.raw[:taille_claire]


def compresser(clair: bytes) -> bytes:
    return compresser_c(clair) if disponible() else cm_reference.compresser(clair)


def decompresser(charge: bytes, taille_claire: int) -> bytes:
    if taille_claire < 0:
        raise ValueError("taille_claire négative")
    if disponible():
        return decompresser_c(charge, taille_claire)
    return cm_reference.decompresser(charge, taille_claire)
