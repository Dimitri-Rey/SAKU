"""Tests du format binaire : aller-retour, tailles, décalages et rejets."""

from __future__ import annotations

import struct
import zlib

import pytest
from conftest import TAILLE_BLOC_TEST

from saku import (
    ArchiveInvalide,
    EnTete,
    EnTeteBloc,
    pied_depuis_octets,
    pied_vers_octets,
)

# --------------------------------------------------------------------------- constantes


def _entete_base(**mots) -> EnTete:
    """Un en-tete valide non chiffre, surchargeable."""
    base = dict(
        version=0,
        chiffree=False,
        id_aead=0,
        id_kdf=0,
        argon2_passes=0,
        argon2_parallelisme=0,
        argon2_memoire_kio=0,
        sel=b"\x00" * 16,
        empreinte_modele=b"\x00" * 32,
        taille_bloc=TAILLE_BLOC_TEST,
    )
    base.update(mots)
    return EnTete(**base)


def _octets_entete(**mots) -> bytes:
    return _entete_base(**mots).vers_octets()


def _bloc_base(**mots) -> EnTeteBloc:
    base = dict(type=1, id_codec=1, taille_claire=100, taille_charge=80, crc_charge=0)
    base.update(mots)
    return EnTeteBloc(**base)


def _pied_base(position: int = 80) -> bytes:
    return pied_vers_octets(position)


# --------------------------------------------------------------------------- aller-retour


def test_aller_retour_entete():
    entete = _entete_base(taille_bloc=8192)
    octets = entete.vers_octets()
    assert EnTete.depuis_octets(octets) == entete


def test_aller_retour_entete_chiffree():
    sel = b"\x01" * 16
    entete = _entete_base(
        chiffree=True,
        id_aead=1,
        id_kdf=1,
        argon2_passes=1,
        argon2_parallelisme=1,
        argon2_memoire_kio=8192,
        sel=sel,
    )
    assert EnTete.depuis_octets(entete.vers_octets()) == entete


def test_aller_retour_entete_bloc():
    bloc = _bloc_base(crc_charge=0xDEADBEEF)
    assert EnTeteBloc.depuis_octets(bloc.vers_octets()) == bloc


def test_aller_retour_pied():
    assert pied_depuis_octets(_pied_base(12345)) == 12345


# --------------------------------------------------------------------------- tailles exactes


def test_taille_entete_80():
    assert len(_octets_entete()) == 80


def test_taille_entete_bloc_16():
    assert len(_bloc_base().vers_octets()) == 16


def test_taille_pied_16():
    assert len(_pied_base()) == 16


# ----------------------------------------------------------- decalages octet par octet


def test_decalages_entete_non_chiffre():
    octets = _octets_entete(taille_bloc=4096)
    assert octets[0:6] == b"SAKU\x00\x00"
    assert octets[6] == 0
    assert octets[7] == 0
    assert octets[8] == 0
    assert octets[9] == 0
    assert octets[10] == 0
    assert octets[11] == 0
    assert struct.unpack_from("<I", octets, 12)[0] == 0
    assert octets[16:32] == b"\x00" * 16
    assert octets[32:64] == b"\x00" * 32
    assert struct.unpack_from("<I", octets, 64)[0] == 4096
    assert octets[68:76] == b"\x00" * 8
    assert struct.unpack_from("<I", octets, 76)[0] == zlib.crc32(octets[0:76]) & 0xFFFFFFFF


def test_decalages_entete_chiffre():
    sel = bytes(range(16))
    empreinte = bytes(range(32))
    octets = _octets_entete(
        chiffree=True,
        id_aead=1,
        id_kdf=1,
        argon2_passes=3,
        argon2_parallelisme=4,
        argon2_memoire_kio=262144,
        sel=sel,
        empreinte_modele=empreinte,
        taille_bloc=8 * 1024 * 1024,
    )
    assert octets[0:6] == b"SAKU\x00\x00"
    assert octets[6] == 0
    assert octets[7] == 1
    assert octets[8] == 1
    assert octets[9] == 1
    assert octets[10] == 3
    assert octets[11] == 4
    assert struct.unpack_from("<I", octets, 12)[0] == 262144
    assert octets[16:32] == sel
    assert octets[32:64] == empreinte
    assert struct.unpack_from("<I", octets, 64)[0] == 8 * 1024 * 1024
    assert octets[68:76] == b"\x00" * 8
    assert struct.unpack_from("<I", octets, 76)[0] == zlib.crc32(octets[0:76]) & 0xFFFFFFFF


def test_decalages_entete_bloc():
    octets = _bloc_base(
        type=2, id_codec=1, taille_claire=1234, taille_charge=5678, crc_charge=0xCAFEBABE
    ).vers_octets()
    assert octets[0] == 2
    assert octets[1] == 1
    assert octets[2:4] == b"\x00\x00"
    assert struct.unpack_from("<I", octets, 4)[0] == 1234
    assert struct.unpack_from("<I", octets, 8)[0] == 5678
    assert struct.unpack_from("<I", octets, 12)[0] == 0xCAFEBABE


