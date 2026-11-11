"""Tests de l'archiveur Saku : aller-retour, routage, erreurs, déterminisme."""

from __future__ import annotations

import random
import stat
from pathlib import Path

import pytest
from conftest import ARGON2_RAPIDE, TAILLE_BLOC_TEST

from saku import (
    Archive,
    EchecAuthentification,
    FichierAbsent,
    MotDePasseRequis,
    creer_archive,
)

MOT_DE_PASSE = "mot de passe d'essai"


def _creer(src: Path, dest: Path, *, mot_de_passe: str | None = None) -> None:
    creer_archive(
        dest,
        [src],
        mot_de_passe=mot_de_passe,
        taille_bloc=TAILLE_BLOC_TEST,
        argon2=ARGON2_RAPIDE,
    )


def _verifier_aller_retour(src: Path, dest: Path, *, mot_de_passe: str | None = None) -> None:
    """Extrait l'archive et compare contenu, mode et mtime_ns à l'original."""
    sortie = dest.parent / "sortie"
    with Archive.ouvrir(dest, mot_de_passe) as archive:
        archive.extraire(sortie)
    originaux = {p.relative_to(src).as_posix(): p for p in src.rglob("*") if p.is_file()}
    racine = sortie / src.name
    extraits = {p.relative_to(racine).as_posix(): p for p in racine.rglob("*") if p.is_file()}
    assert set(originaux) == set(extraits)
    for chemin, original in originaux.items():
        extrait = extraits[chemin]
        assert extrait.read_bytes() == original.read_bytes(), f"contenu diffère : {chemin}"
        assert (
            stat.S_IMODE(extrait.stat().st_mode) & 0o777
            == stat.S_IMODE(original.stat().st_mode) & 0o777
        ), f"mode diffère : {chemin}"
        assert extrait.stat().st_mtime_ns == original.stat().st_mtime_ns, (
            f"mtime diffère : {chemin}"
        )


def test_aller_retour_clair(arbre: Path, tmp_path: Path) -> None:
    dest = tmp_path / "archive.saku"
    _creer(arbre, dest)
    _verifier_aller_retour(arbre, dest)


def test_aller_retour_chiffre(arbre: Path, tmp_path: Path) -> None:
    dest = tmp_path / "archive.saku"
    _creer(arbre, dest, mot_de_passe=MOT_DE_PASSE)
    _verifier_aller_retour(arbre, dest, mot_de_passe=MOT_DE_PASSE)


def test_archive_vide(tmp_path: Path) -> None:
    dossier = tmp_path / "vide"
    dossier.mkdir()
    dest = tmp_path / "vide.saku"
    _creer(dossier, dest)
    with Archive.ouvrir(dest) as archive:
        assert archive.fichiers == ()
        archive.verifier()


def test_routage_textes_avant_binaires(arbre: Path, tmp_path: Path) -> None:
    dest = tmp_path / "archive.saku"
    _creer(arbre, dest)
    with Archive.ouvrir(dest) as archive:
        chemins = [f.chemin for f in archive.fichiers]
        # Les textes (vide, md, py, txt) précèdent les binaires (bin, dat).
        # On vérifie que tout texte précède tout binaire.
        est_texte = {
            "projet/vide.txt",
            "projet/LISEZMOI.md",
            "projet/src/principal.py",
            "projet/src/sous dossier/été.py",
            "projet/src/long.txt",
        }
        groupes = [c in est_texte for c in chemins]
        # Tous les True doivent précéder tous les False.
        premier_faux = groupes.index(False) if False in groupes else len(groupes)
        assert not any(groupes[:premier_faux]) or True  # trivial
        # Vérification stricte : une fois un binaire vu, plus aucun texte.
        vu_binaire = False
        for est_t in groupes:
            if not est_t:
                vu_binaire = True
            elif vu_binaire:
                pytest.fail("un texte apparaît après un binaire")


def test_routage_tri_par_extension_et_chemin(arbre: Path, tmp_path: Path) -> None:
    dest = tmp_path / "archive.saku"
    _creer(arbre, dest)
    with Archive.ouvrir(dest) as archive:
        chemins = [f.chemin for f in archive.fichiers]
        est_texte = {
            "projet/vide.txt",
            "projet/LISEZMOI.md",
            "projet/src/principal.py",
            "projet/src/sous dossier/été.py",
            "projet/src/long.txt",
        }
        textes = [c for c in chemins if c in est_texte]
        binaires = [c for c in chemins if c not in est_texte]

        def cle_tri(chemin: str) -> tuple[str, str]:
            ext = chemin.rsplit(".", 1)[-1].lower() if "." in chemin else ""
            return (ext, chemin)

        assert textes == sorted(textes, key=cle_tri), f"textes mal triés : {textes}"
        assert binaires == sorted(binaires, key=cle_tri), f"binaires mal triés : {binaires}"


def test_donnees_aleatoires_repli_codec_zero_clair(tmp_path: Path) -> None:
    alea = random.Random(42)
    src = tmp_path / "src"
    src.mkdir()
    taille = 100_000
    (src / "alea.bin").write_bytes(alea.randbytes(taille))
    dest = tmp_path / "archive.saku"
    _creer(src, dest)
    taille_archive = dest.stat().st_size
    # 1 % + 1 Kio de marge au-dessus de la taille d'origine.
    assert taille_archive <= taille + taille // 100 + 1024, (
        f"archive {taille_archive} o > {taille} o + 1 % + 1 Kio"
    )


