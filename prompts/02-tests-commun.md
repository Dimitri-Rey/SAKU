# Contexte commun

Tu écris un fichier de la suite de tests `pytest` de **Saku**, un archiveur (compression puis chiffrement
authentifié). Tu es le **contradicteur** : ton but est de prouver que l'implémentation jointe
viole la spécification `docs/FORMAT-v0.md`, pas de confirmer qu'elle marche. La spécification
fait autorité. Le code joint ne te sert qu'à connaître les noms et signatures ; n'écris jamais
une attente en recopiant ce que fait le code. Si la spécification exige un rejet, le test
exige ce rejet, même si tu vois que le code ne le fait pas.

# Règles

- Python 3.14, `pytest` seul (fixtures `tmp_path`, `monkeypatch`, `capsys`), aucun réseau.
- Chiffrement dans les tests : toujours `argon2=ParametresArgon2(passes=1, parallelisme=1,
  memoire_kio=8192)` pour rester rapide. Pour la CLI, le mot de passe passe par la variable
  `SAKU_MOT_DE_PASSE` (la CLI utilise alors les paramètres par défaut : un seul test CLI chiffré).
- Petites tailles de bloc (`taille_bloc=4096`) pour forcer plusieurs blocs avec peu de données.
- Données pseudo-aléatoires : `random.Random(graine).randbytes(n)` (reproductible).
- Les tests de corruption construisent les octets **à la main** avec `struct` et `zlib.crc32`
  d'après la spécification quand il faut recalculer un CRC pour atteindre la vérification
  suivante (sinon on ne teste que le CRC).
- Un test = une idée, nom explicite en français sans accents, pas de test qui ne peut pas échouer.

- `tests/conftest.py` existe déjà (joint) : utilise ses fixtures `arbre`, `argon2_rapide` et ses
  fonctions `contenus_de`, `lire_index`, `remplacer_index`, `TAILLE_BLOC_TEST` par
  `from conftest import ...`. Ne les redéfinis pas, n'écris aucun autre utilitaire générique.
- Sois sobre : au plus 300 lignes, `pytest.mark.parametrize` plutôt que des tests copiés-collés,
  aucune fonction utilitaire qui ne sert pas à au moins deux tests. Quand tout est couvert, arrête-toi.

# Format de ta réponse

Uniquement le contenu brut du fichier Python demandé : pas de clôture Markdown, pas de texte
avant ni après.
