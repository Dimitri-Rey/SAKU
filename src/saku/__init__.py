"""Saku : archiveur a compression par type de fichier puis chiffrement authentifie."""

from __future__ import annotations

from .archive import Archive, FichierArchive, creer_archive
from .chiffrement import (
    chiffrer_bloc,
    dechiffrer_bloc,
    deriver_cle,
    nonce_bloc,
)
from .codecs import compresser, decompresser
from .erreurs import (
    ArchiveInvalide,
    EchecAuthentification,
    ErreurSaku,
    FichierAbsent,
    MotDePasseRequis,
    SourceInvalide,
)
from .format import EnTete, EnTeteBloc, ParametresArgon2, pied_depuis_octets, pied_vers_octets
from .routage import est_texte

__version__ = "0.1.0"

__all__ = [
    "Archive",
    "ArchiveInvalide",
    "EchecAuthentification",
    "EnTete",
    "EnTeteBloc",
    "ErreurSaku",
    "FichierAbsent",
    "FichierArchive",
    "MotDePasseRequis",
    "ParametresArgon2",
    "SourceInvalide",
    "chiffrer_bloc",
    "compresser",
    "creer_archive",
    "dechiffrer_bloc",
    "decompresser",
    "deriver_cle",
    "est_texte",
    "nonce_bloc",
    "pied_depuis_octets",
    "pied_vers_octets",
]
