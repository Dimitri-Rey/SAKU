# Saku

Archiveur libre qui **compresse puis chiffre**, avec un format documenté et un lecteur qui se
méfie de tout ce qu'il lit. À terme : un codec neuronal sans perte pour le texte et le code,
reproductible au bit près d'une machine à l'autre.

> **État : prototype (0.1.0).** Le conteneur, le chiffrement et le banc de mesure existent et
> sont testés. Le codec neuronal n'existe pas encore : aujourd'hui Saku compresse avec zstd,
> et ne fait donc pas mieux que zstd. Le format v0 peut encore changer ; ne confiez pas à Saku
> la seule copie d'un fichier.

## Ce que Saku ne promet pas

- **Pas de ratio universel.** Compresser n'importe quel gigaoctet en un mégaoctet est
  impossible (argument de comptage, borne de Shannon). Des données déjà compressées ou
  aléatoires ne rétrécissent pas.
- **Pas de chiffre sans mesure.** Tout résultat annoncé est dans
  [docs/BENCHMARK.md](docs/BENCHMARK.md), avec la commande qui le reproduit.
- **Pas de génératif sur du texte ou des chiffres.** Sans perte par défaut, toujours. Un mode
  avec perte ne concernera que les médias, et seulement sur demande explicite.

## Installation

Il faut Linux ou macOS, **Python 3.14 ou plus récent** (le module `compression.zstd` de la
bibliothèque standard est utilisé) et [uv](https://docs.astral.sh/uv/).

```bash
git clone https://github.com/Dimitri-Rey/SAKU.git
cd SAKU
uv sync
uv run saku --help
```

## Utilisation

```bash
uv run saku creer projet.saku mon-projet/            # archive compressée
uv run saku creer --chiffrer secret.saku mon-projet/ # compressée puis chiffrée
uv run saku lister projet.saku
uv run saku verifier projet.saku                     # relit et contrôle tout le contenu
uv run saku extraire projet.saku -C sortie/
uv run saku extraire projet.saku -C sortie/ mon-projet/src/main.py
```

Le mot de passe est demandé au clavier, ou lu dans la variable `SAKU_MOT_DE_PASSE`. Il ne se
passe jamais en argument : il resterait dans l'historique du shell et dans la liste des
processus.

En Python :

```python
from saku import Archive, creer_archive

creer_archive("projet.saku", ["mon-projet"], mot_de_passe="phrase longue et unique")
with Archive.ouvrir("projet.saku", "phrase longue et unique") as archive:
    for fichier in archive.fichiers:
        print(fichier.taille, fichier.chemin)
    contenu = archive.lire("mon-projet/README.md")
```

## Fonctionnement en bref

1. **Collecte.** Les dossiers sont parcourus sans suivre les liens symboliques ; chaque fichier
   reçoit une empreinte SHA-256.
2. **Routage.** Les fichiers sont classés (texte ou autre), puis rangés par extension et par
   chemin, pour que les contenus qui se ressemblent soient voisins.
3. **Blocs.** Le flux obtenu est découpé en blocs indépendants de 8 Mio. Un bloc ne mélange pas
   texte et binaire.
4. **Compression.** Chaque bloc est compressé (zstd niveau 19), ou stocké tel quel s'il n'y a
   rien à gagner.
5. **Chiffrement** (facultatif). Chaque bloc est scellé par AES-256-GCM. La clé vient du mot de
   passe par Argon2id ; l'en-tête de l'archive est lié à chaque bloc.
6. **Index et pied.** La liste des fichiers et des blocs est écrite en fin d'archive, elle aussi
   compressée et chiffrée. On peut donc lire un fichier sans tout décompresser.

Le détail octet par octet est dans [docs/FORMAT-v0.md](docs/FORMAT-v0.md) ; les raisons des
choix dans [docs/adr/](docs/adr/) ; ce qui pourrait faire échouer le projet dans
[docs/RISQUES.md](docs/RISQUES.md).

## Feuille de route

| Étape | État |
|---|---|
| Format v0, conteneur, chiffrement, tests d'archives hostiles | fait |
| Banc de mesure contre zstd, xz, cmix et ts_zip | fait |
| Codec neuronal sans perte en arithmétique entière (codec 2) | à faire, c'est le cœur du projet |
| Test de reproductibilité entre machines et architectures | à faire |
| Conteneurs déjà compressés (.docx, .zip, JPEG) déballés et reconstruits à l'identique | à faire |
| Correction d'erreurs, clé enveloppée, ajout de fichiers | à faire |
| Mode avec perte pour les médias, sur demande explicite uniquement | plus tard |

## Développement

```bash
uv run pytest -q          # tests
uv run ruff check .       # lint
uv run ruff format .      # mise en forme
uv run python bench/bench.py CHEMIN/DU/CORPUS   # mesures
```

Une partie du code et des tests a été écrite par un modèle local (Qwen), piloté par les prompts
versionnés dans [`prompts/`](prompts/) avec [`outils/qwen.py`](outils/qwen.py), puis relue et
corrigée. La logique du lecteur et de l'écrivain d'archive est écrite à la main.

### À faire

- Mesurer avant d'affirmer, et vérifier chaque aller-retour octet pour octet.
- Compter la taille du décodeur, modèle compris, dans tout ratio annoncé.
- Traiter toute archive comme hostile : borner avant d'allouer, vérifier avant d'écrire.
- Garder les changements petits, chacun avec ses tests.

### À ne surtout pas faire

- Inventer un algorithme de chiffrement, ou « améliorer » un algorithme standard.
- Chiffrer avant de compresser.
- Introduire de la virgule flottante dans un codec sans perte.
- Activer un mode avec perte par défaut, ou l'appliquer à du texte ou à des chiffres.
- Commiter un corpus privé, une archive ou un secret.

## Licence

[MIT](LICENSE).
