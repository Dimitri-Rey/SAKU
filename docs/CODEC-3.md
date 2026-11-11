# Codec 3 — mélange de contextes en arithmétique entière (version 2)

Ce document **fait autorité**, comme [CODEC-2.md](CODEC-2.md) dont il reprend tout ce qui
n'est pas redéfini ici. Deux implémentations qui le suivent doivent produire **exactement les
mêmes octets**. Le codec 2 reste inchangé et lisible : le codec 3 est un autre identifiant.

Ce qui change par rapport au codec 2, chaque point mesuré sur deux blocs de 8 Mio :

- les ordres hachés vivent dans des **seaux vérifiés** de 16 compteurs, un seau par
  demi-octet (moins de collisions, moins d'accès mémoire) ;
- l'ordre 1 devient une table directe ; un **contexte « mot »** s'ajoute ;
- les compteurs s'adaptent plus vite (limites différentes selon le modèle) ;
- le jeu de poids du mélangeur dépend aussi de la **longueur de correspondance** ;
- deux **APM** (étages de raffinement) corrigent la sortie du mélangeur.

Conventions, `squash`, `stretch`, compteur (§4 sauf la limite), modèle de correspondance (§7)
et codeur arithmétique (§10) : **identiques au codec 2**.

## 1. Constantes

```
DT[n] = 131072 / (2n + 3)        pour n de 0 à 1023
LIM_BAS  = 20                    (O0, O1)
LIM_HACH = 20                    (ordres hachés et mot)
LIM_CORR = 1023                  (MM)
LOGB = 19                        (2^19 seaux par table)
```

La mise à jour d'un compteur est celle du codec 2 §4, avec `si n < lim : n = n + 1` où `lim`
dépend du compteur.

## 2. État (remis à neuf au début de chaque bloc)

| Élément | Taille | Valeur initiale |
|---|---|---|
| `c0`, `bp`, `buf`, `pos`, `MM`, `MT`, `lg`, `ptr` | comme le codec 2 | comme le codec 2 |
| `c4` (les 4 derniers octets, le plus récent en poids faible) | entier 32 bits | 0 |
| `O0` | 256 compteurs | initiale |
| `O1` | 65 536 compteurs | initiale |
| `H[k]`, k = 0..4 | 16 × 2^19 entiers 32 bits chacun | 0 |
| `h[k]`, k = 0..4 | entiers 32 bits | calculés (§3) avec `pos = 0` |
| `seau[k]`, k = 0..4 | position d'un seau dans `H[k]` | calculée (§4) après `h` |
| `mot`, `motp` | entiers 32 bits | 0, 0 |
| `W[s][i]`, s = 0..1023, i = 0..8 | entiers signés | 16384 |
| `A1` | 256 × 33 entiers 16 bits | `A1[cx*33 + j] = squash((j - 16) * 128) * 16` |
| `A2` | 65 536 × 33 entiers 16 bits | même formule |

Un seau est 16 entiers consécutifs : l'entier 0 est la **vérification**, les entiers 1 à 15
sont des compteurs.

## 3. Empreintes de contexte (à chaque frontière d'octet)

Pour k = 0..3, ordres `N = [2, 3, 4, 6]` : même calcul que le codec 2 §6.1.

Pour k = 4 (mot) :

```
h[4] = u32( u32((mot ^ 0x5BD1E995) * 0x01000193) + u32(motp * 0x2F0B3A49) )
```

## 4. Choix des seaux

Au début du bloc, après chaque octet complet (`bp = 0`) et quand `bp` devient 4 :

```
n = (bp == 0) ? 0 : u32(c0 * 0x6F4F2A35)        (à bp = 4, c0 vaut de 16 à 31)
pour k = 0..4 : seau[k] = trouver(H[k], u32(h[k] + n))
```

```
trouver(T, x) :
    x = u32(x * 0x9E3779B1) ; x = x ^ (x >> 15)
    x = u32(x * 0x2545F491) ; x = x ^ (x >> 13)
    i   = x >> (32 - LOGB)
    chk = (x & 0x00FFFFFF) | 0x01000000             (jamais 0)
    a = seau i ; b = seau (i ^ 1)
    si T[a][0] == chk : renvoyer a
    si T[b][0] == chk : renvoyer b
    r = b si (T[b][1] & 1023) < (T[a][1] & 1023), sinon a
    T[r][0] = chk ; T[r][1..15] = valeur initiale d'un compteur
    renvoyer r
```

## 5. Prédiction d'un bit

Indice dans le seau, de 1 à 15 :

```
q = bp si bp < 4, sinon bp - 4
j = (c0 & ((1 << q) - 1)) | (1 << q)
```

`im` se calcule comme au codec 2 §7.2 (ce calcul peut remettre `lg` à 0). Puis :

| i | compteur `cpt[i]` | limite |
|---|---|---|
| 0 | `O0[c0]` | LIM_BAS |
| 1 | `O1[((c4 & 255) << 8) \| c0]` | LIM_BAS |
| 2 à 6 | `H[i-2][seau[i-2]][j]` | LIM_HACH |
| 7 | `MM[im]` | LIM_CORR |

```
x[i] = stretch(p12(cpt[i]))     i = 0..7 ;  x[8] = 256
l    = 0 si lg == 0 ; 1 si lg < 16 ; 2 si lg < 32 ; 3 sinon     (lg après le calcul de im)
s    = c0 + 256 * l
pm   = squash(clamp(asr(Σ W[s][i] * x[i], 16), -2047, 2047))     i = 0..8
p1   = apm(A1, c0, pm)
p2   = apm(A2, c0 | ((c4 & 255) << 8), pm)
p    = clamp((pm + p1 + 2 * p2 + 2) >> 2, 1, 4095)
```

`p` est la probabilité transmise au codeur arithmétique.

```
apm(A, cx, pm) :
    t = stretch(pm) + 2048            (de 1 à 4095)
    w = t & 127
    i = (t >> 7) + cx * 33
    retenir idx = i + (w >> 6)        (point le plus proche, pour la mise à jour)
    renvoyer (A[i] * (128 - w) + A[i + 1] * w) >> 11
```

## 6. Mise à jour après le bit `y`

Dans cet ordre, avec ce qui a été calculé pour ce bit :

```
err = ((y << 12) - pm) * 6                       (pm, pas p)
pour i de 0 à 8 :
    W[s][i] = clamp(W[s][i] + asr(x[i] * err + 32768, 16), -8388608, 8388607)
mettre à jour cpt[0..7] avec y, chacun avec sa limite
pour (A, idx) dans (A1, idx1), (A2, idx2) :
    g = (y << 16) + (y << 7) - 2y
    A[idx] = A[idx] + asr(g - A[idx], 7)
c0 = (c0 << 1) | y ; bp = bp + 1
si bp == 8 :
    c = c0 & 255 ; ajouter c à buf ; pos = pos + 1 ; c0 = 1 ; bp = 0
    c4 = u32((c4 << 8) | c)
    si c est alphanumérique :  mot = u32((mot ^ c) * 0x01000193)
    sinon si mot != 0 :        motp = mot ; mot = 0
    mettre à jour la correspondance (codec 2 §7.1)
    recalculer h[0..4] (§3), puis les seaux (§4)
sinon si bp == 4 :
    recalculer les seaux (§4)
```

« Alphanumérique » : `0`–`9`, `a`–`z`, `A`–`Z`, `_`, ou tout octet ≥ 128.

## 7. Coût et limites

Environ 195 Mio de mémoire par bloc (cinq tables de 32 Mio, `A2` de 4 Mio, `MT` de 4 Mio) et
un temps proportionnel à `taille_claire`.

## 8. Vecteurs de contrôle

`tests/test_cm3.py` fixe les empreintes SHA-256 de la charge pour des entrées de référence.
