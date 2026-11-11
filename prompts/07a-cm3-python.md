# Tâche : référence Python du codec 3

Écris `src/saku/cm3_reference.py`, l'implémentation de référence du codec 3 en Python pur
(bibliothèque standard seulement), en suivant **à la lettre** `docs/CODEC-3.md`, qui renvoie à
`docs/CODEC-2.md` pour ce qu'il ne redéfinit pas.

Tu as `src/saku/cm_reference.py` (le codec 2, vérifié) : **réutilise-le**. Importe ce qui ne
change pas (`asr`, `squash`, `stretch` ou la table `S`, `_Codeur`, `_Decodeur`, la boucle de
compression et de décompression) au lieu de le recopier, et écris un nouveau `_Predicteur`.
Lis bien quels noms `cm_reference.py` expose avant de les importer.

## Interface exacte

```python
def compresser(clair: bytes) -> bytes: ...
def decompresser(charge: bytes, taille_claire: int) -> bytes: ...
```

`decompresser` lève `ValueError` si `taille_claire < 0`.

## Points où l'on se trompe

1. `H[k]` : un seul `array("I", bytes(4 * 16 * 2**19))` par k ; un seau est l'indice de son
   premier entier (`i * 16`). `A1`, `A2` : `array("H")`. `O1` : `array("I")`.
2. `DT` va jusqu'à n = 1023 ; chaque compteur a sa limite (20, 20, 1023 selon le tableau §5).
3. `trouver` remplace le seau **a** en cas d'égalité ; la vérification n'est jamais 0.
4. Les seaux se recalculent au début du bloc, après chaque octet, et quand `bp` devient 4
   (alors `c0` vaut de 16 à 31).
5. `im` se calcule avant `l` (le calcul de `im` peut mettre `lg` à 0).
6. L'erreur du mélangeur utilise `pm` (sortie du mélangeur), le codeur reçoit `p`.
7. Au décodage, l'octet doit être dans `buf` avant la mise à jour de son 8e bit, comme dans
   le codec 2.
8. Masquer à 32 bits chaque `u32`.

Réponds uniquement avec le fichier, entre `=== FICHIER: src/saku/cm3_reference.py ===` et la
fin de ta réponse.
