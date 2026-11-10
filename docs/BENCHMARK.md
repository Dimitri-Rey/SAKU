# Mesures

Règle du projet : aucun chiffre sans mesure, aucune mesure sans vérification. Tout ce qui suit
sort de `bench/bench.py`, qui compresse, décompresse, puis compare la sortie à l'entrée octet
pour octet. Un outil qui échoue, dépasse le délai ou rend autre chose que l'entrée n'a pas de
chiffre : la ligne porte la raison.

## Protocole

- **Dénominateur commun.** La taille brute d'un corpus est la somme des tailles de ses
  fichiers. Elle sert pour tous les outils.
- **Entrée.** zstd, xz, cmix et ts_zip reçoivent un tar déterministe du corpus (format PAX,
  entrées triées, dates et propriétaires à zéro). Saku reçoit le dossier lui-même.
- **Vérification.** Pour les outils à tar : SHA-256 du tar décompressé égal à celui du tar
  d'origine. Pour Saku : même liste de fichiers et même SHA-256 pour chacun.
- **Temps.** Durée murale de la commande, un seul fil pour zstd et xz (`-T1`). Les débits sont
  en Mo/s (10⁶ octets de données brutes par seconde).
- **Mémoire.** Pointe de mémoire résidente du processus (`ru_maxrss`), en Mio.
- **Modèle compris.** Quand le décodeur a besoin d'un modèle, sa taille est ajoutée à celle de
  l'archive dans la colonne « Ratio, modèle compris ». Pour ts_zip : `rwkv_169M_q8.bin`,
  171 363 973 octets. Les exécutables eux-mêmes ne sont pas comptés.
- **Une seule exécution par mesure.** Les temps sont donc indicatifs, à quelques pour cent
  près ; les tailles, elles, sont exactes et reproductibles.

### Ce qui n'est pas comparable terme à terme

- À la décompression, Saku écrit chaque fichier, contrôle son empreinte SHA-256 et restaure
  ses droits et sa date. Les autres outils ne font que reproduire un tar, sans le déballer.
- Saku est un prototype en Python ; zstd et xz sont des programmes C optimisés depuis des
  années.

## Machine et versions

- 2 × Intel Xeon E5-2678 v3 à 2,50 GHz (48 fils), 62 Gio de mémoire, Fedora 44, noyau 7.2.
- Python 3.14, zstd 1.5.7, xz 5.8.2, cmix 21, ts_zip du 2024-03-02 avec `rwkv_169M_q8.bin`,
  sur processeur seul (pas de carte graphique).
- Mesures du 2026-11-10, Saku 0.1.0.

## Corpus

| Nom | Contenu | Reproductible par un tiers |
|---|---|---|
| `cpython` | Sources de CPython 3.14.0, archive officielle `Python-3.14.0.tar.xz` (SHA-256 `2299dae542d395ce3883aca00d3c910307cd68e0b2f7336098c8e7b7eee9f3e9`) | oui |
| `code-perso` | Code d'applications privées : surtout Python, Markdown, JavaScript et TypeScript | non, corpus non distribué |
| `…-echantillon` | Environ 1 Mo tiré de chacun des deux, fichiers pris dans l'ordre du SHA-256 de leur chemin (`--echantillon 1000000`) | comme le corpus d'origine |

Les échantillons existent parce que cmix et ts_zip sont trop lents pour les corpus entiers.

## Résultats

<!--MESURES-->
**code-perso — 709 fichiers, 11 938 143 octets**

| Outil | Archive (octets) | bits/octet | Ratio | Ratio, modèle compris | Compression (Mo/s) | Décompression (Mo/s) | Mémoire compr. (Mio) | Mémoire décompr. (Mio) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| zstd-19 | 1 787 014 | 1,198 | 6,68 | 6,68 | 3,2 | 375,6 | 98 | 24 |
| zstd-22-long | 1 783 228 | 1,195 | 6,69 | 6,69 | 1,8 | 378,6 | 282 | 26 |
| xz-9 | 1 753 708 | 1,175 | 6,81 | 6,81 | 2,8 | 125,9 | 174 | 26 |
| saku | 1 841 226 | 1,234 | 6,48 | 6,48 | 3,1 | 25,3 | 132 | 54 |
| saku-chiffre | 1 841 277 | 1,234 | 6,48 | 6,48 | 2,7 | 11,2 | 284 | 284 |
| saku-cm | 1 664 426 | 1,115 | 7,17 | 7,17 | 0,729 | 0,703 | 136 | 126 |

