"""Banc de mesure de Saku.

Règle du projet : aucun chiffre sans mesure, et aucun chiffre non vérifié. Chaque outil
compresse puis décompresse le corpus ; le résultat n'est retenu que si la sortie est identique
à l'entrée, octet pour octet. Tout le reste est marqué ÉCHEC ou « non mesuré », avec la raison.

Usage : python bench/bench.py CORPUS [CORPUS...] [--outils a,b] [--echantillon OCTETS]
"""

from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import threading
import time
from pathlib import Path

ICI = Path(__file__).resolve().parent
CMIX = ICI / "externes" / "cmix" / "cmix"
TS_ZIP = ICI / "externes" / "ts_zip" / "ts_zip"
MODELE_TS_ZIP = TS_ZIP.parent / "rwkv_169M_q8.bin"
SAKU = [sys.executable, "-m", "saku"]


@dataclasses.dataclass(frozen=True)
class Outil:
    """Un compresseur à mesurer. Les jetons {entree}, {archive}, {sortie} sont remplacés."""

    nom: str
    compresser: tuple[str, ...]
    decompresser: tuple[str, ...]
    entree: str = "tar"  # "tar" : un seul fichier ; "dossier" : l'arborescence elle-même
    vers_stdout: bool = False  # la commande écrit son résultat sur la sortie standard
    executable: Path | None = None  # outil externe facultatif, lancé depuis son dossier
    modele: Path | None = None  # fichier indispensable au décodeur, compté à part
    environnement: tuple[tuple[str, str], ...] = ()


OUTILS = [
    Outil(
        "zstd-19",
        ("zstd", "-19", "-T1", "-q", "-f", "{entree}", "-o", "{archive}"),
        ("zstd", "-d", "-q", "-f", "{archive}", "-o", "{sortie}"),
    ),
    Outil(
        "zstd-22-long",
        ("zstd", "--ultra", "-22", "--long=27", "-T1", "-q", "-f", "{entree}", "-o", "{archive}"),
        ("zstd", "-d", "--long=27", "-q", "-f", "{archive}", "-o", "{sortie}"),
    ),
    Outil(
        "xz-9",
        ("xz", "-9", "-T1", "-k", "-c", "{entree}"),
        ("xz", "-d", "-c", "{archive}"),
        vers_stdout=True,
    ),
    Outil(
        "saku",
        (*SAKU, "creer", "{archive}", "{entree}"),
        (*SAKU, "extraire", "{archive}", "-C", "{sortie}"),
        entree="dossier",
    ),
    Outil(
        "saku-chiffre",
        (*SAKU, "creer", "--chiffrer", "{archive}", "{entree}"),
        (*SAKU, "extraire", "{archive}", "-C", "{sortie}"),
        entree="dossier",
        environnement=(("SAKU_MOT_DE_PASSE", "banc de mesure"),),
    ),
    Outil(
        "cmix",
        (str(CMIX), "-c", "{entree}", "{archive}"),
        (str(CMIX), "-d", "{archive}", "{sortie}"),
        executable=CMIX,
    ),
    Outil(
        "ts_zip",
        (str(TS_ZIP), "c", "{entree}", "{archive}"),
        (str(TS_ZIP), "d", "{archive}", "{sortie}"),
        executable=TS_ZIP,
        modele=MODELE_TS_ZIP,
    ),
]


def sha256(chemin: Path) -> str:
    empreinte = hashlib.sha256()
    with chemin.open("rb") as flux:
        while morceau := flux.read(1 << 20):
            empreinte.update(morceau)
    return empreinte.hexdigest()


def fichiers_de(dossier: Path) -> list[Path]:
    return sorted(p for p in dossier.rglob("*") if p.is_file() and not p.is_symlink())


def tar_deterministe(dossier: Path, destination: Path) -> None:
    with tarfile.open(destination, "w", format=tarfile.PAX_FORMAT) as tar:
        for chemin in fichiers_de(dossier):
            info = tar.gettarinfo(chemin, arcname=chemin.relative_to(dossier.parent).as_posix())
            info.mtime, info.uid, info.gid, info.uname, info.gname = 0, 0, 0, "", ""
            with chemin.open("rb") as flux:
                tar.addfile(info, flux)