def test_donnees_aleatoires_repli_codec_zero_chiffre(tmp_path: Path) -> None:
    alea = random.Random(42)
    src = tmp_path / "src"
    src.mkdir()
    taille = 100_000
    (src / "alea.bin").write_bytes(alea.randbytes(taille))
    dest = tmp_path / "archive.saku"
    _creer(src, dest, mot_de_passe=MOT_DE_PASSE)
    taille_archive = dest.stat().st_size
    assert taille_archive <= taille + taille // 100 + 1024, (
        f"archive {taille_archive} o > {taille} o + 1 % + 1 Kio"
    )


def test_lire_fichier(arbre: Path, tmp_path: Path) -> None:
    dest = tmp_path / "archive.saku"
    _creer(arbre, dest)
    with Archive.ouvrir(dest) as archive:
        contenu = archive.lire("projet/src/principal.py")
        assert contenu == (arbre / "src/principal.py").read_bytes()


def test_lire_chemin_inconnu(arbre: Path, tmp_path: Path) -> None:
    dest = tmp_path / "archive.saku"
    _creer(arbre, dest)
    with Archive.ouvrir(dest) as archive, pytest.raises(FichierAbsent):
        archive.lire("projet/inexistant.txt")


def test_extraction_partielle(arbre: Path, tmp_path: Path) -> None:
    dest = tmp_path / "archive.saku"
    _creer(arbre, dest)
    sortie = tmp_path / "sortie"
    with Archive.ouvrir(dest) as archive:
        archive.extraire(sortie, chemins=["projet/vide.txt", "projet/LISEZMOI.md"])
    extraits = {p.relative_to(sortie).as_posix() for p in sortie.rglob("*") if p.is_file()}
    assert extraits == {"projet/vide.txt", "projet/LISEZMOI.md"}


def test_mauvais_mot_de_passe(arbre: Path, tmp_path: Path) -> None:
    dest = tmp_path / "archive.saku"
    _creer(arbre, dest, mot_de_passe=MOT_DE_PASSE)
    with pytest.raises(EchecAuthentification):
        Archive.ouvrir(dest, "mot de passe erroné")


def test_archive_chiffree_sans_mot_de_passe(arbre: Path, tmp_path: Path) -> None:
    dest = tmp_path / "archive.saku"
    _creer(arbre, dest, mot_de_passe=MOT_DE_PASSE)
    with pytest.raises(MotDePasseRequis):
        Archive.ouvrir(dest)


def test_destination_existante(arbre: Path, tmp_path: Path) -> None:
    dest = tmp_path / "archive.saku"
    dest.write_bytes(b"existant")
    with pytest.raises(FileExistsError):
        _creer(arbre, dest)


def test_deux_archives_chiffrees_differentes(arbre: Path, tmp_path: Path) -> None:
    dest1 = tmp_path / "a1.saku"
    dest2 = tmp_path / "a2.saku"
    _creer(arbre, dest1, mot_de_passe=MOT_DE_PASSE)
    _creer(arbre, dest2, mot_de_passe=MOT_DE_PASSE)
    assert dest1.read_bytes() != dest2.read_bytes(), (
        "deux archives chiffrées des mêmes données avec le même mot de passe doivent différer (sel)"
    )


def test_archive_clair_deterministe(arbre: Path, tmp_path: Path) -> None:
    dest1 = tmp_path / "a1.saku"
    dest2 = tmp_path / "a2.saku"
    _creer(arbre, dest1)
    _creer(arbre, dest2)
    assert dest1.read_bytes() == dest2.read_bytes(), (
        "deux archives claires des mêmes données doivent être identiques au bit près"
    )


@pytest.mark.parametrize(
    ("codec", "id_codec", "mot_de_passe"),
    [("cm", 3, None), ("cm", 3, MOT_DE_PASSE), ("cm1", 2, None)],
    ids=["cm-clair", "cm-chiffre", "cm1-clair"],
)
def test_aller_retour_codec_cm(
    arbre: Path, tmp_path: Path, codec: str, id_codec: int, mot_de_passe: str | None
) -> None:
    dest = tmp_path / "archive.saku"
    creer_archive(
        dest,
        [arbre],
        mot_de_passe=mot_de_passe,
        taille_bloc=TAILLE_BLOC_TEST,
        argon2=ARGON2_RAPIDE,
        codec=codec,
    )
    with Archive.ouvrir(dest, mot_de_passe) as archive:
        codecs = {bloc.entete.id_codec for bloc in archive._blocs}
        archive.verifier()
    assert id_codec in codecs  # le texte passe par le codec choisi ; l'aléatoire est stocké
    _verifier_aller_retour(arbre, dest, mot_de_passe=mot_de_passe)


def test_codec_inconnu_refuse(arbre: Path, tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="codec"):
        creer_archive(tmp_path / "x.saku", [arbre], codec="lzma")


def test_chemins_en_texte(arbre: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """L'exemple du README passe des chemins en texte, pas des Path."""
    monkeypatch.chdir(tmp_path)
    creer_archive("projet.saku", [str(arbre)], taille_bloc=TAILLE_BLOC_TEST)
    with Archive.ouvrir("projet.saku") as archive:
        archive.verifier()
        archive.extraire("sortie")
    assert (tmp_path / "sortie" / arbre.name / "LISEZMOI.md").exists()
