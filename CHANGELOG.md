# Journal des modifications

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/). Versions :
[SemVer](https://semver.org/lang/fr/).

## [Non publié]

### Ajouté

- **Codec 3** (`--codec cm`) : mélange de contextes v2, spécifié dans `docs/CODEC-3.md` —
  seaux vérifiés, contexte « mot », deux APM, poids choisis selon la correspondance. Référence
  Python (`saku.cm3_reference`) et C99 (`src/saku/_cm/cm3.c`) identiques octet pour octet ;
  vecteurs dans `tests/test_cm3.py`. ADR 0003. Le codec 2 reste lisible et s'écrit encore
  avec `--codec cm1`.
- Option `--taille-bloc` (en Mio) de `saku creer`.
- `docs/RECHERCHE-MODELES.md` : décisions sur le futur codec neuronal (un modèle unique livré,
  lecture sur processeur garantie, niveaux de modèles), mesure du plafond de Qwen3.8-27B,
  état de l'art (Qwen3.5, ts_zip, Nacrith, calcul entier, poids ternaires), test ARM64.
- **Blocs traités en parallèle** à l'écriture et à la lecture (option `--fils`, paramètre
  `fils`) : l'archive produite ne dépend pas du nombre de fils. CPython au codec 3 : de
  0,8 à 7,4 Mo/s en compression, de 0,8 à 8,0 Mo/s en décompression.
- Codec 3 en C : préchargement des seaux et pages mémoire de 2 Mio, environ +20 % par cœur,
  octets inchangés.
- **Codec 2** (`--codec cm`) : mélange de contextes en arithmétique entière, spécifié dans
  `docs/CODEC-2.md`. Référence en Python (`saku.cm_reference`) et version C99
  (`src/saku/_cm/cm.c`, compilée à la première utilisation) qui produisent les mêmes octets ;
  vecteurs de contrôle dans `tests/test_cm.py`. ADR 0002.
- Option `--codec` de `saku creer` et paramètre `codec` de `creer_archive`.
- Mesures du codec 2 dans `docs/BENCHMARK.md`.
- Site de présentation publié sur GitHub Pages : animation du parcours des fichiers,
  figures interactives (principe des tiroirs, coût d'un caractère selon la prédiction,
  codage arithmétique, divergence d'un décodeur non déterministe), démonstration
  AES-256-GCM dans le navigateur, graphiques des mesures.

### Corrigé

- `Archive.ouvrir`, `Archive.extraire` et `creer_archive` acceptent des chemins en texte,
  comme le montrait déjà l'exemple du README.

### Modifié

- Le codec 2 n'est plus « réservé au codec neuronal » : il désigne le mélange de contextes.
  Un réseau pré-entraîné prendra un nouvel identifiant.

## [0.1.0] - 2026-11-10

### Ajouté

- Spécification du format d'archive v0 (`docs/FORMAT-v0.md`).
- Bibliothèque Python `saku` : création, lecture, vérification et extraction d'archives.
- Compression zstd par blocs indépendants, avec repli « stocké ».
- Chiffrement authentifié AES-256-GCM, clé dérivée du mot de passe par Argon2id.
- Commande `saku` : `creer`, `extraire`, `lister`, `verifier`.
- Suite de tests, dont un lot d'archives hostiles (corruption, troncature, chemins piégés).
- Banc de mesure `bench/bench.py` et premiers résultats (`docs/BENCHMARK.md`).
- Outil et prompts de pilotage d'un modèle local (`outils/qwen.py`, `prompts/`).
