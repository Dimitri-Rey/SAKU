# Mission

Tu implémentes le prototype Python de **Saku**, un archiveur open source (compression puis
chiffrement authentifié). La spécification du format est jointe plus bas
(`docs/FORMAT-v0.md`) : elle fait autorité. Si ton code et la spécification divergent, c'est
ton code qui a tort. N'invente aucun champ, aucune option, aucun comportement hors
spécification.

Ce code protège des données : un lecteur qui accepte une archive invalide, ou qui écrit un
fichier faux sans le dire, est un échec plus grave qu'un plantage. Dans le doute, lève une
erreur.

# Environnement

- Python 3.14, typage complet, `from __future__ import annotations`.
- Bibliothèque standard + `cryptography` 46 uniquement. Compression : module standard
  `compression.zstd` (`from compression import zstd` ; `zstd.compress(data, level=19)`,
  `zstd.ZstdDecompressor().decompress(data, max_length=n)`, erreurs `zstd.ZstdError`).
- Chiffrement : `cryptography.hazmat.primitives.ciphers.aead.AESGCM` et
  `cryptography.hazmat.primitives.kdf.argon2.Argon2id(salt=, length=32, iterations=,
  lanes=, memory_cost=)` puis `.derive(mot_de_passe_octets)`. Rien d'autre, rien de maison.
- Identifiants, docstrings, messages d'erreur : en français, sans accents dans les
  identifiants. Lignes ≤ 100 caractères. Le code doit passer `ruff` (règles E,F,W,I,B,UP,S,SIM,RUF).

# Fichiers à produire (exactement ceux-ci)

## `src/saku/__init__.py`
Exporte `__version__ = "0.1.0"` et les noms publics ci-dessous.

## `src/saku/erreurs.py`
`ErreurSaku(Exception)` et ses filles : `ArchiveInvalide` (structure, CRC, bornes, chemin
dangereux, empreinte de fichier fausse), `EchecAuthentification` (mauvais mot de passe ou
archive modifiée : ne pas distinguer les deux), `MotDePasseRequis`.

## `src/saku/format.py`
Constantes de la spécification et (dé)sérialisation pure, sans entrée-sortie :
- `@dataclass(frozen=True) class EnTete` avec `vers_octets() -> bytes` et
  `@classmethod depuis_octets(cls, donnees: bytes) -> EnTete` (valide TOUT ce que la section 2 exige).
- `@dataclass(frozen=True) class EnTeteBloc`, mêmes deux méthodes (section 3).
- `pied_vers_octets(position_index: int) -> bytes`, `pied_depuis_octets(donnees: bytes) -> int`.
- `@dataclass(frozen=True) class ParametresArgon2(passes: int = 3, parallelisme: int = 4,
  memoire_kio: int = 262_144)`.

## `src/saku/chiffrement.py`
- `deriver_cle(mot_de_passe: str, sel: bytes, parametres: ParametresArgon2) -> bytes`
- `nonce_bloc(numero: int, est_dernier: bool) -> bytes`
- `chiffrer_bloc(cle, numero, est_dernier, clair, aad) -> bytes` et `dechiffrer_bloc(...)`
  (lève `EchecAuthentification`).

## `src/saku/codecs.py`
`compresser(id_codec: int, clair: bytes) -> bytes`, `decompresser(id_codec: int, charge: bytes,
taille_claire: int) -> bytes` (limite de sortie stricte, taille vérifiée, `ArchiveInvalide`
sinon). Codecs 0 et 1. Codec inconnu ou 2 → `ArchiveInvalide` explicite.

## `src/saku/routage.py`
`est_texte(contenu: bytes) -> bool` et `ordonner(fichiers)` selon la section 7.

