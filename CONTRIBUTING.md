# Contribuer à ce projet

Merci de votre intérêt pour la contribution ! Voici comment travailler proprement.

## Convention de nommage des branches

Une branche par fonctionnalité :

```
feat/<nom>           # nouvelle fonctionnalité
fix/<nom>            # correction de bug
docs/<nom>           # documentation
```

## Format des commits

Commits atomiques en **Conventional Commits** :

- `feat:` nouvelle fonctionnalité
- `fix:` correction de bug
- `refactor:` restructure sans changer le comportement
- `docs:` documentation
- `test:` tests
- `chore:` maintenance

Exemple :

```bash
git commit -m "feat: ajouter l'authentification par token"
```

## Flux de travail

1. Forker le dépôt.
2. Créer une branche depuis `main`.
3. Développer en petits incréments vérifiables (lint + tests).
4. Ouvrir une pull request avec la description remplie (voir le template PR).
5. Attendre la revue avant fusion.

## Avant de soumettre

- [ ] Le lint et les tests passent.
- [ ] Aucun secret dans le code.
- [ ] La documentation est à jour.
- [ ] Aucun chiffre de compression sans mesure reproductible (voir `docs/BENCHMARK.md`).
