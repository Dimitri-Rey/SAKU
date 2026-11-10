# ADR 0002 — Codec 2 : mélange de contextes en arithmétique entière

- Statut : accepté
- Date : 2026-11-10

## Contexte

Le premier verrou du projet est le déterminisme : un codec à prédiction n'est utilisable que si
le décodeur retrouve exactement les mêmes probabilités que l'encodeur, sur n'importe quelle
machine. Avant d'entraîner un réseau de neurones, il faut prouver trois choses avec le modèle
le plus simple qui puisse battre xz :

1. qu'un prédicteur entièrement en entiers peut être spécifié sans ambiguïté ;
2. que deux implémentations écrites séparément à partir de la spécification produisent les
   mêmes octets ;
3. que ce prédicteur, sans aucun modèle pré-entraîné, compresse le code mieux que xz -9.

## Décision

- **Codec 2 = mélange de contextes** (famille PAQ) : ordres 0 à 6 et un modèle de
  correspondance, combinés par un mélangeur logistique appris en direct (un réseau à une
  couche), puis un codeur arithmétique binaire sur 32 bits. Tout en entiers ; les fonctions
  `squash` et `stretch` sont des tables fixes écrites dans la spécification.
- **La spécification fait autorité** ([CODEC-2.md](../CODEC-2.md)). Elle est vérifiée par
  deux implémentations : une référence en Python (lente, lisible, juge) et une version en C99
  (rapide, chargée par `ctypes`, compilée à la première utilisation). Les tests exigent
  l'égalité octet pour octet des deux sorties et fixent des vecteurs de contrôle.
- **Le modèle repart de zéro à chaque bloc.** Pas de modèle externe : `empreinte_modele`
  reste à zéro. L'accès direct par bloc est préservé.
- **zstd reste le codec par défaut**, le codec 2 est demandé par `--codec cm`, tant que sa
  vitesse n'est pas acceptable pour un usage courant.
- Un réseau pré-entraîné viendra comme **un autre identifiant de codec**, avec son empreinte
  dans l'en-tête ; le codec 2 v1 reste lisible tel quel.

## Conséquences

- Gain de taille mesuré dans [BENCHMARK.md](../BENCHMARK.md) ; vitesse de l'ordre du
  mégaoctet par seconde, mémoire d'environ 90 Mio par bloc.
- Sans compilateur C, la référence Python prend le relais : même résultat, beaucoup plus lent.
- La reproductibilité est prouvée entre deux langages et entre niveaux d'optimisation du
  compilateur (`-O0` à `-O3 -march=native`) ; elle reste à prouver sur une autre architecture
  (ARM64).

## Options écartées

- **Réseau de neurones d'emblée** : trop de variables à la fois (entraînement, quantification,
  vitesse) avant d'avoir prouvé la chaîne déterministe.
- **Virgule flottante avec arrondis contrôlés** : la moindre différence de bibliothèque
  mathématique ou d'ordre d'addition casse l'archive ; impossible à garantir.
- **Reprendre le code de lpaq ou de paq8** : licences GPL, incompatibles avec la licence MIT
  du projet. Saku réutilise les idées publiées, pas le code.
