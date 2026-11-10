# Mission

Écris le fichier `tests/test_format.py` de Saku. Il doit couvrir exactement ceci :

Aller-retour de l'en-tête, de l'en-tête de bloc et du pied ; taille exacte (80, 16, 16) ;
décalages exacts de la section 2 vérifiés octet par octet sur un en-tête connu ; rejets :
magic faux, version ≠ 0, drapeau inconnu, réservé non nul, CRC faux, incohérence
drapeau/aead/kdf, chaque borne Argon2 et `taille_bloc` (juste dessous et juste dessus).

Le contexte commun, la spécification et le code suivent.
