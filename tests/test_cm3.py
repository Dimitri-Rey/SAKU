"""Codec 3 : les deux implémentations, conformité et robustesse."""

import hashlib
import random

import pytest

import saku.cm3_reference as cm_ref
from saku.cm import CODEC_3 as cm


def _texte_source():
    lignes = []
    for i in range(100):
        lignes.append(f"def fonction_{i}():")
        for j in range(5):
            lignes.append(f"    variable_{i}_{j} = {i * j}")
            lignes.append(f"    print(variable_{i}_{j})")
        lignes.append("")
    return "\n".join(lignes).encode("utf-8")


def _texte_grand():
    base = _texte_source()
    return (base * 50)[:300000]


ENTREES = [
    b"",
    b"\x00",
    b"\x00" * 300,
    random.Random(1234).randbytes(4000),
    _texte_source(),
    "Déjà 42 éléments — naïve façon, ½ € ; 0x7F_3a.\n".encode() * 40,
]


def test_aller_retour_reference():
    for clair in ENTREES:
        charge = cm_ref.compresser(clair)
        assert cm_ref.decompresser(charge, len(clair)) == clair


def test_identite_c_python():
    if not cm.disponible():
        pytest.skip("bibliothèque C non disponible")
    for clair in ENTREES:
        charge_py = cm_ref.compresser(clair)
        charge_c = cm.compresser_c(clair)
        assert charge_c == charge_py
        assert cm.decompresser_c(charge_py, len(clair)) == clair
        assert cm_ref.decompresser(charge_c, len(clair)) == clair


def test_aller_retour_c_grand():
    if not cm.disponible():
        pytest.skip("bibliothèque C non disponible")
    clair = _texte_grand()
    charge = cm.compresser_c(clair)
    assert cm.decompresser_c(charge, len(clair)) == clair


def test_compression_texte():
    clair = _texte_source()
    charge = cm_ref.compresser(clair)
    assert len(charge) < len(clair) // 2


def test_compression_aleatoire():
    clair = random.Random(1234).randbytes(4000)
    charge = cm_ref.compresser(clair)
    # Mesuré : +2,1 % sur ces 4 000 octets ; l'archive stocke alors le bloc tel quel.
    assert len(charge) <= len(clair) * 1.03 + 16


def test_altérations_reference():
    clair = random.Random(1234).randbytes(4000)
    charge = cm_ref.compresser(clair)
    for i in range(50):
        alt = bytearray(charge)
        if i < 25:
            alt[i % len(alt)] ^= 0xFF
        else:
            alt = alt[: len(alt) - (i - 24)]
        res = cm_ref.decompresser(bytes(alt), len(clair))
        assert len(res) == len(clair)


def test_altérations_c():
    if not cm.disponible():
        pytest.skip("bibliothèque C non disponible")
    clair = random.Random(1234).randbytes(4000)
    charge = cm_ref.compresser(clair)
    for i in range(50):
        alt = bytearray(charge)
        if i < 25:
            alt[i % len(alt)] ^= 0xFF
        else:
            alt = alt[: len(alt) - (i - 24)]
        res = cm.decompresser_c(bytes(alt), len(clair))
        assert len(res) == len(clair)


def test_vide():
    assert cm_ref.decompresser(b"", 0) == b""
    assert len(cm_ref.decompresser(b"", 5)) == 5


def test_valeur_negative():
    with pytest.raises(ValueError):
        cm_ref.decompresser(b"", -1)
    with pytest.raises(ValueError):
        cm.decompresser(b"", -1)


def test_empreintes():
    """Vecteurs de contrôle de la spécification (docs/CODEC-3.md, section 8)."""
    attendues = [
        "df3f619804a92fdb4057192dc43dd748ea778adc52bc498ce80524c014b81119",
        "a9109c1002bcf36c3ddf529981a64781381335038cb974afc446dba196d7cbcd",
        "0fc1dc42369a5616c6c971328ea5ca7135b31bf0fc2b58f9b344a8141030102c",
        "233efa099c1a472e61c2367775a88c4962342f2bab8c3ad89d8890072979042a",
        "0cae479a85c323faa0c55e353acae0443547ca6d0df4aaa9d4051c28e9ba97e4",
        "3484c3d3cc972aae0c35a00a8fbc5912979bbf0eb78559f27e68a5222bd24f82",
    ]
    for clair, attendue in zip(ENTREES, attendues, strict=True):
        assert hashlib.sha256(cm_ref.compresser(clair)).hexdigest() == attendue
        if cm.disponible():
            assert hashlib.sha256(cm.compresser_c(clair)).hexdigest() == attendue


def test_chargement_concurrent():
    """Huit fils qui chargent le codec en même temps obtiennent tous la version C.

    Régression : sans verrou, un fil arrivé pendant le chargement se rabattait sur la
    référence Python, juste mais des centaines de fois plus lente.
    """
    from concurrent.futures import ThreadPoolExecutor

    from saku.cm import _Moteur

    if not cm.disponible():
        pytest.skip("bibliothèque C non disponible")
    moteur = _Moteur("cm3.c", "saku_cm3", 2, cm_ref)
    with ThreadPoolExecutor(8) as executeur:
        resultats = list(executeur.map(lambda _: moteur.disponible(), range(8)))
    assert all(resultats)