def echantillonner(dossier: Path, destination: Path, octets: int) -> Path:
    """Sous-corpus reproductible : fichiers pris dans l'ordre du SHA-256 de leur chemin."""
    cible = destination / f"{dossier.name}-echantillon"
    shutil.rmtree(cible, ignore_errors=True)
    total = 0
    ordre = sorted(
        fichiers_de(dossier),
        key=lambda p: hashlib.sha256(p.relative_to(dossier).as_posix().encode()).digest(),
    )
    for chemin in ordre:
        if total >= octets:
            break
        copie = cible / chemin.relative_to(dossier)
        copie.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(chemin, copie)
        total += chemin.stat().st_size
    return cible


def executer(commande, sortie: Path | None, outil: Outil, delai: float):
    """Lance la commande ; rend (durée en s, RAM de pointe en Kio) ou lève RuntimeError."""
    depasse = threading.Event()
    environnement = {**os.environ, **dict(outil.environnement)}
    dossier = outil.executable.parent if outil.executable else None
    flux = sortie.open("wb") if sortie else subprocess.DEVNULL
    try:
        debut = time.perf_counter()
        processus = subprocess.Popen(  # commandes fixes de la table OUTILS
            commande, stdout=flux, stderr=subprocess.PIPE, cwd=dossier, env=environnement
        )

        def tuer() -> None:
            depasse.set()
            processus.kill()

        minuterie = threading.Timer(delai, tuer)
        minuterie.start()
        erreurs = processus.stderr.read()
        _, etat, usage = os.wait4(processus.pid, 0)
        duree = time.perf_counter() - debut
        minuterie.cancel()
        processus.returncode = os.waitstatus_to_exitcode(etat)
    finally:
        if sortie:
            flux.close()
    if depasse.is_set():
        raise RuntimeError(f"délai de {delai:.0f} s dépassé")
    if processus.returncode != 0:
        dernier = erreurs.decode(errors="replace").strip().splitlines()[-1:] or [""]
        raise RuntimeError(f"code de retour {processus.returncode} : {dernier[0][:120]}")
    return duree, usage.ru_maxrss


def verifier(outil: Outil, tar: Path, dossier: Path, sortie: Path) -> None:
    if outil.entree == "tar":
        if sha256(sortie) != sha256(tar):
            raise RuntimeError("la sortie décompressée diffère de l'entrée")
        return
    racine = sortie / dossier.name
    attendus, obtenus = fichiers_de(dossier), fichiers_de(racine)
    if [p.relative_to(dossier) for p in attendus] != [p.relative_to(racine) for p in obtenus]:
        raise RuntimeError("la liste des fichiers extraits diffère de l'entrée")
    for original, extrait in zip(attendus, obtenus, strict=True):
        if sha256(original) != sha256(extrait):
            raise RuntimeError(f"contenu différent : {original.relative_to(dossier)}")


def mesurer(outil: Outil, tar: Path, dossier: Path, brut: int, travail: Path, delai: float):
    resultat = {"corpus": dossier.name, "outil": outil.nom, "octets_bruts": brut}
    if outil.executable and not outil.executable.exists():
        return resultat | {"statut": "non mesuré", "raison": "exécutable absent"}
    archive, sortie = travail / f"{dossier.name}.{outil.nom}", travail / f"sortie-{outil.nom}"
    for chemin in (archive, sortie):
        shutil.rmtree(chemin, ignore_errors=True) if chemin.is_dir() else chemin.unlink(True)
    jetons = {
        "entree": str(tar if outil.entree == "tar" else dossier),
        "archive": str(archive),
        "sortie": str(sortie),
    }
    try:
        temps_c, ram_c = executer(
            [a.format(**jetons) for a in outil.compresser],
            archive if outil.vers_stdout else None,
            outil,
            delai,
        )
        temps_d, ram_d = executer(
            [a.format(**jetons) for a in outil.decompresser],
            sortie if outil.vers_stdout else None,
            outil,
            delai,
        )
        verifier(outil, tar, dossier, sortie)
        taille = archive.stat().st_size
    except (RuntimeError, OSError) as erreur:
        return resultat | {"statut": "ÉCHEC", "raison": str(erreur)}
    finally:
        for chemin in (archive, sortie):
            shutil.rmtree(chemin, ignore_errors=True) if chemin.is_dir() else chemin.unlink(True)
    modele = outil.modele.stat().st_size if outil.modele else 0
    return resultat | {
        "statut": "vérifié",
        "octets_archive": taille,
        "octets_modele": modele,
        "bits_par_octet": round(8 * taille / brut, 4),
        "ratio": round(brut / taille, 3),
        "ratio_modele_compris": round(brut / (taille + modele), 4),
        "compression_mo_s": round(brut / 1e6 / temps_c, 4),
        "decompression_mo_s": round(brut / 1e6 / temps_d, 4),
        "ram_compression_mio": round(ram_c / 1024),
        "ram_decompression_mio": round(ram_d / 1024),
    }


