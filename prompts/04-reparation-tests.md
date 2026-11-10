# Mission

Le fichier de tests joint (le premier `<fichier>`) a des tests qui échouent ; la sortie de
`pytest` est jointe. Rends le fichier corrigé, en entier.

# Méthode (pour chaque test en échec)

1. Relis ce que la spécification `docs/FORMAT-v0.md` exige vraiment.
2. Décide qui a tort : le **test** (mauvaise manipulation d'octets, mauvaise attente, mauvais
   usage d'une fonction du socle) ou le **code**.
3. Si le test a tort : corrige-le pour qu'il vérifie réellement l'exigence, sans l'affaiblir.
   Interdits : supprimer le test, le marquer `skip`/`xfail`, remplacer une attente précise par
   `Exception`, retirer une assertion.
4. Si le code a tort : ne touche pas au test et ajoute juste au-dessus le commentaire
   `# DESACCORD: <ce que la spécification exige et que le code ne fait pas>`.

# Faits utiles (vérifiés)

- `contenus_de(racine)` rend les chemins relatifs à `racine` elle-même. Archiver `arbre`
  (dossier `projet/`) puis extraire dans `sortie` recrée `sortie/projet/...` : comparer
  `contenus_de(arbre)` à `contenus_de(sortie / "projet")`.
- `lire_index` et `remplacer_index` ne marchent que sur une archive NON chiffrée. Sur une
  archive chiffrée on ne peut ni lire ni refaire l'index sans la clé : les positions des blocs
  se retrouvent en parcourant le fichier (en-tête de bloc de 16 octets en position 80, puis
  `taille_charge` octets, etc.).
- `Archive.ouvrir` valide l'en-tête, le pied, l'index et l'en-tête de chaque bloc, mais ne lit
  la charge des blocs de données qu'à `lire`, `extraire` ou `verifier`. Une corruption de
  charge se détecte donc à `verifier()`, pas forcément à l'ouverture : c'est conforme.
- Une corruption détectée par un CRC ou par la confrontation index/en-tête lève
  `ArchiveInvalide` AVANT toute tentative de déchiffrement ; `EchecAuthentification` ne sort
  que si les contrôles en clair passent. Pour tester l'authentification elle-même, il faut
  donc recalculer `crc_charge` (CRC-32 de la charge sur disque) après avoir modifié la charge,
  ou accepter `ErreurSaku` quand l'exigence est seulement « rejet ».
- `ARGON2_RAPIDE` est une constante de `conftest`, `arbre` une fixture (paramètre du test).
- `Path.read_bytes()` rend des `bytes` immuables : passer par `bytearray`.
- `argparse` termine par `SystemExit(2)` sur une option inconnue : c'est le comportement voulu.
- `creer_archive` et `saku creer` refusent d'écraser une destination existante.
- La CLI `saku lister` affiche la taille puis le chemin ; `saku creer` n'affiche rien.

# Format de ta réponse

Uniquement le contenu brut du fichier Python corrigé : pas de clôture Markdown, pas de texte
avant ni après.
