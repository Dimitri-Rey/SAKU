"""Tests adverses : corruption, index hostile, liens symboliques, empreintes, modes."""

from __future__ import annotations

import json
import stat
import struct
from pathlib import Path

import pytest
from conftest import (
    TAILLE_BLOC_TEST,
    TAILLE_ENTETE,
    TAILLE_ENTETE_BLOC,
    TAILLE_PIED,
    lire_index,
    remplacer_index,
)

from saku import Archive, ArchiveInvalide, ErreurSaku, ParametresArgon2, creer_archive

MOT_DE_PASSE = "mot-de-passe-test"


def _fabrique_archive(tmp_path: Path, arbre: Path, chiffree: bool) -> Path:
    """Crée une archive (chiffrée ou non) à partir de l'arbre de test."""
    destination = tmp_path / ("archive.saku" if not chiffree else "archive_chiffree.saku")
    creer_archive(
        destination,
        [arbre],
        mot_de_passe=MOT_DE_PASSE if chiffree else None,
        taille_bloc=TAILLE_BLOC_TEST,
        argon2=ParametresArgon2(passes=1, parallelisme=1, memoire_kio=8192) if chiffree else None,
    )
    return destination


def _inverser_bit(octets: bytearray, position: int) -> None:
    octets[position] ^= 1