def test_decalages_pied():
    octets = _pied_base(0x1122334455667788)
    assert struct.unpack_from("<Q", octets, 0)[0] == 0x1122334455667788
    assert octets[8:12] == b"UKAS"
    assert struct.unpack_from("<I", octets, 12)[0] == zlib.crc32(octets[0:12]) & 0xFFFFFFFF


# --------------------------------------------------------------------------- rejets : en-tete


def _corrompre(octets: bytes, decalage: int, valeur: int) -> bytes:
    """Remplace un octet de l'en-tete et recalcule le CRC pour atteindre le contrôle suivant."""
    b = bytearray(octets)
    b[decalage] = valeur
    b[76:80] = struct.pack("<I", zlib.crc32(bytes(b[0:76])) & 0xFFFFFFFF)
    return bytes(b)


def test_rejet_magic_faux():
    b = bytearray(_octets_entete())
    b[0] = 0x41  # 'A' au lieu de 'E'
    with pytest.raises(ArchiveInvalide):
        EnTete.depuis_octets(bytes(b))


def test_rejet_version_non_nulle():
    with pytest.raises(ArchiveInvalide):
        EnTete.depuis_octets(_corrompre(_octets_entete(), 6, 1))


def test_rejet_drapeau_inconnu():
    with pytest.raises(ArchiveInvalide):
        EnTete.depuis_octets(_corrompre(_octets_entete(), 7, 2))


def test_rejet_reserve_non_nul():
    with pytest.raises(ArchiveInvalide):
        EnTete.depuis_octets(_corrompre(_octets_entete(), 68, 1))


def test_rejet_crc_faux():
    b = bytearray(_octets_entete())
    b[76] ^= 0xFF  # casse le CRC sans le recalculer
    with pytest.raises(ArchiveInvalide):
        EnTete.depuis_octets(bytes(b))


@pytest.mark.parametrize(
    "mots",
    [
        # drapeau=1 mais aead/kdf=0
        dict(
            chiffree=True,
            id_aead=0,
            id_kdf=0,
            argon2_passes=1,
            argon2_parallelisme=1,
            argon2_memoire_kio=8192,
            sel=b"\x01" * 16,
        ),
        # drapeau=1, aead=1, kdf=0
        dict(
            chiffree=True,
            id_aead=1,
            id_kdf=0,
            argon2_passes=1,
            argon2_parallelisme=1,
            argon2_memoire_kio=8192,
            sel=b"\x01" * 16,
        ),
        # drapeau=1, aead=0, kdf=1
        dict(
            chiffree=True,
            id_aead=0,
            id_kdf=1,
            argon2_passes=1,
            argon2_parallelisme=1,
            argon2_memoire_kio=8192,
            sel=b"\x01" * 16,
        ),
        # drapeau=0 mais aead=1
        dict(chiffree=False, id_aead=1, id_kdf=0),
        # drapeau=0 mais kdf=1
        dict(chiffree=False, id_aead=0, id_kdf=1),
    ],
)
def test_rejet_incoherence_drapeau_aead_kdf(mots):
    with pytest.raises(ArchiveInvalide):
        EnTete.depuis_octets(_octets_entete(**mots))


@pytest.mark.parametrize(
    "champ, valeur",
    [
        ("argon2_passes", 0),
        ("argon2_passes", 17),
        ("argon2_parallelisme", 0),
        ("argon2_parallelisme", 17),
        ("argon2_memoire_kio", 8191),
        ("argon2_memoire_kio", 4_194_305),
    ],
)
def test_rejet_borne_argon2(champ, valeur):
    mots = dict(
        chiffree=True,
        id_aead=1,
        id_kdf=1,
        argon2_passes=1,
        argon2_parallelisme=1,
        argon2_memoire_kio=8192,
        sel=b"\x01" * 16,
    )
    mots[champ] = valeur
    with pytest.raises(ArchiveInvalide):
        EnTete.depuis_octets(_octets_entete(**mots))


@pytest.mark.parametrize("taille_bloc", [4095, 268_435_457])
def test_rejet_borne_taille_bloc(taille_bloc):
    with pytest.raises(ArchiveInvalide):
        EnTete.depuis_octets(_octets_entete(taille_bloc=taille_bloc))


# ----------------------------------------------------------- rejets : en-tete de bloc


def test_rejet_type_bloc_inconnu():
    with pytest.raises(ArchiveInvalide):
        EnTeteBloc.depuis_octets(_bloc_base(type=3).vers_octets())


def test_rejet_codec_inconnu():
    with pytest.raises(ArchiveInvalide):
        EnTeteBloc.depuis_octets(_bloc_base(id_codec=4).vers_octets())


def test_rejet_reserve_bloc_non_nul():
    octets = bytearray(_bloc_base().vers_octets())
    octets[2] = 1
    with pytest.raises(ArchiveInvalide):
        EnTeteBloc.depuis_octets(bytes(octets))


# --------------------------------------------------------------------------- rejets : pied


def test_rejet_magic_pied_faux():
    octets = bytearray(_pied_base())
    octets[8] = 0x00
    with pytest.raises(ArchiveInvalide):
        pied_depuis_octets(bytes(octets))


def test_rejet_crc_pied_faux():
    octets = bytearray(_pied_base())
    octets[12] ^= 0xFF
    with pytest.raises(ArchiveInvalide):
        pied_depuis_octets(bytes(octets))
