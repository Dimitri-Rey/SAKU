"""Structures binaires du format v0 : en-tete, en-tete de bloc, pied (sans entree-sortie)."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass

from .erreurs import ArchiveInvalide

_MAGIC = b"SAKU\x00\x00"
_MAGIC_FIN = b"UKAS"
_TAILLE_ENTETE = 80
_TAILLE_ENTETE_BLOC = 16
_TAILLE_PIED = 16
_TAILLE_SEL = 16
_TAILLE_EMPREINTE = 32
_TAILLE_NONCE = 12
_TAILLE_ETIQUETTE = 16

_TAILLE_BLOC_MIN = 4096
_TAILLE_BLOC_MAX = 268_435_456
_ARGON2_MEMOIRE_MIN = 8192
_ARGON2_MEMOIRE_MAX = 4_194_304
_ARGON2_PARA_MIN = 1
_ARGON2_PARA_MAX = 16
_ARGON2_PASSES_MIN = 1
_ARGON2_PASSES_MAX = 16
_TAILLE_INDEX_MAX = 1_073_741_824


@dataclass(frozen=True)
class ParametresArgon2:
    """Parametres Argon2id."""

    passes: int = 3
    parallelisme: int = 4
    memoire_kio: int = 262_144


@dataclass(frozen=True)
class EnTete:
    """En-tete d'archive (80 octets)."""

    version: int
    chiffree: bool
    id_aead: int
    id_kdf: int
    argon2_passes: int
    argon2_parallelisme: int
    argon2_memoire_kio: int
    sel: bytes
    empreinte_modele: bytes
    taille_bloc: int

    def vers_octets(self) -> bytes:
        """Serialise l'en-tete en 80 octets."""
        corps = bytearray(_TAILLE_ENTETE - 4)
        corps[0:6] = _MAGIC
        corps[6] = self.version
        drapeaux = 1 if self.chiffree else 0
        corps[7] = drapeaux
        corps[8] = self.id_aead
        corps[9] = self.id_kdf
        corps[10] = self.argon2_passes
        corps[11] = self.argon2_parallelisme
        struct.pack_into("<I", corps, 12, self.argon2_memoire_kio)
        corps[16:32] = self.sel
        corps[32:64] = self.empreinte_modele
        struct.pack_into("<I", corps, 64, self.taille_bloc)
        corps[68:76] = b"\x00" * 8
        crc = zlib.crc32(bytes(corps)) & 0xFFFFFFFF
        return bytes(corps) + struct.pack("<I", crc)

    @classmethod
    def depuis_octets(cls, donnees: bytes) -> EnTete:
        """Deserialise et valide un en-tete de 80 octets."""
        if len(donnees) != _TAILLE_ENTETE:
            raise ArchiveInvalide("En-tete de taille inattendue")
        if donnees[0:6] != _MAGIC:
            raise ArchiveInvalide("Magic d'en-tete invalide")
        version = donnees[6]
        if version != 0:
            raise ArchiveInvalide("Version d'archive non supportee")
        drapeaux = donnees[7]
        if drapeaux & ~1:
            raise ArchiveInvalide("Bits de drapeaux reserves non nuls")
        id_aead = donnees[8]
        id_kdf = donnees[9]
        argon2_passes = donnees[10]
        argon2_parallelisme = donnees[11]
        argon2_memoire_kio = struct.unpack_from("<I", donnees, 12)[0]
        sel = donnees[16:32]
        empreinte_modele = donnees[32:64]
        taille_bloc = struct.unpack_from("<I", donnees, 64)[0]
        if donnees[68:76] != b"\x00" * 8:
            raise ArchiveInvalide("Champ reserve non nul")
        crc_stocke = struct.unpack_from("<I", donnees, 76)[0]
        crc_calcule = zlib.crc32(donnees[0:76]) & 0xFFFFFFFF
        if crc_stocke != crc_calcule:
            raise ArchiveInvalide("CRC d'en-tete invalide")
        chiffree = bool(drapeaux & 1)
        if chiffree:
            if id_aead != 1 or id_kdf != 1:
                raise ArchiveInvalide("Incoherence drapeaux/id_aead/id_kdf")
            if not (_ARGON2_PASSES_MIN <= argon2_passes <= _ARGON2_PASSES_MAX):
                raise ArchiveInvalide("argon2_passes hors bornes")
            if not (_ARGON2_PARA_MIN <= argon2_parallelisme <= _ARGON2_PARA_MAX):
                raise ArchiveInvalide("argon2_parallelisme hors bornes")
            if not (_ARGON2_MEMOIRE_MIN <= argon2_memoire_kio <= _ARGON2_MEMOIRE_MAX):
                raise ArchiveInvalide("argon2_memoire_kio hors bornes")
        else:
            if id_aead != 0 or id_kdf != 0:
                raise ArchiveInvalide("Incoherence drapeaux/id_aead/id_kdf")
            if argon2_passes != 0 or argon2_parallelisme != 0 or argon2_memoire_kio != 0:
                raise ArchiveInvalide("Parametres Argon2 non nuls sur archive non chiffree")
            if sel != b"\x00" * _TAILLE_SEL:
                raise ArchiveInvalide("Sel non nul sur archive non chiffree")
        if not (_TAILLE_BLOC_MIN <= taille_bloc <= _TAILLE_BLOC_MAX):
            raise ArchiveInvalide("taille_bloc hors bornes")
        return cls(
            version=version,
            chiffree=chiffree,
            id_aead=id_aead,
            id_kdf=id_kdf,
            argon2_passes=argon2_passes,
            argon2_parallelisme=argon2_parallelisme,
            argon2_memoire_kio=argon2_memoire_kio,
            sel=sel,
            empreinte_modele=empreinte_modele,
            taille_bloc=taille_bloc,
        )


