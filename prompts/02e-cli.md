# Mission

Écris le fichier `tests/test_cli.py` de Saku. Il doit couvrir exactement ceci :

`main([...])` : creer / lister / verifier / extraire en clair (codes de retour 0, sorties
utiles) ; un cycle chiffré via `SAKU_MOT_DE_PASSE` ; archive corrompue → code 1, une ligne
sur stderr, pas de `Traceback` ; le mot de passe n'est accepté par aucune option de ligne de commande.

Le contexte commun, la spécification et le code suivent.
