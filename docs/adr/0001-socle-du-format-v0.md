# ADR 0001 — Socle du format v0

- Statut : accepté
- Date : 2026-11-10

## Contexte

Saku vise un archiveur libre qui compresse puis chiffre, avec à terme un codec neuronal sans
perte pour le texte et le code. Avant d'écrire ce codec, il faut un conteneur fiable et un banc
de mesure, sinon aucun gain ne pourra être prouvé.

## Décisions

1. **Premier type visé : code source et texte.** C'est là que les modèles de langage apportent
   le plus par rapport à LZ77, et les corpus libres ne manquent pas pour mesurer.
2. **Premier verrou attaqué : le déterminisme.** Un codec neuronal qui ne redonne pas exactement
   les mêmes probabilités sur une autre machine produit une archive illisible. Tant que ce point
   n'est pas réglé, tout gain de ratio est sans valeur. Le codec 2 est donc réservé à une
   inférence en arithmétique entière, et rien d'autre.
3. **Archive solide découpée en blocs indépendants** (8 Mio par défaut). Les fichiers proches
   sont rangés côte à côte ; chaque bloc se lit seul, ce qui donne l'accès aléatoire et borne la
   mémoire du lecteur.
4. **Compresser puis chiffrer, avec AES-256-GCM et Argon2id** de la bibliothèque `cryptography`.
   Une clé par archive (sel aléatoire), un nonce à compteur par bloc, l'en-tête lié à chaque
   bloc par les données associées. Aucun algorithme maison.
5. **Repli zstd.** Tout ce que le futur codec ne sait pas mieux compresser passe par zstd
   niveau 19, ou est stocké tel quel si la compression ne gagne rien.

## Conséquences

- Un bloc indépendant ne profite pas du contenu des blocs précédents : sur un gros corpus,
  Saku v0 compresse moins bien qu'un zstd à grande fenêtre. C'est mesuré dans
  [BENCHMARK.md](../BENCHMARK.md).
- Les tailles de blocs restent visibles dans une archive chiffrée.
- Le format v0 n'a ni correction d'erreurs ni ajout de fichiers ; voir
  [FORMAT-v0.md](../FORMAT-v0.md), section 9.

## Options écartées

- **XChaCha20-Poly1305** : aussi solide, mais `cryptography` ne fournit que ChaCha20-Poly1305
  à nonce de 12 octets, pas la variante X ; l'identifiant `id_aead` permet de l'ajouter plus tard.
- **Compression fichier par fichier** : accès direct trivial, mais ratio médiocre sur les
  petits fichiers de code.
- **Inférence en virgule flottante** : plus rapide à écrire, non reproductible d'une machine à
  l'autre.
