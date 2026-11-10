"""Ligne de commande de Saku : creer, extraire, lister, verifier."""

from __future__ import annotations

import argparse
import getpass
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from .archive import Archive, creer_archive
from .erreurs import ErreurSaku, MotDePasseRequis


def _demander_mot_de_passe(confirmer: bool = False) -> str:
    """Demande le mot de passe via getpass ou variable d'environnement."""
    env = os.environ.get("SAKU_MOT_DE_PASSE")
    if env is not None:
        return env
    mot = getpass.getpass("Mot de passe: ")
    if confirmer:
        mot2 = getpass.getpass("Confirmation: ")
        if mot != mot2:
            raise ErreurSaku("Les mots de passe ne correspondent pas")
    return mot


def _ouvrir_archive(chemin: Path) -> Archive:
    """Ouvre une archive, en demandant le mot de passe seulement si elle est chiffree."""
    try:
        return Archive.ouvrir(chemin)
    except MotDePasseRequis:
        return Archive.ouvrir(chemin, _demander_mot_de_passe())


def main(argv: Sequence[str] | None = None) -> int:
    """Point d'entree CLI."""
    parser = argparse.ArgumentParser(prog="saku", description="Archiveur saku")
    sous = parser.add_subparsers(dest="commande", required=True)

    p_creer = sous.add_parser("creer", help="Creer une archive")
    p_creer.add_argument("archive", type=Path)
    p_creer.add_argument("sources", nargs="+", type=Path)
    p_creer.add_argument("--chiffrer", action="store_true", help="demande un mot de passe")
    p_creer.add_argument("--niveau", type=int, default=19)

    p_extraire = sous.add_parser("extraire", help="Extraire une archive")
    p_extraire.add_argument("archive", type=Path)
    p_extraire.add_argument("-C", type=Path, default=Path("."), metavar="DOSSIER")
    p_extraire.add_argument("chemins", nargs="*")

    p_lister = sous.add_parser("lister", help="Lister les fichiers")
    p_lister.add_argument("archive", type=Path)

    p_verifier = sous.add_parser("verifier", help="Verifier une archive")
    p_verifier.add_argument("archive", type=Path)

    args = parser.parse_args(argv)

    try:
        if args.commande == "creer":
            mot_de_passe = None
            if args.chiffrer:
                mot_de_passe = _demander_mot_de_passe(confirmer=True)
            creer_archive(
                args.archive,
                args.sources,
                mot_de_passe=mot_de_passe,
                niveau=args.niveau,
            )
        elif args.commande == "extraire":
            with _ouvrir_archive(args.archive) as archive:
                archive.extraire(args.C, args.chemins or None)
        elif args.commande == "lister":
            with _ouvrir_archive(args.archive) as archive:
                for f in archive.fichiers:
                    print(f"{f.taille:>12}  {f.chemin}")
        elif args.commande == "verifier":
            with _ouvrir_archive(args.archive) as archive:
                archive.verifier()
                print(f"archive valide : {len(archive.fichiers)} fichier(s)")
    except (ErreurSaku, OSError, ValueError) as exc:
        print(f"saku : {exc}", file=sys.stderr)
        return 1
    return 0
