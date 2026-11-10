"""Tests de la ligne de commande de Saku."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
from conftest import ARGON2_RAPIDE, TAILLE_BLOC_TEST, contenus_de

from saku import creer_archive
from saku.cli import main


def _creer_archive_claire(chemin: Path, sources: list[Path]) -> None:
    """Fabrique une archive non chiffree avec des blocs de 4096 o."""
    creer_archive(chemin, sources, taille_bloc=TAILLE_BLOC_TEST)


def _creer_archive_chiffree(chemin: Path, sources: list[Path], mot_de_passe: str) -> None:
    """Fabrique une archive chiffree avec des parametres Argon2 rapides."""
    creer_archive(
        chemin,
        sources,
        mot_de_passe=mot_de_passe,
        taille_bloc=TAILLE_BLOC_TEST,
        argon2=ARGON2_RAPIDE,
    )


def _corrompre_archive(chemin: Path) -> None:
    """Corrompt un octet de la charge du premier bloc de donnees."""
    octets = bytearray(chemin.read_bytes())
    # Le premier bloc de donnees commence a 80 (en-tete de bloc 16 o).
    # On modifie un octet de la charge (decalage 80 + 16 + 1).
    octets[80 + 16 + 1] ^= 0xFF
    chemin.write_bytes(bytes(octets))


def test_creer_lister_verifier_extraire_claire(tmp_path: Path, arbre: Path, capsys: object) -> None:
    """Creer, lister, verifier et extraire une archive non chiffree."""
    archive = tmp_path / "test.saku"

    # Creer : code 0, pas de sortie
    code = main(["creer", str(archive), str(arbre)])
    assert code == 0
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err == ""

    # Lister : code 0, liste les fichiers
    code = main(["lister", str(archive)])
    assert code == 0
    out = capsys.readouterr()
    lignes = out.out.strip().splitlines()
    assert len(lignes) > 0
    # Chaque ligne doit contenir un chemin de fichier
    for ligne in lignes:
        assert "  " in ligne  # taille + chemin separes par des espaces

    # Verifier : code 0, message de validation
    code = main(["verifier", str(archive)])
    assert code == 0
    out = capsys.readouterr()
    assert "archive valide" in out.out

    # Extraire : code 0, fichiers recreees
    dest = tmp_path / "extraite"
    code = main(["extraire", str(archive), "-C", str(dest)])
    assert code == 0
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err == ""

    # Verifier que les fichiers extraits correspondent
    contenus_originaux = contenus_de(arbre)
    contenus_extraits = contenus_de(dest / "projet")
    assert contenus_originaux == contenus_extraits


def test_cycle_chiffre_par_variable_env(
    tmp_path: Path, arbre: Path, monkeypatch: object, capsys: object
) -> None:
    """Cycle complet chiffree via SAKU_MOT_DE_PASSE."""
    mot_de_passe = "mot-de-passe-test"
    monkeypatch.setenv("SAKU_MOT_DE_PASSE", mot_de_passe)

    archive = tmp_path / "chiffre.saku"
    _creer_archive_chiffree(archive, [arbre], mot_de_passe)

    # Lister : code 0
    code = main(["lister", str(archive)])
    assert code == 0
    out = capsys.readouterr()
    assert len(out.out.strip().splitlines()) > 0

    # Verifier : code 0
    code = main(["verifier", str(archive)])
    assert code == 0
    out = capsys.readouterr()
    assert "archive valide" in out.out

    # Extraire : code 0, fichiers corrects
    dest = tmp_path / "extraite_chiffree"
    code = main(["extraire", str(archive), "-C", str(dest)])
    assert code == 0
    out = capsys.readouterr()
    assert out.out == ""
    assert out.err == ""

    contenus_originaux = contenus_de(arbre)
    contenus_extraits = contenus_de(dest / "projet")
    assert contenus_originaux == contenus_extraits


def test_archive_corrompue_code_1_stderr_pas_traceback(
    tmp_path: Path, arbre: Path, capsys: object
) -> None:
    """Une archive corrompue donne code 1, une ligne sur stderr, pas de Traceback."""
    archive = tmp_path / "corrompu.saku"
    _creer_archive_claire(archive, [arbre])
    _corrompre_archive(archive)

    code = main(["verifier", str(archive)])
    assert code == 1
    out = capsys.readouterr()
    # Une seule ligne sur stderr
    lignes_stderr = out.err.strip().splitlines()
    assert len(lignes_stderr) == 1
    # Pas de Traceback
    assert "Traceback" not in out.err
    # Le message doit etre utile
    assert (
        "saku" in out.err.lower() or "corrompu" in out.err.lower() or "invalide" in out.err.lower()
    )


def test_mot_de_passe_pas_accepte_par_option_cli(
    tmp_path: Path, arbre: Path, monkeypatch: object, capsys: object
) -> None:
    """Le mot de passe n'est pas accepte par aucune option de ligne de commande."""
    # Essayer de passer un mot de passe comme option inconnue
    archive = tmp_path / "test.saku"
    _creer_archive_claire(archive, [arbre])

    # --mot-de-passe n'existe pas
    # argparse doit rejeter l'option inconnue -> SystemExit(2)
    # On utilise pytest.raises pour SystemExit
    with pytest.raises(SystemExit) as exc_info:
        main(["lister", str(archive), "--mot-de-passe", "secret"])
    assert exc_info.value.code == 2  # erreur argparse

    # Tester que --chiffrer ne prend pas de valeur
    with pytest.raises(SystemExit) as exc_info:
        main(["creer", str(tmp_path / "x.saku"), str(arbre), "--chiffrer", "secret"])
    assert exc_info.value.code == 2


def test_module_executable(tmp_path: Path) -> None:
    """`python -m saku` doit réellement lancer la commande (régression du banc de mesure)."""
    source = tmp_path / "donnees"
    source.mkdir()
    (source / "a.txt").write_text("bonjour\n")
    archive = tmp_path / "a.saku"
    subprocess.run([sys.executable, "-m", "saku", "creer", str(archive), str(source)], check=True)
    resultat = subprocess.run(
        [sys.executable, "-m", "saku", "verifier", str(archive)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert "1 fichier" in resultat.stdout
