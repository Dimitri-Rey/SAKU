# Codec 2 — mélange de contextes en arithmétique entière (version 1)

Ce document **fait autorité**. Deux implémentations indépendantes qui le suivent à la lettre
doivent produire **exactement les mêmes octets** pour la même entrée, sur toute machine. Toute
ambiguïté est un défaut de ce document.

## 1. Principe

Chaque bloc est codé bit par bit, du bit de poids fort au bit de poids faible de chaque octet.
Avant chaque bit, un prédicteur estime la probabilité `p` (sur 12 bits, de 1 à 4095) que ce bit
vaille 1 ; un codeur arithmétique binaire consomme `p` et le bit. Le décodeur refait les mêmes
prédictions et retrouve les bits. Le prédicteur apprend en direct, à partir de zéro, au début de
chaque bloc : il n'y a **aucun modèle externe** (champ `empreinte_modele` de l'en-tête : zéros).

Le prédicteur combine 7 modèles par un mélangeur logistique (un réseau à une couche, appris en
direct) :

| Entrée | Modèle |
|---|---|
| 0 | ordre 0 : bits déjà vus de l'octet courant |
| 1 à 5 | ordres 1, 2, 3, 4 et 6 : les 1, 2, 3, 4 ou 6 octets précédents, hachés |
| 6 | correspondance : prolonge la plus récente répétition d'au moins 6 octets |
| 7 | biais constant |

**Aucun nombre à virgule flottante.** Tous les calculs sont sur des entiers.

## 2. Conventions

- `u32(x)` = `x mod 2^32` (résultat dans `[0, 2^32)`).
- `asr(x, n)` = `floor(x / 2^n)`, y compris pour `x < 0`. En C, ne pas se fier à `>>` sur un
  signé : utiliser `x >= 0 ? x >> n : ~((~x) >> n)`.
- `clamp(x, a, b)` = `min(max(x, a), b)`.
- Les produits intermédiaires peuvent dépasser 32 bits : en C, les faire en 64 bits.
- `/` n'apparaît que sur des entiers positifs et désigne la division entière.

## 3. Tables fixes

### 3.1 `squash` : de l'espace logistique vers une probabilité

```
T = [1, 2, 4, 6, 10, 17, 27, 45, 74, 120, 194, 311, 488, 747, 1102, 1546, 2048,
     2550, 2994, 3349, 3608, 3785, 3902, 3976, 4022, 4051, 4069, 4079, 4086, 4090,
     4092, 4094, 4095]                       (33 valeurs, T[16] = 2048)

squash(d):
    d = clamp(d, -2047, 2047)
    e = d + 2048                             (1 ≤ e ≤ 4095)
    i = e / 128                              (0 ≤ i ≤ 31)
    w = e mod 128
    r = (T[i] * (128 - w) + T[i + 1] * w + 64) / 128
    return clamp(r, 1, 4095)
```

### 3.2 `stretch` : l'inverse, pour p de 0 à 4095

Table `S[0..4095]` construite une fois :

```
pi = 0
pour x de -2047 à 2047 (inclus) :
    v = squash(x)
    pour j de pi à v (inclus) : S[j] = x
    pi = v + 1
pour j de pi à 4095 (inclus) : S[j] = 2047
stretch(p) = S[p]
```

### 3.3 `DT` : vitesses d'apprentissage

`DT[n] = 131072 / (2n + 3)` pour `n` de 0 à 255 (division entière). `LIMITE = 255`.

## 4. Compteur adaptatif

Un compteur est un entier de 32 bits `s`. Ses 22 bits de poids fort sont une probabilité
`p22 = s >> 10` (sur 2^22) ; ses 10 bits de poids faible un nombre d'observations `n`.

- Valeur initiale : `s = (2^21) << 10` (probabilité 1/2, `n = 0`).
- Prédiction sur 12 bits : `p12(s) = s >> 20`.
- Mise à jour avec le bit `y` :

```
p22 = s >> 10 ; n = s & 1023
cible = y ? 4194303 : 0                      (2^22 - 1 ou 0)
si cible > p22 : p22 = p22 + (((cible - p22) * DT[n]) >> 16)
sinon          : p22 = p22 - (((p22 - cible) * DT[n]) >> 16)
si n < LIMITE  : n = n + 1
s = (p22 << 10) | n
```

## 5. État du prédicteur

Remis à neuf **au début de chaque bloc** :