def tableau(resultats: list[dict]) -> str:
    lignes = [
        "| Corpus | Outil | Archive (octets) | bits/octet | Ratio | Ratio modèle compris "
        "| Compr. Mo/s | Décompr. Mo/s | RAM compr. Mio | RAM décompr. Mio |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for r in resultats:
        if r["statut"] != "vérifié":
            lignes.append(
                f"| {r['corpus']} | {r['outil']} | {r['statut']} : {r['raison']} |||||||||"
            )
            continue
        lignes.append(
            f"| {r['corpus']} | {r['outil']} | {r['octets_archive']} | {r['bits_par_octet']:.3f} "
            f"| {r['ratio']:.2f} | {r['ratio_modele_compris']:.2f} | {r['compression_mo_s']:.3f} "
            f"| {r['decompression_mo_s']:.3f} | {r['ram_compression_mio']} "
            f"| {r['ram_decompression_mio']} |"
        )
    return "\n".join(lignes)


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument("corpus", nargs="+", type=Path)
    analyseur.add_argument("--sortie", type=Path, default=ICI / "sorties")
    analyseur.add_argument("--outils", default=",".join(o.nom for o in OUTILS))
    analyseur.add_argument("--delai", type=float, default=3600.0, help="secondes par commande")
    analyseur.add_argument("--echantillon", type=int, default=0, help="taille visée en octets")
    analyseur.add_argument("--nom", default="resultats", help="nom du fichier de résultats")
    options = analyseur.parse_args()

    demandes = options.outils.split(",")
    inconnus = set(demandes) - {o.nom for o in OUTILS}
    if inconnus:
        analyseur.error(f"outils inconnus : {', '.join(sorted(inconnus))}")
    travail = options.sortie.resolve()
    travail.mkdir(parents=True, exist_ok=True)

    resultats = []
    for dossier in options.corpus:
        dossier = dossier.resolve()
        if options.echantillon:
            dossier = echantillonner(dossier, travail, options.echantillon)
        fichiers = fichiers_de(dossier)
        brut = sum(p.stat().st_size for p in fichiers)
        tar = travail / f"{dossier.name}.tar"
        tar_deterministe(dossier, tar)
        print(f"# {dossier.name} : {len(fichiers)} fichiers, {brut} octets", file=sys.stderr)
        for outil in (o for o in OUTILS if o.nom in demandes):
            resultat = mesurer(outil, tar, dossier, brut, travail, options.delai)
            resultat["fichiers"] = len(fichiers)
            resultats.append(resultat)
            print(f"  {outil.nom} : {resultat['statut']}", file=sys.stderr)
        tar.unlink()

    rapport = {
        "date": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "machine": {
            "processeur": platform.processor() or platform.machine(),
            "coeurs": os.cpu_count(),
            "systeme": platform.platform(),
            "python": platform.python_version(),
        },
        "resultats": resultats,
    }
    (travail / f"{options.nom}.json").write_text(json.dumps(rapport, ensure_ascii=False, indent=1))
    print(tableau(resultats))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
