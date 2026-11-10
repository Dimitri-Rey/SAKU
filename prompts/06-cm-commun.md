# Contexte

Projet **Saku** (archiveur libre, Python 3.14). Le fichier `docs/CODEC-2.md` joint est la
spécification du **codec 2** : un compresseur sans perte par mélange de contextes, en
arithmétique **entière** uniquement. Elle fait autorité.

Deux implémentations sont écrites séparément à partir de cette seule spécification, l'une en
Python, l'autre en C. Elles devront produire **exactement les mêmes octets**. La moindre
liberté prise avec la spécification (ordre des opérations, arrondi, décalage, valeur
initiale, condition de boucle) fera diverger les deux sorties, et ton travail sera rejeté.

# Règles

- Suis la spécification ligne par ligne, dans l'ordre où elle décrit les opérations.
  Reprends ses noms (`c0`, `bp`, `lg`, `ptr`, `MT`, `MM`, `O0`, `W`, `squash`, `stretch`…).
- Aucune virgule flottante, nulle part, même pour construire une table.
- N'invente aucune optimisation qui change un résultat. N'ajoute aucun modèle, aucun étage.
- Pas d'explication autour du code. Réponds uniquement avec le ou les fichiers demandés, au
  format ci-dessous.

# Format de réponse

```
=== FICHIER: chemin/du/fichier ===
contenu complet du fichier
```
