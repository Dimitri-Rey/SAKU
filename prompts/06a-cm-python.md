# Tâche : implémentation de référence en Python

Écris `src/saku/cm_reference.py`, l'implémentation de référence du codec 2 en Python pur
(bibliothèque standard seulement). Elle sert de juge : la lisibilité et la conformité exacte
comptent plus que la vitesse, mais elle doit rester utilisable sur quelques centaines de
kilooctets.

## Interface exacte

```python
def compresser(clair: bytes) -> bytes: ...
def decompresser(charge: bytes, taille_claire: int) -> bytes: ...
```

- `decompresser` lève `ValueError` si `taille_claire < 0` ; sinon renvoie exactement
  `taille_claire` octets.
- Les tables fixes (`T`, `S`, `DT`) sont construites une fois au chargement du module.

## Points où l'on se trompe

1. `asr` sur des négatifs : en Python `>>` est déjà une division par excès vers moins
   l'infini, ce qui est exactement `asr`. Ne pas utiliser `int(x / 2**n)`.
2. Masquer à 32 bits (`& 0xFFFFFFFF`) chaque produit marqué `u32` dans la spécification.
3. Les tables `Ck` font 2^22 compteurs chacune : utiliser `array("I", ...)`, pas des listes.
   `MT` : `array("I")` de 2^20 ; `W` : une liste de 256 listes de 8 entiers.
4. Le prédicteur et le codeur sont deux choses séparées : écrire une classe `_Predicteur`
   avec `predire() -> int` et `mettre_a_jour(y: int) -> None`, et deux classes `_Codeur`,
   `_Decodeur`. Le compresseur et le décompresseur utilisent le même `_Predicteur`.
5. `predire()` calcule et mémorise les cases, `im`, les `x[i]` et `p` ; `mettre_a_jour(y)`
   réutilise exactement ces valeurs mémorisées.
6. Section 7.2 : la mise à zéro de `lg` en cas de discordance se fait pendant `predire()`.
7. Fin du codage : émettre `x1` sur 4 octets, poids fort d'abord, même pour une entrée vide.
8. Au décodage, un octet lu au-delà de la fin de la charge vaut 0.
