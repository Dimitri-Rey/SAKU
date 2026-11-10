# Mission

Écris le fichier `tests/test_archive_hostile.py` de Saku. Il doit couvrir exactement ceci :

- Corruption, pour une archive en clair ET une chiffrée (paramétrer) : inverser un bit à
  chaque position d'une petite archive (toutes les positions si < 3000 octets, sinon un pas
  régulier) → dans TOUS les cas, soit `ouvrir`+`verifier` lève `ErreurSaku`, soit — toléré
  uniquement pour l'archive en clair — le contenu extrait est strictement identique à
  l'original. Jamais de contenu différent rendu sans erreur.
- Troncature à chaque longueur (pas régulier) → `ErreurSaku`. Octets ajoutés à la fin → `ErreurSaku`.
- Archive chiffrée : échanger deux blocs de données de même taille (en recalculant ce qu'il
  faut) → `ErreurSaku`.
- Index hostile, archive en clair fabriquée en réécrivant le bloc d'index (JSON modifié,
  recompressé en zstd, CRC et pied recalculés) : chemin `../evasion`, chemin absolu `/tmp/x`,
  chemin avec `a//b`, avec `.`, avec antislash, doublon de chemin, `taille` négative, somme des
  tailles incohérente, `position` hors du fichier, `taille_claire` supérieure à `taille_bloc`
  → `ArchiveInvalide` dès l'ouverture, et rien n'est écrit hors de la destination.
- Lien symbolique piégé : la destination contient `projet -> /ailleurs` ; extraire un fichier
  `projet/a.txt` doit lever une erreur et ne rien écrire dans `/ailleurs` (un dossier de `tmp_path`).
- SHA-256 faux dans l'index (archive en clair refabriquée) → erreur à `lire`, `extraire` et
  `verifier`, et aucun fichier définitif laissé par `extraire`.
- Bits de mode : un fichier archivé avec setuid (index refabriqué, mode `0o4755`) est extrait en `0o755`.

Le contexte commun, la spécification et le code suivent.
