# Tâche : implémentation rapide en C99

Écris `src/saku/_cm/cm.c`, implémentation du codec 2 en C99 portable (aucune dépendance hors
bibliothèque standard, aucune extension de compilateur, aucun `float` ni `double`). Elle sera
compilée en bibliothèque partagée et appelée depuis Python par `ctypes`.

## Interface exacte (exportée)

```c
#include <stddef.h>
#include <stdint.h>

/* Compresse n octets. Alloue *sortie (à libérer par saku_cm_liberer) et écrit sa taille.
   Renvoie 0, ou -1 si une allocation échoue (rien à libérer dans ce cas). */
int saku_cm_compresser(const uint8_t *entree, size_t n, uint8_t **sortie, size_t *taille_sortie);

/* Décompresse exactement `taille` octets dans `sortie` (déjà allouée par l'appelant).
   Renvoie 0, ou -1 si une allocation interne échoue. */
int saku_cm_decompresser(const uint8_t *charge, size_t n, uint8_t *sortie, size_t taille);

void saku_cm_liberer(void *p);

/* Version de la spécification implémentée : renvoie 1. */
int saku_cm_version(void);
```

## Points où l'on se trompe

1. Types : `uint32_t` pour tout ce qui est `u32`, `int64_t` pour le produit scalaire du
   mélangeur et pour `x[i] * err`, `uint64_t` pour `(cible - p22) * DT[n]` et pour
   `(r >> 12) * p`. Écrire chaque `u32(...)` comme un calcul en `uint32_t` (le dépassement
   non signé est défini en C, il fait le modulo voulu).
2. `asr` : fonction `static int64_t asr(int64_t x, int n)` qui renvoie
   `x >= 0 ? x >> n : ~((~x) >> n)`. Ne jamais décaler un signé négatif directement.
3. État alloué sur le tas (`calloc`) : 5 tables de 2^22 `uint32_t`, `MT` de 2^20 `uint32_t`,
   `buf` de `n` octets (au décodage : `taille`). Libérer tout avant de rendre la main, y compris
   en cas d'échec d'une allocation intermédiaire.
4. Sortie du compresseur : tampon qui grandit (`realloc` en doublant), taille de départ
   `n / 2 + 64`.
5. Tables `T`, `S`, `DT` : construites dans une fonction d'initialisation appelée au début de
   chaque appel (pas de variable globale modifiable partagée entre fils : tout l'état est dans
   une structure locale).
6. `predire()` et `mettre_a_jour()` séparés, comme dans la spécification ; `mettre_a_jour`
   réutilise les cases, `im`, `x[i]` et `p` calculés par `predire`.
7. Section 7.2 : la mise à zéro de `lg` en cas de discordance se fait pendant `predire()`.
8. Au décodage, un octet lu au-delà de la fin de la charge vaut 0. Ne jamais lire `charge`
   hors de `[0, n)`.
9. Le fichier doit compiler sans avertissement avec
   `cc -std=c99 -O2 -Wall -Wextra -pedantic -fPIC -shared`.

## Exigences supplémentaires (après un premier essai rejeté)

- Le premier essai contenait un « placeholder » et plantait. **Aucun code provisoire** : chaque
  fonction est complète. Écris d'abord mentalement la structure, puis le fichier d'un trait.
- `predire()` mémorise dans l'état : les 6 cases, `im`, les 8 valeurs `x[i]` (en `int32_t`,
  elles sont signées) et `p`. `mettre_a_jour(y)` n'a pas d'autre paramètre que l'état et `y`.
- Au début de chaque appel, après l'initialisation des tables, calculer `h[1..5]` avec
  `pos = 0` (section 5).
- Pour `pos - j` avec `pos` de type `size_t`, tester `j <= pos` (pas `pos - j >= 0`).