def _positions_corruption(octets: bytes) -> list[int]:
    """Toutes les positions si < 3000 octets, sinon un pas régulier."""
    n = len(octets)
    if n < 3000:
        return list(range(n))
    pas = max(1, n // 3000)
    return list(range(0, n, pas))


@pytest.mark.parametrize("chiffree", [False, True], ids=["clair", "chiffree"])
def test_corruption_bit_a_bit(tmp_path: Path, arbre: Path, chiffree: bool) -> None:
    """Inverser un bit à chaque position : soit ErreurSaku, soit (clair) contenu identique."""
    archive = _fabrique_archive(tmp_path, arbre, chiffree)
    octets_originaux = archive.read_bytes()
    positions = _positions_corruption(octets_originaux)
    attendus = {
        p.relative_to(arbre.parent).as_posix(): p.read_bytes()
        for p in arbre.rglob("*")
        if p.is_file()
    }

    for position in positions:
        corrompu = bytearray(octets_originaux)
        _inverser_bit(corrompu, position)
        chemin_corrompu = tmp_path / f"corrompu_{position}.saku"
        chemin_corrompu.write_bytes(bytes(corrompu))

        try:
            with Archive.ouvrir(chemin_corrompu, MOT_DE_PASSE if chiffree else None) as arch:
                arch.verifier()
                contenus = {f.chemin: arch.lire(f.chemin) for f in arch.fichiers}
        except ErreurSaku:
            continue  # corruption détectée, à l'ouverture ou à la vérification
        finally:
            chemin_corrompu.unlink()
        # Aucune erreur : toléré seulement en clair, et seulement si rien n'a changé.
        assert not chiffree, f"Octet {position} : archive chiffrée acceptée après corruption"
        assert contenus == attendus, f"Octet {position} : contenu faux rendu sans erreur"


@pytest.mark.parametrize("chiffree", [False, True], ids=["clair", "chiffree"])
def test_troncature(tmp_path: Path, arbre: Path, chiffree: bool) -> None:
    """Tronquer l'archive à chaque longueur (pas régulier) : ErreurSaku."""
    archive = _fabrique_archive(tmp_path, arbre, chiffree)
    octets = archive.read_bytes()
    n = len(octets)
    pas = max(1, n // 3000)

    for longueur in range(0, n, pas):
        tronque = tmp_path / f"tronque_{longueur}.saku"
        tronque.write_bytes(octets[:longueur])
        with pytest.raises(ErreurSaku):
            Archive.ouvrir(tronque, MOT_DE_PASSE if chiffree else None)


@pytest.mark.parametrize("chiffree", [False, True], ids=["clair", "chiffree"])
def test_octets_ajoutes_fin(tmp_path: Path, arbre: Path, chiffree: bool) -> None:
    """Ajouter des octets à la fin : ErreurSaku."""
    archive = _fabrique_archive(tmp_path, arbre, chiffree)
    octets = archive.read_bytes()
    modifie = tmp_path / "ajoute.saku"
    modifie.write_bytes(octets + b"\x00" * 16)
    with pytest.raises(ErreurSaku):
        Archive.ouvrir(modifie, MOT_DE_PASSE if chiffree else None)


def test_echange_blocs_chiffree(tmp_path: Path, arbre: Path) -> None:
    """Échanger deux blocs de données de même taille dans une archive chiffrée : ErreurSaku."""
    archive = _fabrique_archive(tmp_path, arbre, True)
    octets = bytearray(archive.read_bytes())

    # lire_index ne marche que sur une archive NON chiffrée.
    # Sur une archive chiffrée, on parcourt le fichier pour trouver les blocs.
    # L'index est le dernier bloc, juste avant le pied.
    (position_index,) = struct.unpack_from("<Q", octets, len(octets) - TAILLE_PIED)

    # Trouver les positions des blocs de données en parcourant depuis le début
    positions_blocs = []
    pos = TAILLE_ENTETE
    while pos < position_index:
        positions_blocs.append(pos)
        (taille_charge,) = struct.unpack_from("<I", octets, pos + 8)
        pos += TAILLE_ENTETE_BLOC + taille_charge

    if len(positions_blocs) < 2:
        pytest.fail("le jeu d'essai doit produire au moins deux blocs")

    # Choisir deux blocs consécutifs de même taille_charge.
    i, j = None, None
    for a in range(len(positions_blocs)):
        for b in range(a + 1, len(positions_blocs)):
            taille_charge_a = struct.unpack_from("<I", octets, positions_blocs[a] + 8)[0]
            taille_charge_b = struct.unpack_from("<I", octets, positions_blocs[b] + 8)[0]
            if taille_charge_a == taille_charge_b:
                i, j = a, b
                break
        if i is not None:
            break

    if i is None:
        pytest.fail("le jeu d'essai doit contenir deux blocs de même taille")

    pos_i = positions_blocs[i]
    pos_j = positions_blocs[j]
    taille_charge_i = struct.unpack_from("<I", octets, pos_i + 8)[0]
    taille_charge_j = struct.unpack_from("<I", octets, pos_j + 8)[0]

    if taille_charge_i != taille_charge_j:
        pytest.skip("Tailles de charge différentes")

    # Échanger les charges (en-têtes de bloc + charge).
    taille_total_i = TAILLE_ENTETE_BLOC + taille_charge_i
    taille_total_j = TAILLE_ENTETE_BLOC + taille_charge_j

    bloc_i = bytes(octets[pos_i : pos_i + taille_total_i])
    bloc_j = bytes(octets[pos_j : pos_j + taille_total_j])

    octets[pos_i : pos_i + taille_total_i] = bloc_j
    octets[pos_j : pos_j + taille_total_j] = bloc_i

    chemin = tmp_path / "echange.saku"
    chemin.write_bytes(bytes(octets))
    # Les en-têtes échangés sont identiques (hors CRC) : l'ouverture peut passer, c'est le
    # numéro de bloc lié au nonce qui doit faire échouer la vérification.
    with pytest.raises(ErreurSaku), Archive.ouvrir(chemin, MOT_DE_PASSE) as arch:
        arch.verifier()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda idx: _muter_chemin(idx, "../evasion"),
        lambda idx: _muter_chemin(idx, "/tmp/x"),
        lambda idx: _muter_chemin(idx, "a//b"),
        lambda idx: _muter_chemin(idx, "a/./b"),
        lambda idx: _muter_chemin(idx, "a\\b"),
        lambda idx: _muter_doublon(idx),
        lambda idx: _muter_taille_negatif(idx),
        lambda idx: _muter_tailles_incoherentes(idx),
        lambda idx: _muter_position_hors_fichier(idx),
        lambda idx: _muter_taille_claire_superieure(idx),
    ],
    ids=[
        "evasion",
        "absolu",
        "double-slash",
        "point",
        "antislash",
        "doublon",
        "taille-negatif",
        "tailles-incoherentes",
        "position-hors-fichier",
        "taille-claire-superieure",
    ],
)
def test_index_hostile(tmp_path: Path, arbre: Path, mutation) -> None:
    """Index hostile : ArchiveInvalide dès l'ouverture, rien n'est écrit hors de la destination."""
    archive = _fabrique_archive(tmp_path, arbre, False)
    octets = archive.read_bytes()
    index = lire_index(octets)
    index_muté = mutation(index)
    archive_hostile = remplacer_index(octets, index_muté)
    chemin = tmp_path / "hostile.saku"
    chemin.write_bytes(archive_hostile)

    with pytest.raises(ArchiveInvalide), Archive.ouvrir(chemin) as arch:
        arch.extraire(tmp_path / "sortie")

    # Rien n'est écrit hors de la destination.
    sortie = tmp_path / "sortie"
    if sortie.exists():
        fichiers = list(sortie.rglob("*"))
        assert not fichiers, "Des fichiers ont été écrits dans la destination"


def _muter_chemin(index: dict, mauvais_chemin: str) -> dict:
    """Remplace le premier chemin par un chemin dangereux."""
    index = json.loads(json.dumps(index))
    if index["fichiers"]:
        index["fichiers"][0]["chemin"] = mauvais_chemin
    return index