@dataclass(frozen=True)
class EnTeteBloc:
    """En-tete de bloc (16 octets)."""

    type: int
    id_codec: int
    taille_claire: int
    taille_charge: int
    crc_charge: int

    def vers_octets(self) -> bytes:
        """Serialise l'en-tete de bloc en 16 octets."""
        return struct.pack("<BBHI", self.type, self.id_codec, 0, self.taille_claire) + struct.pack(
            "<II", self.taille_charge, self.crc_charge
        )

    @classmethod
    def depuis_octets(cls, donnees: bytes) -> EnTeteBloc:
        """Deserialise un en-tete de bloc de 16 octets."""
        if len(donnees) != _TAILLE_ENTETE_BLOC:
            raise ArchiveInvalide("En-tete de bloc de taille inattendue")
        type_b = donnees[0]
        id_codec = donnees[1]
        if donnees[2:4] != b"\x00\x00":
            raise ArchiveInvalide("Champ reserve de bloc non nul")
        taille_claire = struct.unpack_from("<I", donnees, 4)[0]
        taille_charge = struct.unpack_from("<I", donnees, 8)[0]
        crc_charge = struct.unpack_from("<I", donnees, 12)[0]
        if type_b not in (1, 2):
            raise ArchiveInvalide("Type de bloc inconnu")
        if id_codec not in (0, 1, 2):
            raise ArchiveInvalide("Codec inconnu")
        return cls(
            type=type_b,
            id_codec=id_codec,
            taille_claire=taille_claire,
            taille_charge=taille_charge,
            crc_charge=crc_charge,
        )


def pied_vers_octets(position_index: int) -> bytes:
    """Serialise le pied de 16 octets."""
    corps = struct.pack("<Q", position_index) + _MAGIC_FIN
    crc = zlib.crc32(corps) & 0xFFFFFFFF
    return corps + struct.pack("<I", crc)


def pied_depuis_octets(donnees: bytes) -> int:
    """Deserialise et valide le pied de 16 octets, renvoie position_index."""
    if len(donnees) != _TAILLE_PIED:
        raise ArchiveInvalide("Pied de taille inattendue")
    position_index = struct.unpack_from("<Q", donnees, 0)[0]
    if donnees[8:12] != _MAGIC_FIN:
        raise ArchiveInvalide("Magic de pied invalide")
    crc_stocke = struct.unpack_from("<I", donnees, 12)[0]
    crc_calcule = zlib.crc32(donnees[0:12]) & 0xFFFFFFFF
    if crc_stocke != crc_calcule:
        raise ArchiveInvalide("CRC de pied invalide")
    return position_index
