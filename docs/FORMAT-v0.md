# Format d'archive Saku — version 0

Statut : **expérimental**. Une archive v0 n'a aucune garantie de lecture par les versions
futures. Tous les entiers sont **little-endian**, non signés. `‖` = concaténation.

## 1. Vue d'ensemble

```
[En-tête 80 o] [Bloc de données]* [Bloc d'index] [Pied 16 o]
```

Les fichiers archivés sont concaténés dans un **flux logique** unique (archive « solide » :
indispensable sur du code, fait de milliers de petits fichiers). Le flux est découpé en blocs
indépendants, chacun **compressé puis chiffré**. L'index dit où commence chaque fichier dans le
flux : pour extraire un fichier, on ne lit que les blocs qui le couvrent (accès aléatoire).

## 2. En-tête (80 octets)

| Décalage | Taille | Champ | Valeur |
| --- | --- | --- | --- |
| 0 | 6 | `magic` | `53 41 4B 55 00 00` (`SAKU\0\0`) |
| 6 | 1 | `version` | `0` |
| 7 | 1 | `drapeaux` | bit 0 = archive chiffrée ; tout autre bit à 1 → rejet |
| 8 | 1 | `id_aead` | `0` aucun, `1` AES-256-GCM |
| 9 | 1 | `id_kdf` | `0` aucun, `1` Argon2id |
| 10 | 1 | `argon2_passes` | 1 à 16 si chiffré, sinon 0 |
| 11 | 1 | `argon2_parallelisme` | 1 à 16 si chiffré, sinon 0 |
| 12 | 4 | `argon2_memoire_kio` | 8 192 à 4 194 304 si chiffré, sinon 0 |
| 16 | 16 | `sel` | aléatoire (`os.urandom`) si chiffré, sinon zéros |
| 32 | 32 | `empreinte_modele` | SHA-256 du modèle neuronal exigé ; zéros si aucun |
| 64 | 4 | `taille_bloc` | octets en clair max par bloc, 4 096 à 268 435 456 |
| 68 | 8 | réservé | zéros (sinon rejet) |
| 76 | 4 | `crc_entete` | CRC-32 (zlib) des octets 0 à 75 |

Cohérence exigée : `drapeaux` bit 0 = 1 ⇔ `id_aead` = 1 ⇔ `id_kdf` = 1.
Valeurs par défaut à l'écriture : `taille_bloc` = 8 Mio ; Argon2id 3 passes, 4 voies, 262 144 Kio.

## 3. Bloc

En-tête de bloc (16 octets) suivi de la charge :

| Décalage | Taille | Champ | Valeur |
| --- | --- | --- | --- |
| 0 | 1 | `type` | `1` données, `2` index |
| 1 | 1 | `id_codec` | `0` stocké, `1` zstd, `2` mélange de contextes en entiers v1 ([CODEC-2.md](CODEC-2.md)) |
| 2 | 2 | réservé | zéros |
| 4 | 4 | `taille_claire` | taille après déchiffrement et décompression, ≤ `taille_bloc` pour les données |
| 8 | 4 | `taille_charge` | taille de la charge sur disque (étiquette AEAD de 16 o incluse si chiffré) |
| 12 | 4 | `crc_charge` | CRC-32 de la charge telle qu'écrite sur disque |

Construction de la charge : `clair → compression(id_codec) → chiffrement (si archive chiffrée)`.
Si la compression ne gagne rien (`taille compressée ≥ taille claire`), le bloc est écrit en
codec `0` (stocké). Un bloc de données a une `taille_claire` ≥ 1. Le bloc d'index est toujours
le dernier bloc, en codec `1`, et sa `taille_claire` est plafonnée à 1 Gio.

## 4. Chiffrement

