"""Socle commun des tests : arbre de fichiers type et fabrication d'archives hostiles."""

from __future__ import annotations

import json
import random
import struct
import zlib
from compression import zstd
from pathlib import Path

import pytest

from saku import ParametresArgon2

TAILLE_BLOC_TEST = 4096
TAILLE_ENTETE = 80
TAILLE_ENTETE_BLOC = 16
TAILLE_PIED = 16


# Parametres Argon2 minimaux : les tests n'ont pas a attendre une vraie derivation.
ARGON2_RAPIDE = ParametresArgon2(passes=1, parallelisme=1, memoire_kio=8192)


@pytest.fixture
def arbre(tmp_path: Path) -> Path:
    """Dossier `projet/` melant tous les cas limites ; rend son chemin."""
    alea = random.Random(2026)
    racine = tmp_path / "projet"
    contenus = {
        "vide.txt": b"",
        "LISEZMOI.md": "Saku — archive d'essai, accents : éàùç œ\n".encode(),
        "src/principal.py": b"def f():\n    return 42\n" * 50,
        "src/sous dossier/été.py": b"x = 1\n",
        "src/long.txt": ("ligne de texte repetee\n" * 700)[: int(3.5 * TAILLE_BLOC_TEST)].encode(),
        "donnees/pile.bin": alea.randbytes(TAILLE_BLOC_TEST),
        "donnees/alea.bin": alea.randbytes(10_000),
        "donnees/nuls.dat": bytes(5000),
    }
    for chemin, contenu in contenus.items():
        cible = racine / chemin
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_bytes(contenu)
    (racine / "src/principal.py").chmod(0o755)
    return racine


def contenus_de(racine: Path) -> dict[str, bytes]:
    """Contenu de chaque fichier sous `racine`, par chemin relatif a `racine`."""
    return {
        p.relative_to(racine).as_posix(): p.read_bytes()
        for p in sorted(racine.rglob("*"))
        if p.is_file()
    }


def lire_index(octets: bytes) -> dict:
    """Decode l'index d'une archive NON chiffree."""
    (position,) = struct.unpack_from("<Q", octets, len(octets) - TAILLE_PIED)
    (taille_charge,) = struct.unpack_from("<I", octets, position + 8)
    debut = position + TAILLE_ENTETE_BLOC
    return json.loads(zstd.decompress(octets[debut : debut + taille_charge]))


def remplacer_index(octets: bytes, index: dict) -> bytes:
    """Rend l'archive NON chiffree avec un autre index, CRC et pied recalcules.

    Sert a fabriquer une archive hostile mais bien formee : seule la validation du contenu de
    l'index peut alors la rejeter.
    """
    (position,) = struct.unpack_from("<Q", octets, len(octets) - TAILLE_PIED)
    clair = json.dumps(index, ensure_ascii=False).encode()
    charge = zstd.compress(clair)
    entete = struct.pack("<BBHIII", 2, 1, 0, len(clair), len(charge), zlib.crc32(charge))
    pied = struct.pack("<Q", position) + b"UKAS"
    return octets[:position] + entete + charge + pied + struct.pack("<I", zlib.crc32(pied))
