"""Codec 2 : les deux implémentations, conformité et robustesse."""

import hashlib
import random

import pytest

import saku.cm as cm
import saku.cm_reference as cm_ref


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
    """Vecteurs de contrôle de la spécification (docs/CODEC-2.md, section 12)."""
    attendues = [
        "df3f619804a92fdb4057192dc43dd748ea778adc52bc498ce80524c014b81119",
        "c6baeacc070c08f7c445665ac50018355d812b0ed93213d38c2d14045a3213c0",
        "11fe95df5de5bd721b885e0339395068b92a7738f562adad577795d5814c22bb",
        "46a820036ee311cf7b9d5798f63cd09eb068170be68c7680789cbbbfd0618720",
        "b84315b071f78e97e9b13ecfa0bf1626205d375008b61000225e281aec9cad19",
    ]
    for clair, attendue in zip(ENTREES, attendues, strict=True):
        assert hashlib.sha256(cm_ref.compresser(clair)).hexdigest() == attendue
        if cm.disponible():
            assert hashlib.sha256(cm.compresser_c(clair)).hexdigest() == attendue
