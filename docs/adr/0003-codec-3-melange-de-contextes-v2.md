# ADR 0003 — Codec 3 : mélange de contextes v2

- Statut : accepté
- Date : 2026-11-11

## Contexte

Le codec 2 bat `xz -9` sur le code applicatif mais pas sur CPython, et reste sous 1 Mo/s. Sa
spécification (§11) promet qu'une archive écrite avec lui reste lisible : toute amélioration
du modèle doit donc prendre un autre identifiant.

## Décision

Un codec 3 (`docs/CODEC-3.md`), toujours entièrement en entiers et sans modèle externe :

- seaux vérifiés de 16 compteurs par demi-octet pour les ordres 2, 3, 4 et 6 ;
- ordre 1 en table directe, contexte « mot » ;
- compteurs à adaptation rapide (limite 20) sauf celui de la correspondance ;
- poids du mélangeur choisis selon `c0` et la longueur de correspondance ;
- deux APM après le mélangeur.

Chaque élément a été gardé parce qu'il améliore la taille sur deux blocs de 8 Mio (code
applicatif et CPython) ; retirer l'un d'eux coûte de 0,7 % (mot) à 1,8 % (APM).

`--codec cm` désigne désormais le codec 3 ; `--codec cm1` écrit encore du codec 2. Les deux
restent lisibles. La méthode de redondance de l'ADR 0002 est reconduite : spécification par
Claude, référence Python par Qwen (corrigée, cinq erreurs), C par Claude ; identité octet pour
octet vérifiée sur des entrées de test et sur 200 Ko de code réel.

`--taille-bloc` (en Mio) devient une option de la ligne de commande.

## Conséquences

- Environ 195 Mio de mémoire par bloc au lieu de 90 Mio ; même ordre de vitesse.
- Deux codecs de mélange à maintenir ; le codec 2 n'évoluera plus.
- Les tables de 2^19 seaux sont un compromis : 2^20 gagnerait encore 0,3 % pour 160 Mio de plus.
