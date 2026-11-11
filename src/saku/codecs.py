"""Codecs de compression : 0 stocké, 1 zstd, 2 et 3 mélange de contextes
(docs/CODEC-2.md, docs/CODEC-3.md)."""

from __future__ import annotations

from compression import zstd

from . import cm
from .erreurs import ArchiveInvalide


def compresser(id_codec: int, clair: bytes, niveau: int = 19) -> bytes:
    """Compresse selon le codec ; leve ArchiveInvalide si codec inconnu."""
    if id_codec == 0:
        return clair
    if id_codec == 1:
        return zstd.compress(clair, level=niveau)
    if id_codec == 2:
        return cm.CODEC_2.compresser(clair)
    if id_codec == 3:
        return cm.CODEC_3.compresser(clair)
    raise ArchiveInvalide(f"Codec inconnu ou reserve: {id_codec}")


def decompresser(id_codec: int, charge: bytes, taille_claire: int) -> bytes:
    """Decompresse avec limite de sortie stricte ; leve ArchiveInvalide sinon."""
    if id_codec == 0:
        if len(charge) != taille_claire:
            raise ArchiveInvalide("Taille de charge incoherente avec taille_claire")
        return charge
    if id_codec == 1:
        try:
            moteur = zstd.ZstdDecompressor()
            sortie = moteur.decompress(charge, max_length=taille_claire)
            # Un flux qui produirait davantage que prevu n'est pas termine : il faut le
            # sonder, sinon la limite de sortie masquerait une taille mensongere.
            if not moteur.eof and moteur.decompress(b"", max_length=1):
                raise ArchiveInvalide("Le flux zstd depasse taille_claire")
        except zstd.ZstdError as exc:
            raise ArchiveInvalide("Echec de decompression zstd") from exc
        if not moteur.eof or moteur.unused_data:
            raise ArchiveInvalide("Flux zstd incomplet ou suivi d'octets en trop")
        if len(sortie) != taille_claire:
            raise ArchiveInvalide("Taille decomprimee incoherente avec taille_claire")
        return sortie
    if id_codec in (2, 3):
        # Le décodeur rend toujours taille_claire octets : une charge altérée donne un contenu
        # faux, que le CRC, l'AEAD et l'empreinte SHA-256 de chaque fichier font rejeter.
        moteur_cm = cm.CODEC_2 if id_codec == 2 else cm.CODEC_3
        return moteur_cm.decompresser(charge, taille_claire)
    raise ArchiveInvalide(f"Codec inconnu ou reserve: {id_codec}")
