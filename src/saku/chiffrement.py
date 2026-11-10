"""Derivation de cle (Argon2id) et chiffrement authentifie des blocs (AES-256-GCM)."""

from __future__ import annotations

import hashlib
import struct

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from .erreurs import EchecAuthentification, MotDePasseRequis
from .format import ParametresArgon2


def deriver_cle(mot_de_passe: str, sel: bytes, parametres: ParametresArgon2) -> bytes:
    """Derive une cle de 32 octets via Argon2id."""
    if not mot_de_passe:
        raise MotDePasseRequis("Mot de passe vide interdit")
    kdf = Argon2id(
        salt=sel,
        length=32,
        iterations=parametres.passes,
        lanes=parametres.parallelisme,
        memory_cost=parametres.memoire_kio,
    )
    return kdf.derive(mot_de_passe.encode("utf-8"))


def nonce_bloc(numero: int, est_index: bool) -> bytes:
    """Nonce de 12 octets : numero (8 o LE), trois zeros, role (01 pour l'index)."""
    return struct.pack("<Q", numero) + b"\x00\x00\x00" + (b"\x01" if est_index else b"\x00")


def chiffrer_bloc(
    cle: bytes,
    numero: int,
    est_index: bool,
    clair: bytes,
    aad: bytes,
) -> bytes:
    """Chiffre un bloc en AES-256-GCM, renvoie charge + etiquette."""
    nonce = nonce_bloc(numero, est_index)
    return AESGCM(cle).encrypt(nonce, clair, aad)


def dechiffrer_bloc(
    cle: bytes,
    numero: int,
    est_index: bool,
    charge: bytes,
    aad: bytes,
) -> bytes:
    """Dechiffre un bloc ; leve EchecAuthentification si etiquette invalide."""
    nonce = nonce_bloc(numero, est_index)
    try:
        return AESGCM(cle).decrypt(nonce, charge, aad)
    except InvalidTag as exc:
        raise EchecAuthentification("Echec d'authentification du bloc") from exc


def aad_entete(entete_octets: bytes, entete_bloc_octets: bytes) -> bytes:
    """AAD = SHA-256(entete 80 o) || 12 premiers octets de l'en-tete de bloc."""
    return hashlib.sha256(entete_octets).digest() + entete_bloc_octets[0:12]
