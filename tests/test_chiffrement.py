"""Tests du chiffrement authentifie : nonce, aller-retour, rejets, derivation de cle."""

from __future__ import annotations

import hashlib
import struct
import zlib

import pytest
from conftest import ARGON2_RAPIDE, TAILLE_BLOC_TEST

from saku import (
    Archive,
    EchecAuthentification,
    MotDePasseRequis,
    chiffrer_bloc,
    creer_archive,
    dechiffrer_bloc,
    deriver_cle,
    nonce_bloc,
)

MOT_DE_PASSE = "mot de passe d'essai"
SEL = b"\x00" * 16
AAD = b"\x00" * 40


# --------------------------------------------------------------------------- nonce


@pytest.mark.parametrize(
    ("numero", "est_index", "attendu"),
    [
        (0, False, b"\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"),
        (1, False, b"\x01\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00\x00"),
        (2**40, True, b"\x00\x00\x00\x00\x00\x01\x00\x00\x00\x00\x00\x01"),
    ],
)
def test_nonce_valeurs_exactes(numero: int, est_index: bool, attendu: bytes) -> None:
    assert nonce_bloc(numero, est_index) == attendu


def test_nonce_unicite_sur_mille_numeros() -> None:
    nonces = [nonce_bloc(n, False) for n in range(1000)]
    assert len(set(nonces)) == 1000


# --------------------------------------------------------------------------- aller-retour


def test_aller_retour_chiffrement() -> None:
    cle = deriver_cle(MOT_DE_PASSE, SEL, ARGON2_RAPIDE)
    clair = b"contenu de test"
    charge = chiffrer_bloc(cle, 0, False, clair, AAD)
    assert charge != clair
    assert dechiffrer_bloc(cle, 0, False, charge, AAD) == clair


# --------------------------------------------------------------------------- rejets


def _corrompre(octets: bytes, position: int) -> bytes:
    """Retourne une copie d'octets avec un bit change a la position donnee."""
    copie = bytearray(octets)
    copie[position] ^= 0x01
    return bytes(copie)


def _archive_chiffree(tmp_path, mot_de_passe: str = MOT_DE_PASSE) -> bytes:
    """Cree une petite archive chiffree et retourne ses octets."""
    import random

    alea = random.Random(42)
    dossier = tmp_path / "src"
    dossier.mkdir()
    (dossier / "a.txt").write_bytes(alea.randbytes(TAILLE_BLOC_TEST))
    (dossier / "b.txt").write_bytes(alea.randbytes(TAILLE_BLOC_TEST))
    archive = tmp_path / "test.saku"
    creer_archive(
        archive,
        [dossier],
        mot_de_passe=mot_de_passe,
        taille_bloc=TAILLE_BLOC_TEST,
        argon2=ARGON2_RAPIDE,
    )
    return archive.read_bytes()


def _entete_archive(octets: bytes) -> bytes:
    return octets[:80]


def _entete_bloc(octets: bytes, position: int) -> bytes:
    return octets[position : position + 16]


def _aad(octets: bytes, position: int) -> bytes:
    return hashlib.sha256(_entete_archive(octets)).digest() + _entete_bloc(octets, position)[:12]


def _position_premier_bloc(octets: bytes) -> int:
    return 80


def _position_index(octets: bytes) -> int:
    (position,) = struct.unpack_from("<Q", octets, len(octets) - 16)
    return position


def test_rejet_bit_charge_modifiee(tmp_path) -> None:
    octets = bytearray(_archive_chiffree(tmp_path))
    position = _position_premier_bloc(bytes(octets))
    (taille_charge,) = struct.unpack_from("<I", octets, position + 8)
    debut = position + 16
    octets[debut] ^= 0x01
    # CRC recalcule : seule l'etiquette AEAD peut encore detecter la modification.
    struct.pack_into("<I", octets, position + 12, zlib.crc32(octets[debut : debut + taille_charge]))
    with (
        Archive.ouvrir(_ecrire(tmp_path, bytes(octets)), MOT_DE_PASSE) as archive,
        pytest.raises(EchecAuthentification),
    ):
        archive.verifier()


def test_entete_modifie_casse_l_authentification(tmp_path) -> None:
    """L'en-tete entre dans l'AAD : le modifier (CRC refait) invalide tous les blocs."""
    octets = bytearray(_archive_chiffree(tmp_path))
    struct.pack_into("<I", octets, 64, 2 * TAILLE_BLOC_TEST)  # taille_bloc
    struct.pack_into("<I", octets, 76, zlib.crc32(octets[:76]))
    with pytest.raises(EchecAuthentification):
        Archive.ouvrir(_ecrire(tmp_path, bytes(octets)), MOT_DE_PASSE)


