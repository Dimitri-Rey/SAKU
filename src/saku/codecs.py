"""Codecs de compression : 0 stocke, 1 zstd."""

from __future__ import annotations

from compression import zstd

from .erreurs import ArchiveInvalide


def compresser(id_codec: int, clair: bytes, niveau: int = 19) -> bytes:
    """Compresse selon le codec ; leve ArchiveInvalide si codec inconnu."""
    if id_codec == 0:
        return clair
    if id_codec == 1:
        return zstd.compress(clair, level=niveau)
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
    raise ArchiveInvalide(f"Codec inconnu ou reserve: {id_codec}")