- Clé (32 o) = Argon2id(mot de passe UTF-8, `sel`, paramètres de l'en-tête). Mot de passe vide interdit.
- Le sel est tiré au hasard à chaque archive : une clé ne sert donc qu'à une archive, ce qui
  rend sûr un nonce à compteur (construction STREAM, comme `age`).
- Nonce (12 o) = `numéro` sur 8 o little-endian ‖ `00 00 00` ‖ `rôle`. Blocs de données :
  numérotés à partir de 0 dans l'ordre du fichier, rôle `00`. Bloc d'index : numéro 0, rôle `01`
  (le lecteur peut ainsi le déchiffrer en premier, sans connaître le nombre de blocs).
- Données associées (AAD) = SHA-256(en-tête de 80 o) ‖ les 12 premiers octets de l'en-tête de bloc.
- Conséquences : modifier l'en-tête, réordonner, dupliquer ou retyper un bloc fait échouer
  l'authentification ; l'index authentifié fixe la liste exacte des blocs (ni ajout ni retrait). Aucun octet déchiffré n'est rendu avant vérification de l'étiquette.

Archive non chiffrée : pas de confidentialité ni d'authenticité, seulement la détection
d'erreurs (CRC-32 par bloc, SHA-256 par fichier).

## 5. Index

Clair du bloc d'index = JSON UTF-8 :

```json
{
  "blocs": [{"position": 80, "taille_claire": 8388608, "id_codec": 1}],
  "fichiers": [{"chemin": "src/a.py", "taille": 1234, "mode": 420,
                "mtime_ns": 1790000000000000000, "sha256": "…64 hex…"}]
}
```

- `blocs` : blocs de données dans l'ordre du fichier ; `position` = décalage de l'en-tête de bloc.
  Les blocs sont **contigus** : le premier est en 80, chacun commence où finit le précédent, et
  le dernier finit à `position_index`. Le bloc d'index finit exactement là où commence le pied.
- `fichiers` : dans l'ordre du flux logique. Le fichier n° `k` occupe
  `[somme des tailles précédentes, + taille)`. La somme des `taille` doit égaler la somme des
  `taille_claire` des blocs.
- `chemin` : relatif, séparateur `/`, UTF-8 valide. **Rejet** à la lecture si : absolu, vide,
  composant `.` ou `..` ou vide, octet nul, antislash, doublon, ou chemin qui est aussi le
  dossier d'un autre fichier (`a` et `a/b`).
- `mode` : seuls les bits `0o777` sont appliqués à l'extraction.
- v0 n'archive que les fichiers ordinaires (liens symboliques et fichiers spéciaux ignorés
  avec avertissement ; dossiers vides non conservés).

## 6. Pied (16 octets)

| Décalage | Taille | Champ |
| --- | --- | --- |
| 0 | 8 | `position_index` : décalage de l'en-tête du bloc d'index |
| 8 | 4 | `magic_fin` : `55 4B 41 53` (`UKAS`) |
| 12 | 4 | CRC-32 des 12 octets précédents |

## 7. Routage (à l'écriture)

1. Chaque fichier est classé `texte` (UTF-8 valide et sans octet nul, fichier vide compris) ou `autre`.
2. Ordre du flux : tous les `texte` puis tous les `autre` ; dans chaque groupe, tri par
   (extension en minuscules, chemin). Les fichiers semblables se suivent, la compression en profite.
3. Un bloc ne mélange jamais les deux groupes (coupure forcée au changement de groupe).
4. Codec : zstd niveau 19 par défaut, ou codec 2 sur demande (`--codec cm`), pour tous les
   blocs. Un bloc que le codec ne réduit pas est stocké (`id_codec` 0). Un futur codec neuronal
   à modèle pré-entraîné prendra un nouvel identifiant ; le format n'aura pas à changer.

## 8. Obligations du lecteur

- Vérifier tous les CRC, la cohérence de l'en-tête, les bornes (aucune taille au-delà des
  plafonds, aucune position hors du fichier), puis les étiquettes AEAD.
- Décompresser avec une limite de sortie égale à `taille_claire` (anti-bombe) et rejeter si la
  taille obtenue diffère.
- À l'extraction : vérifier le SHA-256 de chaque fichier **avant** de le mettre à sa place
  définitive (écriture dans un fichier temporaire du même dossier puis renommage) ; refuser
  d'écrire hors du dossier de destination, y compris à travers un lien symbolique existant.
- Toute anomalie lève une erreur explicite ; jamais de sortie partielle présentée comme valide.

## 9. Ce que v0 ne fait pas (assumé)

- **Pas de correction d'erreurs** : la corruption est détectée, pas réparée (Reed-Solomon prévu en v1).
- Pas de clé de fichier enveloppée (changer le mot de passe = recréer l'archive), pas de destinataires multiples.
- Les tailles des blocs et le nombre de blocs restent visibles sur une archive chiffrée ; les noms
  et tailles de fichiers, eux, sont chiffrés (ils sont dans l'index).
- Pas d'ajout ni de suppression dans une archive existante.
