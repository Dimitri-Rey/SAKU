# Journal des modifications

Format : [Keep a Changelog](https://keepachangelog.com/fr/1.1.0/). Versions :
[SemVer](https://semver.org/lang/fr/).

## [Non publié]

### Ajouté

- Site de présentation publié sur GitHub Pages : animation du parcours des fichiers,
  figures interactives (principe des tiroirs, coût d'un caractère selon la prédiction,
  codage arithmétique, divergence d'un décodeur non déterministe), démonstration
  AES-256-GCM dans le navigateur, graphiques des mesures.

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
