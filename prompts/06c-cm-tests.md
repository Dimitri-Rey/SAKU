# Tâche : tests du codec 2

Écris `tests/test_cm.py` (pytest). Le module `saku.cm_reference` expose
`compresser(clair: bytes) -> bytes` et `decompresser(charge: bytes, taille_claire: int) -> bytes`.
Le module `saku.cm` expose les mêmes fonctions, plus :
- `cm.disponible() -> bool` : vrai si la bibliothèque C compilée est utilisable ;
- `cm.compresser_c(clair)` / `cm.decompresser_c(charge, taille)` : forcent la version C
  (lèvent `RuntimeError` si elle n'est pas disponible).

## Tests à écrire (au plus 220 lignes)

1. Aller-retour avec la référence Python sur : `b""`, un octet, 300 octets nuls, 4 000 octets
   pseudo-aléatoires (`random.Random(1234).randbytes`), un texte source Python de ~6 Ko
   construit dans le test (répétitif, avec des indentations).
2. Pour les mêmes entrées : la sortie C est **identique octet pour octet** à la sortie Python
   (`pytest.mark.skipif(not cm.disponible(), ...)`), et la version C décompresse la sortie
   Python et inversement.
3. Aller-retour C sur une entrée plus grande (~300 Ko de texte construit) : identique.
4. Le texte source se compresse : charge plus petite que la moitié de l'entrée.
5. Données aléatoires : la charge ne dépasse pas l'entrée de plus de 1 % + 16 octets.
6. Charge tronquée ou altérée : `decompresser` ne lève rien d'autre que rien du tout (il rend
   `taille` octets, éventuellement faux) et ne boucle pas ; vérifier sur 50 altérations que la
   longueur rendue est exacte. Tester les deux implémentations.
7. `decompresser(b"", 0) == b""` et `decompresser(b"", 5)` rend 5 octets.
8. `decompresser(..., -1)` lève `ValueError` (version Python et version publique `cm`).

Pas d'utilitaires génériques, pas de classes de test. Imports en tête de fichier.
