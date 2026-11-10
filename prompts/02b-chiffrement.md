# Mission

Écris le fichier `tests/test_chiffrement.py` de Saku. Il doit couvrir exactement ceci :

Nonce : valeurs exactes pour (0, False), (1, False), (2**40, True) ; unicité sur 1000 numéros ;
aller-retour ; rejet si un bit du chiffré change, si l'AAD change, si le numéro change, si le
drapeau « dernier » change, si la clé change ; mot de passe vide refusé ; dérivation
déterministe et sensible au sel.

Le contexte commun, la spécification et le code suivent.