| Élément | Taille | Valeur initiale |
|---|---|---|
| `c0` (octet en cours, avec un 1 de tête) | entier | 1 |
| `bp` (rang du bit dans l'octet, 0 = poids fort) | entier | 0 |
| `buf` (octets du bloc déjà codés) | — | vide ; `pos` = sa longueur |
| `O0` (ordre 0) | 256 compteurs | initiale |
| `Ck`, k = 1..5 (ordres 1, 2, 3, 4, 6) | 2^22 compteurs chacun | initiale |
| `h[k]`, k = 1..5 | entiers 32 bits | calculés comme en 6.1 avec `pos = 0` |
| `MM` (correspondance) | 64 compteurs | initiale |
| `MT` (table des positions) | 2^20 entiers | 0 |
| `lg` (longueur de correspondance), `ptr` | entiers | 0, 0 |
| `W[c][i]`, c = 0..255, i = 0..7 | entiers signés | `16384` |

## 6. Contextes

### 6.1 Hachage d'ordre `n` (calculé à chaque frontière d'octet)

Ordres `N = [1, 2, 3, 4, 6]` pour k = 1..5.

```
h = u32(N[k] * 0x9E3779B1)
pour j de 1 à N[k] :
    b = buf[pos - j] si pos - j ≥ 0, sinon 0
    h = u32((h ^ b) * 0x01000193)
h[k] = h
```

### 6.2 Case utilisée pour un bit

Pour k = 1..5 et l'état `c0` courant :

```
x = u32(h[k] ^ u32(c0 * 0x2545F491))
x = u32(x * 0x9E3779B1)
x = x ^ (x >> 15)
case[k] = x >> 10                            (22 bits)
```

Pour l'ordre 0 : `case[0] = c0`.

## 7. Modèle de correspondance

### 7.1 À chaque frontière d'octet (après l'ajout de l'octet `c` dans `buf`, `pos` mis à jour)

```
si lg > 0 et buf[ptr] == c : lg = min(lg + 1, 65535) ; ptr = ptr + 1
sinon                      : lg = 0
si pos ≥ 6 :
    g = 0
    pour j de 6 à 1 (décroissant) : g = u32(g * 0x2F0B3A49 + buf[pos - j] + 1)
    e = u32(g * 0x9E3779B1) >> 12            (20 bits)
    si lg == 0 et MT[e] > 0 :
        ptr = MT[e]
        lg = 0
        tant que lg < 32 et lg < ptr et buf[ptr - 1 - lg] == buf[pos - 1 - lg] : lg = lg + 1
    MT[e] = pos
```

Remarques : `ptr` désigne l'octet qui a suivi l'occurrence précédente, donc `ptr < pos`
toujours ; une longueur vérifiée nulle laisse `lg = 0`.

### 7.2 Pour chaque bit

```
si lg > 0 :
    attendu = buf[ptr]
    si (attendu + 256) >> (8 - bp) == c0 :   (les bits déjà codés de l'octet concordent)
        bit_att = (attendu >> (7 - bp)) & 1
        im = min(lg, 31) * 2 + bit_att
    sinon :
        lg = 0 ; im = 0
sinon : im = 0
```

Le compteur utilisé est `MM[im]`.

## 8. Prédiction d'un bit

```
x[0]     = stretch(p12(O0[case[0]]))
x[k]     = stretch(p12(Ck[case[k]]))         k = 1..5
x[6]     = stretch(p12(MM[im]))
x[7]     = 256
point    = Σ W[c0][i] * x[i]                 i = 0..7 (entier signé, 64 bits)
d        = clamp(asr(point, 16), -2047, 2047)
p        = squash(d)                         (1 ≤ p ≤ 4095)
```

`p` est la probabilité, sur 4096, que le bit vaille 1.

## 9. Mise à jour après le bit `y`

Dans cet ordre, avec les cases et `im` calculés pour ce bit :

```
err = ((y << 12) - p) * 6
pour i de 0 à 7 :
    W[c0][i] = clamp(W[c0][i] + asr(x[i] * err + 32768, 16), -8388608, 8388607)
mettre à jour O0[case[0]], Ck[case[k]] (k = 1..5) et MM[im] avec y   (section 4)
c0 = (c0 << 1) | y ; bp = bp + 1
si bp == 8 :
    c = c0 & 255 ; ajouter c à buf ; pos = pos + 1
    c0 = 1 ; bp = 0
    mettre à jour la correspondance (7.1)
    recalculer h[1..5] (6.1)
```

## 10. Codeur arithmétique binaire (32 bits)

### Codage

```
x1 = 0 ; x2 = 0xFFFFFFFF
coder(y, p) :
    r = x2 - x1
    xm = x1 + (r >> 12) * p + (((r & 0xFFF) * p) >> 12)
    si y == 1 : x2 = xm   sinon : x1 = xm + 1
    tant que ((x1 ^ x2) & 0xFF000000) == 0 :
        émettre l'octet x2 >> 24
        x1 = u32(x1 << 8)
        x2 = u32(x2 << 8) | 255
fin : émettre x1 sur 4 octets, poids fort d'abord
```

### Décodage

```
x1 = 0 ; x2 = 0xFFFFFFFF
x = les 4 premiers octets de la charge, poids fort d'abord
décoder(p) :
    r = x2 - x1
    xm = x1 + (r >> 12) * p + (((r & 0xFFF) * p) >> 12)
    y = 1 si x ≤ xm sinon 0
    si y == 1 : x2 = xm   sinon : x1 = xm + 1
    tant que ((x1 ^ x2) & 0xFF000000) == 0 :
        x1 = u32(x1 << 8) ; x2 = u32(x2 << 8) | 255
        x = u32(x << 8) | octet suivant de la charge
    renvoyer y
```

Un octet lu au-delà de la fin de la charge vaut **0**. Le décodeur produit exactement
`taille_claire` octets, connue par l'en-tête de bloc, puis s'arrête ; il ne contrôle pas que
la charge est consommée en entier (l'intégrité est assurée par le CRC, l'AEAD et les SHA-256
du format). Il ne peut ni boucler ni écrire plus de `taille_claire` octets.

## 11. Ce qui est volontairement simple dans la version 1

Pas de somme de contrôle dans les cases hachées (les collisions dégradent la prédiction, pas
l'exactitude), pas d'étage de raffinement après le mélangeur, pas d'automate d'historique de
bits. Chacun de ces ajouts sera une **version 2** du codec, avec un autre identifiant : une
archive écrite en version 1 doit rester lisible telle quelle.

## 12. Coût et limites

Le décodage d'un bloc demande environ 90 Mio de mémoire (cinq tables de 16 Mio et la table
des positions) et un temps proportionnel à `taille_claire`. Une archive hostile ne peut donc
pas obtenir plus que ce travail pour chaque bloc qu'elle déclare.

## 13. Vecteurs de contrôle

Les tests du dépôt fixent les empreintes SHA-256 de la charge produite pour quelques entrées de
référence (`tests/test_cm.py`). Une implémentation conforme doit les reproduire.
