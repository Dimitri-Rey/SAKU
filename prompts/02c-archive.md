# Mission

Écris le fichier `tests/test_archive.py` de Saku. Il doit couvrir exactement ceci :

- Aller-retour identique au bit près (contenu, mode, mtime_ns) en clair et chiffré, sur un
  arbre mêlant : fichier vide, texte UTF-8 accentué, binaire aléatoire, fichier de 3,5 blocs,
  fichier de taille exactement `taille_bloc`, sous-dossiers, nom avec espace et accent.
- Archive sans aucun fichier (dossier vide) : se crée, s'ouvre, se vérifie.
- Routage : dans `Archive.fichiers`, tous les textes précèdent tous les binaires, tri par
  (extension, chemin) dans chaque groupe.
- Données aléatoires : la taille de l'archive ne dépasse pas la taille d'origine de plus de
  1 % + 1 Kio (preuve du repli en codec 0), en clair et chiffré.
- `lire()` d'un seul fichier rend le bon contenu ; chemin inconnu → erreur.
- Extraction partielle (`chemins=[...]`) : seuls les fichiers demandés existent.
- Mauvais mot de passe → `EchecAuthentification` ; archive chiffrée sans mot de passe →
  `MotDePasseRequis` ; destination déjà existante → `FileExistsError`.
- Deux archives chiffrées des mêmes données avec le même mot de passe diffèrent (sel).
- Archive en clair : deux créations des mêmes données donnent des octets identiques
  (déterminisme de l'écriture).

Le contexte commun, la spécification et le code suivent.