**cpython — 5 045 fichiers, 112 691 061 octets**

| Outil | Archive (octets) | bits/octet | Ratio | Ratio, modèle compris | Compression (Mo/s) | Décompression (Mo/s) | Mémoire compr. (Mio) | Mémoire décompr. (Mio) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| zstd-19 | 23 971 699 | 1,702 | 4,70 | 4,70 | 2,1 | 649,7 | 206 | 40 |
| zstd-22-long | 23 200 760 | 1,647 | 4,86 | 4,86 | 1,4 | 425,3 | 846 | 115 |
| xz-9 | 22 909 784 | 1,626 | 4,92 | 4,92 | 2,1 | 101,9 | 674 | 67 |
| saku | 24 384 040 | 1,731 | 4,62 | 4,62 | 2,5 | 45,1 | 147 | 73 |
| saku-chiffre | 24 384 168 | 1,731 | 4,62 | 4,62 | 2,6 | 35,9 | 284 | 284 |
| saku-cm | 23 107 271 | 1,640 | 4,88 | 4,88 | 0,771 | 0,765 | 150 | 146 |

<!--/MESURES-->

## Lecture

### Codec 2 (`--codec cm`, mélange de contextes en entiers)

- **Sur `code-perso`, il bat tous les autres outils mesurés** : 1 664 426 octets, soit 5,1 % de
  moins que `xz -9` et 6,9 % de moins que `zstd -19`.
- **Sur `cpython`, il reste 0,9 % derrière `xz -9`** (23 107 271 octets contre 22 909 784),
  mais passe devant `zstd -19` (−3,6 %) et `zstd --ultra -22 --long` (−0,4 %).
- **L'écart avec xz sur `cpython` est presque entièrement celui de l'index** : 219 777 octets,
  dont 161 440 d'empreintes SHA-256 (32 octets par fichier, incompressibles par nature).
  Les données seules tiennent en 22 887 398 octets, moins que l'archive xz entière.
- **Blocs plus grands** : avec des blocs de 64 Mio au lieu de 8, l'archive `cpython` passe à
  22 920 441 octets, à 0,05 % de `xz -9`. Archive relue entièrement par `saku verifier`
  (5 045 empreintes conformes) ; cette variante n'est pas passée par le banc, donc pas de
  mesure de vitesse ni de mémoire. La taille de bloc n'est pas encore réglable en ligne de
  commande.
- **Le prix est la vitesse** : 0,7 à 0,8 Mo/s, dans les deux sens, contre 2 à 650 Mo/s pour
  zstd et xz. Mémoire de pointe : environ 150 Mio.
- **Aucun modèle externe** : la colonne « modèle compris » est égale au ratio.

### Saku avec zstd (codec par défaut)

- Il ne fait pas mieux que zstd, et c'est attendu : il utilise zstd niveau 19 par blocs
  indépendants, et son index porte une empreinte par fichier. Son archive est plus grosse que
  celle de `zstd -19` de 3,0 % (`code-perso`) et 1,7 % (`cpython`).
- **Le chiffrement ne coûte presque rien en taille** : 51 octets de plus sur `code-perso`,
  128 sur `cpython`. Il coûte de la mémoire (Argon2id réserve 256 Mio) et un peu de temps.

### cmix et ts_zip

- **cmix** n'a pas fini l'échantillon d'1 Mo de `code-perso` en 5 400 secondes : il est
  marqué « non mesuré » plutôt qu'estimé.
- **ts_zip**, sur processeur seul, est en cours de mesure sur les échantillons.

## Reproduire

```bash
uv run python bench/bench.py CHEMIN/cpython --outils zstd-19,zstd-22-long,xz-9,saku,saku-chiffre
uv run python bench/bench.py CHEMIN/cpython --echantillon 1000000 --delai 5400
uv run python outils/rapport.py bench/sorties/resultats-*.json
```

cmix et ts_zip sont cherchés dans `bench/externes/cmix/cmix` et `bench/externes/ts_zip/ts_zip` ;
absents, ils sont notés « non mesuré ».