## `src/saku/archive.py`
- `creer_archive(destination: Path, sources: Sequence[Path], *, mot_de_passe: str | None = None,
  taille_bloc: int = 8 * 1024 * 1024, niveau: int = 19,
  argon2: ParametresArgon2 = ParametresArgon2()) -> None`
  Chaque source est un fichier ou un dossier (parcouru récursivement). Le `chemin` archivé est
  relatif au **parent** de la source (archiver `projet/` donne `projet/src/a.py`). Écrit dans
  un fichier temporaire à côté de la destination puis renomme (jamais d'archive à moitié
  écrite) ; refuse d'écraser une destination existante (`FileExistsError`). Ne charge pas tout
  le corpus en mémoire : au plus un bloc à la fois, plus une passe préalable de classement
  (lire chaque fichier pour le classer est acceptable).
- `class Archive` (gestionnaire de contexte) :
  `Archive.ouvrir(chemin: Path, mot_de_passe: str | None = None) -> Archive`,
  `.fichiers -> tuple[FichierArchive, ...]` (dataclass figée : `chemin, taille, mode,
  mtime_ns, sha256`), `.lire(chemin: str) -> bytes` (ne déchiffre que les blocs utiles et
  vérifie le SHA-256), `.extraire(destination: Path, chemins: Sequence[str] | None = None)
  -> None`, `.verifier() -> None` (relit tout : chaque bloc, chaque empreinte), `.fermer()`.
  Ouvrir une archive chiffrée sans mot de passe lève `MotDePasseRequis`.

## `src/saku/cli.py`
`main(argv: Sequence[str] | None = None) -> int` avec `argparse`, sous-commandes
`creer ARCHIVE SOURCE...` (`--chiffrer`, `--niveau`), `extraire ARCHIVE [-C DOSSIER] [CHEMIN...]`,
`lister ARCHIVE`, `verifier ARCHIVE`. Mot de passe : variable d'environnement
`SAKU_MOT_DE_PASSE` sinon `getpass` (avec confirmation à la création) ; **jamais** en argument
de ligne de commande. Les `ErreurSaku` donnent un message d'une ligne sur stderr et le code 1,
sans trace d'appel. Si une archive chiffrée est ouverte sans mot de passe connu, le demander.

# Points où l'on se trompe d'habitude (vérifie-les un par un avant de répondre)

1. Le numéro de bloc du nonce compte les blocs de données PUIS l'index ; le drapeau « dernier »
   ne vaut `01` que pour l'index.
2. L'AAD utilise les 12 premiers octets de l'en-tête de bloc : `taille_charge` doit donc être
   connue avant de chiffrer (taille compressée + 16).
3. `crc_charge` porte sur la charge finale sur disque (chiffrée si chiffré).
4. Repli en codec 0 si la compression ne gagne rien, y compris en mode chiffré.
5. Lecture : valider le pied, les positions et les tailles par rapport à la taille réelle du
   fichier AVANT toute allocation ; vérifier que les `position` de l'index désignent bien des
   blocs dont l'en-tête (type, codec, `taille_claire`) concorde avec l'index.
6. Chemins de l'index : appliquer tous les rejets de la section 5 à l'ouverture, pas seulement
   à l'extraction.
7. Extraction : fichier temporaire dans le dossier cible, SHA-256 vérifié, puis `os.replace` ;
   en cas d'erreur le temporaire est supprimé. Résoudre le dossier parent réel et vérifier
   qu'il reste sous la destination (lien symbolique piégé).
8. Fichier vide (taille 0), archive sans aucun fichier, fichier pile sur une frontière de
   bloc, fichier plus grand que plusieurs blocs : tous doivent marcher.
9. Un fichier modifié entre le classement et l'écriture doit lever une erreur claire, pas
   produire une archive incohérente.
10. `except Exception` nu interdit ; n'attraper que les exceptions attendues
    (`InvalidTag`, `zstd.ZstdError`, `struct.error`, `json.JSONDecodeError`, `UnicodeDecodeError`…).

# Format de ta réponse

Uniquement les fichiers, chacun précédé d'une ligne `=== FICHIER: chemin/relatif ===`,
contenu brut sans clôture Markdown, sans aucun texte avant, entre ou après. Pas de tests, pas
de README : ils sont écrits séparément.