def _muter_doublon(index: dict) -> dict:
    """Crée un doublon de chemin."""
    index = json.loads(json.dumps(index))
    if len(index["fichiers"]) >= 2:
        index["fichiers"][1]["chemin"] = index["fichiers"][0]["chemin"]
    return index


def _muter_taille_negatif(index: dict) -> dict:
    """Rend une taille négative."""
    index = json.loads(json.dumps(index))
    if index["fichiers"]:
        index["fichiers"][0]["taille"] = -1
    return index


def _muter_tailles_incoherentes(index: dict) -> dict:
    """Rend la somme des tailles incohérente avec les blocs."""
    index = json.loads(json.dumps(index))
    if index["fichiers"]:
        index["fichiers"][0]["taille"] += 1
    return index


def _muter_position_hors_fichier(index: dict) -> dict:
    """Rend une position hors du fichier."""
    index = json.loads(json.dumps(index))
    if index["blocs"]:
        index["blocs"][0]["position"] = 10**9
    return index


def _muter_taille_claire_superieure(index: dict) -> dict:
    """Rend taille_claire supérieure à taille_bloc."""
    index = json.loads(json.dumps(index))
    if index["blocs"]:
        index["blocs"][0]["taille_claire"] = TAILLE_BLOC_TEST + 1
    return index


def test_lien_symbolique_piege(tmp_path: Path, arbre: Path) -> None:
    """Lien symbolique piégé : extraire un fichier à travers un lien doit lever une erreur."""
    archive = _fabrique_archive(tmp_path, arbre, False)
    destination = tmp_path / "dest"
    destination.mkdir()

    # Créer un lien symbolique pointant hors de la destination.
    ailleurs = tmp_path / "ailleurs"
    ailleurs.mkdir()
    (destination / "projet").symlink_to(ailleurs)

    with pytest.raises(ErreurSaku), Archive.ouvrir(archive) as arch:
        arch.extraire(destination, ["projet/src/principal.py"])

    # Rien n'est écrit dans /ailleurs.
    assert not list(ailleurs.rglob("*")), (
        "Des fichiers ont été écrits dans le dossier cible du lien"
    )


def test_sha256_faux(tmp_path: Path, arbre: Path) -> None:
    """SHA-256 faux dans l'index : erreur à lire, extraire et verifier, aucun fichier définitif."""
    archive = _fabrique_archive(tmp_path, arbre, False)
    octets = archive.read_bytes()
    index = lire_index(octets)

    # Corrompre le SHA-256 du premier fichier.
    index = json.loads(json.dumps(index))
    if index["fichiers"]:
        index["fichiers"][0]["sha256"] = "0" * 64

    archive_fausse = remplacer_index(octets, index)
    chemin = tmp_path / "faux_sha.saku"
    chemin.write_bytes(archive_fausse)

    # lire doit lever une erreur.
    with pytest.raises(ErreurSaku), Archive.ouvrir(chemin) as arch:
        arch.lire(arch.fichiers[0].chemin)

    # verifier doit lever une erreur.
    with pytest.raises(ErreurSaku), Archive.ouvrir(chemin) as arch:
        arch.verifier()

    # extraire doit lever une erreur et ne laisser aucun fichier définitif.
    destination = tmp_path / "sortie_sha"
    with pytest.raises(ErreurSaku), Archive.ouvrir(chemin) as arch:
        arch.extraire(destination)

    if destination.exists():
        fichiers_definitifs = [
            p for p in destination.rglob("*") if p.is_file() and not p.name.startswith(".saku-")
        ]
        assert not fichiers_definitifs, "Des fichiers définitifs ont été laissés par extraire"


def test_bits_mode_setuid(tmp_path: Path, arbre: Path) -> None:
    """Un fichier archivé avec setuid est extrait en 0o755 (seuls les bits 0o777 sont appliqués)."""
    archive = _fabrique_archive(tmp_path, arbre, False)
    octets = archive.read_bytes()
    index = lire_index(octets)

    # Trouver un fichier et lui attribuer un mode setuid.
    index = json.loads(json.dumps(index))
    if index["fichiers"]:
        index["fichiers"][0]["mode"] = 0o4755

    archive_setuid = remplacer_index(octets, index)
    chemin = tmp_path / "setuid.saku"
    chemin.write_bytes(archive_setuid)

    destination = tmp_path / "sortie_setuid"
    with Archive.ouvrir(chemin) as arch:
        arch.extraire(destination)

    # Vérifier que le mode est 0o755 (setuid effacé).
    fichier_extrait = destination / index["fichiers"][0]["chemin"]
    mode = stat.S_IMODE(fichier_extrait.stat().st_mode)
    assert mode == 0o755, f"Mode attendu 0o755, obtenu {oct(mode)}"