@pytest.mark.parametrize(
    ("numero", "est_index", "aad", "cle"),
    [
        (8, False, b"aad", bytes(32)),  # autre numero de bloc
        (7, True, b"aad", bytes(32)),  # autre role
        (7, False, b"AAD", bytes(32)),  # autres donnees associees
        (7, False, b"aad", bytes([1]) * 32),  # autre cle
    ],
)
def test_dechiffrement_refuse_tout_parametre_different(numero, est_index, aad, cle) -> None:
    chiffre = chiffrer_bloc(bytes(32), 7, False, b"contenu clair", b"aad")
    assert dechiffrer_bloc(bytes(32), 7, False, chiffre, b"aad") == b"contenu clair"
    with pytest.raises(EchecAuthentification):
        dechiffrer_bloc(cle, numero, est_index, chiffre, aad)


def test_rejet_numero_bloc_modifie(tmp_path) -> None:
    octets = _archive_chiffree(tmp_path)
    position = _position_premier_bloc(octets)
    entete_bloc = _entete_bloc(octets, position)
    (taille_charge,) = struct.unpack_from("<I", entete_bloc, 8)
    debut_charge = position + 16
    cle = deriver_cle(MOT_DE_PASSE, octets[16:32], ARGON2_RAPIDE)
    aad = _aad(octets, position)
    charge = octets[debut_charge : debut_charge + taille_charge]
    # Re-chiffrer avec le mauvais numéro (1 au lieu de 0)
    charge_fausse = chiffrer_bloc(cle, 1, False, dechiffrer_bloc(cle, 0, False, charge, aad), aad)
    octets_corrompus = bytearray(octets)
    octets_corrompus[debut_charge : debut_charge + taille_charge] = charge_fausse
    # Recalculer CRC charge
    crc = (
        zlib.crc32(bytes(octets_corrompus[debut_charge : debut_charge + taille_charge]))
        & 0xFFFFFFFF
    )
    struct.pack_into("<I", octets_corrompus, position + 12, crc)
    with pytest.raises(EchecAuthentification):
        Archive.ouvrir(_ecrire(tmp_path, bytes(octets_corrompus)), MOT_DE_PASSE)
        archive = Archive.ouvrir(_ecrire(tmp_path, bytes(octets_corrompus)), MOT_DE_PASSE)
        archive.verifier()


def test_rejet_drapeau_index_modifie(tmp_path) -> None:
    octets = _archive_chiffree(tmp_path)
    position = _position_index(octets)
    entete_bloc = _entete_bloc(octets, position)
    (taille_charge,) = struct.unpack_from("<I", entete_bloc, 8)
    debut_charge = position + 16
    cle = deriver_cle(MOT_DE_PASSE, octets[16:32], ARGON2_RAPIDE)
    aad = _aad(octets, position)
    charge = octets[debut_charge : debut_charge + taille_charge]
    # Re-chiffrer avec est_index=False au lieu de True
    charge_fausse = chiffrer_bloc(cle, 0, False, dechiffrer_bloc(cle, 0, True, charge, aad), aad)
    octets_corrompus = bytearray(octets)
    octets_corrompus[debut_charge : debut_charge + taille_charge] = charge_fausse
    crc = (
        zlib.crc32(bytes(octets_corrompus[debut_charge : debut_charge + taille_charge]))
        & 0xFFFFFFFF
    )
    struct.pack_into("<I", octets_corrompus, position + 12, crc)
    with pytest.raises(EchecAuthentification):
        Archive.ouvrir(_ecrire(tmp_path, bytes(octets_corrompus)), MOT_DE_PASSE)
        archive = Archive.ouvrir(_ecrire(tmp_path, bytes(octets_corrompus)), MOT_DE_PASSE)
        archive.verifier()


def test_rejet_cle_differente(tmp_path) -> None:
    octets = _archive_chiffree(tmp_path)
    with pytest.raises(EchecAuthentification):
        Archive.ouvrir(_ecrire(tmp_path, octets), "autre mot de passe")


def test_mot_de_passe_vide_refuse(tmp_path) -> None:
    dossier = tmp_path / "src"
    dossier.mkdir()
    (dossier / "a.txt").write_bytes(b"test")
    with pytest.raises(MotDePasseRequis):
        creer_archive(tmp_path / "test.saku", [dossier], mot_de_passe="", argon2=ARGON2_RAPIDE)


def test_derivation_deterministe() -> None:
    cle1 = deriver_cle(MOT_DE_PASSE, SEL, ARGON2_RAPIDE)
    cle2 = deriver_cle(MOT_DE_PASSE, SEL, ARGON2_RAPIDE)
    assert cle1 == cle2
    assert len(cle1) == 32


def test_derivation_sensible_au_sel() -> None:
    cle1 = deriver_cle(MOT_DE_PASSE, SEL, ARGON2_RAPIDE)
    sel_autre = b"\x01" * 16
    cle2 = deriver_cle(MOT_DE_PASSE, sel_autre, ARGON2_RAPIDE)
    assert cle1 != cle2


def _ecrire(tmp_path, octets: bytes):
    chemin = tmp_path / "corrompu.saku"
    chemin.write_bytes(octets)
    return chemin
