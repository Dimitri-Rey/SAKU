# Mission

Écris `bench/bench.py`, le banc de mesure de **Saku** (archiveur). Règle du projet : aucune
affirmation sans mesure, et une mesure fausse est pire que pas de mesure. Le script doit donc
vérifier lui-même chaque aller-retour et refuser d'afficher un chiffre non vérifié.

# Usage attendu

`python bench/bench.py CORPUS [CORPUS...] [--sortie bench/sorties] [--outils zstd-19,xz-9,...]`

Chaque `CORPUS` est un dossier. Pour chacun :

1. Lister les fichiers ordinaires (tri par chemin). `taille_brute` = somme de leurs tailles :
   c'est le dénominateur de TOUS les outils.
2. Fabriquer une fois un tar déterministe `sorties/<nom>.tar` avec le module `tarfile`
   (format PAX, entrées triées, `mtime=0`, `uid=gid=0`, `uname=gname=""`).
3. Pour chaque outil : compresser, décompresser, vérifier, mesurer.

# Outils (table déclarative en tête de fichier)

Une liste de dataclasses `Outil(nom, compresser, decompresser, entree)` où les commandes sont
des listes d'arguments contenant les jetons `{entree}`, `{archive}`, `{sortie}` ; `entree` vaut
`"tar"` ou `"dossier"`.

- `zstd-19` : `zstd -19 -T1 -q -f {entree} -o {archive}` / `zstd -d -q -f {archive} -o {sortie}`
- `zstd-22-long` : `zstd --ultra -22 --long=27 -T1 -q -f {entree} -o {archive}` / `zstd -d --long=27 -q -f {archive} -o {sortie}`
- `xz-9` : `xz -9 -T1 -k -c {entree}` avec stdout redirigé vers `{archive}` / `xz -d -c {archive}` vers `{sortie}`
  (prévois un champ booléen `vers_stdout` pour ces deux cas)
- `saku` (entrée `dossier`) : `[sys.executable, "-m", "saku.cli", "creer", "{archive}", "{entree}"]` /
  `[sys.executable, "-m", "saku.cli", "extraire", "{archive}", "-C", "{sortie}"]`
- Outils externes optionnels, ajoutés seulement si l'exécutable existe :
  `bench/externes/cmix/cmix` (`cmix -c {entree} {archive}` / `cmix -d {archive} {sortie}`) et
  `bench/externes/ts_zip/ts_zip` (`ts_zip c {entree} {archive}` / `ts_zip d {archive} {sortie}`),
  lancés avec `cwd` = le dossier de l'exécutable. Un outil absent est noté « non mesuré », jamais omis en silence.

# Mesures (par outil et par corpus)

- Lancer chaque commande avec `subprocess.Popen` puis `os.wait4(pid, 0)` : durée murale
  (`time.perf_counter`), et `ru_maxrss` du processus (Kio sous Linux) = RAM de pointe.
- `taille_archive` en octets ; `bits_par_octet = 8 * taille_archive / taille_brute` ;
  `ratio = taille_brute / taille_archive` ; débits en Mo/s (10^6 octets) = `taille_brute / durée`.
- Vérification : outils en entrée `tar` → SHA-256 du fichier décompressé = SHA-256 du tar.
  Outil en entrée `dossier` → chaque fichier extrait identique (SHA-256) à l'original, même
  nombre de fichiers. Échec de vérification, code de retour non nul ou dépassement de
  `--delai` secondes (défaut 3600, tuer le processus) → ligne marquée `ÉCHEC` avec la raison,
  sans chiffres.
- Supprimer archives et sorties intermédiaires après mesure (pas le tar).

# Sorties

- `sorties/resultats.json` : liste d'objets (corpus, outil, tous les champs, version de l'outil
  quand `--version` répond, date ISO, `platform.processor()`, nombre de cœurs).
- Sur stdout, un tableau Markdown par corpus, trié par `bits_par_octet` croissant :
  `| Outil | Taille | Ratio | bits/octet | Comp. Mo/s | Décomp. Mo/s | RAM comp. Mo | RAM décomp. Mo |`
  précédé d'une ligne donnant le corpus, le nombre de fichiers et `taille_brute`.

# Contraintes

Python 3.14, bibliothèque standard seule, typage complet, `from __future__ import annotations`,
docstrings et messages en français, lignes ≤ 100 caractères, jamais `shell=True`, fonctions
courtes, au plus 260 lignes. Pas de classe inutile, pas d'option non demandée.

# Format de ta réponse

Uniquement le contenu brut du fichier Python : pas de clôture Markdown, pas de texte avant ni après.
