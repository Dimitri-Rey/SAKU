"""Erreurs levees par Saku."""

from __future__ import annotations


class ErreurSaku(Exception):
    """Erreur de base du module saku."""


class ArchiveInvalide(ErreurSaku):
    """Structure, CRC, bornes, chemin dangereux ou empreinte de fichier fausse."""


class EchecAuthentification(ErreurSaku):
    """Mauvais mot de passe ou archive modifiee."""


class MotDePasseRequis(ErreurSaku):
    """Une archive chiffree est ouverte sans mot de passe."""


class SourceInvalide(ErreurSaku):
    """Fichier a archiver inutilisable : nom non representable, doublon, modifie en cours."""


class FichierAbsent(ErreurSaku):
    """Le chemin demande n'existe pas dans l'archive."""
