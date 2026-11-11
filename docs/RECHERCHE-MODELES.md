# Recherche : un codec neuronal accessible

État au 2026-11-11. Ce document rassemble ce qui a été lu, mesuré et décidé avant d'écrire le
codec neuronal. Les mesures viennent de cette machine ; les chiffres tirés de publications sont
signalés comme tels et ne sont pas comparables terme à terme (corpus et modèles différents).

## 1. Décisions prises

- **Un seul modèle, entraîné par le projet, livré avec Saku.** Aucun utilisateur n'entraîne
  quoi que ce soit. Le modèle est figé et versionné ; son empreinte SHA-256 va dans l'en-tête
  (`empreinte_modele`, déjà prévu par le format v0). Une version publiée n'est jamais retirée.
- **La carte graphique accélère, elle n'est jamais obligatoire.** Toute archive se relit sur
  processeur seul, avec les mêmes octets : l'inférence sera entièrement en entiers.
- **La taille du modèle est bornée par la lecture sur une machine ordinaire** : au moins
  1 Mo/s en extraction sur un processeur courant de 8 cœurs, ou le modèle est trop gros.
- **Le codec 3 reste le choix par défaut**, sans modèle et lisible partout.
- **Des niveaux de modèles**, chacun avec sa propre empreinte :

| Niveau | Modèle | Pour qui |
|---|---|---|
| 0 | aucun (codec 3) | tout le monde, par défaut |
| 1 | 5 à 50 M paramètres, en entiers | portables, processeur seul |
| 2 | 0,5 à 4 G paramètres | NPU ou carte de 8 Go, bêta-testeurs |
| 3 | 100 Go et plus | archivage froid, recherche |

## 2. Ce qui a été mesuré

### 2.1 Plafond d'un grand modèle

Probabilité de chaque jeton d'un texte réel sous Qwen3.8-27B (variante servie localement,
quantifiée en 4 bits, via `prompt_logprobs` de vLLM). C'est un **plafond** : calcul en
virgule flottante, taille du modèle non comptée.

| Extrait | xz -9 | zstd -19 | Saku codec 3 | Qwen3.8-27B |
|---|---:|---:|---:|---:|
| Code privé, 16 fichiers, 102 232 o | 2,216 | 2,243 | 1,879 | **0,406** |
| CPython (`importlib`, `Objects/*.c`), 103 933 o | 1,772 | — | 1,544 | **0,191** |

En bits par octet. Le 27B a traité chaque extrait en 15 s environ sur RTX 3090 (calcul de
tout le texte d'un coup, le sens le plus favorable), soit environ 7 Ko/s.

**Piège : la mémorisation.** CPython est dans les données d'entraînement de tous les grands
modèles ; le 0,19 bit/octet mesure en partie un par-cœur. Le banc des codecs neuronaux devra
utiliser du code que les modèles n'ont pas vu (privé, ou publié après leur date de coupure).

### 2.2 Petits modèles Qwen3.5 : préparés, pas encore mesurés

Les poids officiels de Qwen3.5 0,8B, 2B, 4B et 9B (Apache 2.0) sont téléchargés. Deux voies ont
été essayées :

- **Sur la carte graphique**, avec le vLLM de la machine : la carte est occupée par le modèle
  de production (22,3 Go sur 24) ; la mesure demande de l'arrêter, ce qui n'a pas été fait.
- **Sur processeur**, avec transformers : l'architecture DeltaNet n'y a pas de version
  optimisée ; le 0,8B n'avait pas fini 100 Ko au bout de vingt minutes. Mesure arrêtée.

La mesure est reportée ; elle se fera sur la carte graphique, avec la même méthode que le 27B.

### 2.3 Reproductibilité sur ARM64

Test sous émulation (QEMU 10.2, conteneur Debian ARM64, Python 3.14, gcc 14.2 ARM) :

| Étape | Résultat |
|---|---|
| Compilation des codecs 2 et 3 en C sur ARM64 | réussie |
| Relecture sur ARM64 d'archives créées sur x86 (zstd, codec 2, codec 3) | contenu identique |
| Création sur ARM64 des mêmes archives | **octets identiques à x86** (SHA-256 égaux) |
| Vecteurs de contrôle et identité C / Python sous ARM64 | en cours (lent en émulation) |

Échantillon : `json`, `email` et `asyncio` de CPython, 974 195 octets, blocs de 1 Mio.
L'émulation exécute de vraies instructions ARM64 : c'est un test de l'architecture, pas d'une
puce particulière.

### 2.4 ts_zip et cmix sur processeur

ts_zip (RWKV 169M) : 110 octets par seconde sur processeur, 1,322 bit/octet sur 20 000 octets
de code, contre 2,141 pour le codec 3 ([BENCHMARK.md](BENCHMARK.md)). cmix et ts_zip ne
finissent pas 1 Mo en 90 minutes.

## 3. Ce que fait l'état de l'art

**Famille Qwen** (sources secondaires sauf mention) :

- **Qwen3.5 petits modèles** (mars 2026) : 0,8B, 2B, 4B, 9B, denses, Apache 2.0. Fiche
  officielle du 0,8B vérifiée : 24 couches en 6 groupes de « 3 × Gated DeltaNet + 1 × attention
  complète », contexte 262 144, vocabulaire de 248 320 jetons, entraîné avec prédiction de
  plusieurs jetons.
- **Qwen3.6** (avril 2026) : 27B dense et 35B-A3B (mélange d'experts : 3 G paramètres actifs
  par jeton), Apache 2.0.
- **Qwen3.8** (août 2026) : 27B dense en Apache 2.0, Flash-Next en mélange d'experts, et un
  2,4T-A95B sous licence restrictive.

**Compression par modèle de langage** :

- **ts_zip** (Bellard) : RWKV 169M, poids 8 bits, calcul BF16 **déterministe quel que soit le
  matériel et le nombre de fils** ; jusqu'à 1 Mo/s sur RTX 4090 ; enwik8 1,106 bit/octet.
- **Nacrith** (arXiv 2602.19626, début 2026, non relu par des pairs) : SmolLM2-135M mélangé à
  un modèle n-grammes ; alice29 0,918 bit/octet contre 1,14 (ts_zip) et 1,63 (cmix). Deux idées
  à reprendre : **sauter le réseau quand le modèle statistique est sûr de lui**, et des
  **probabilités sur 2^24** (leur plus gros gain, −0,52 bit/octet sur enwik8). Reproductible
  seulement à carte, bibliothèque et pilote identiques : le piège à éviter.
- **LLMZip** (2023) : LLaMA-7B, 0,71 bit/caractère sur 1 Mo de text8.

**Calcul en entiers et poids ternaires** :

- **I-LLM** (arXiv 2405.17849) : inférence entièrement en entiers, softmax et normalisation
  comprises (décalages de bits), en 4 bits poids et activations, perte annoncée négligeable.
- **BitNet b1.58** (Microsoft) : poids dans {−1, 0, 1}, les produits deviennent des additions ;
  bitnet.cpp annonce 2,4 à 6,2 fois la vitesse de llama.cpp en 16 bits sur x86.

## 4. Ce qu'on en retient pour Saku

1. **L'architecture hybride à mémoire fixe** (Gated DeltaNet, comme RWKV) : le coût par jeton
   ne dépend pas de la longueur du fichier ; idéal pour des milliers de morceaux en parallèle
   sur carte graphique, ou quelques-uns sur processeur.
2. **Le réseau comme entrée du mélangeur du codec 3**, pas à sa place, et **sauté quand le
   codec 3 est sûr de lui** — décision déterministe, prise sur l'état du codec 3 seul.
3. **En entiers de bout en bout.** En compression, une approximation ne coûte que de la taille,
   jamais l'exactitude, tant qu'elle est déterministe : on peut simplifier hardiment.
4. **Un vocabulaire réduit.** Dans Qwen3.5-0,8B, la table de 248 320 jetons pèse environ
   250 M paramètres et se calcule à chaque jeton prédit ; un modèle spécialisé code peut
   descendre à 16 000-32 000 jetons.
5. **La distillation** : le grand modèle (27B, sur la carte de développement) sert de
   professeur à un petit élève ternaire, spécialisé code, entraîné sur du code sous licence
   libre. Les poids livrés devront venir de modèles officiels à licence vérifiée.

## 5. Ordres de grandeur du calcul

Un modèle de N paramètres coûte environ 2N opérations par jeton (≈ 4 octets de code). Un
modèle de 4 G paramètres : environ 2 G opérations par octet, soit 2 × 10^18 pour 1 Go. Ce sont
des estimations, pas des mesures : elles disent seulement que **les modèles de plusieurs
milliards de paramètres sont réservés à l'archivage froid**, et que le niveau « portable »
passe par des modèles de quelques dizaines de millions de paramètres au plus.

## Sources

- [Qwen3.5-0.8B, fiche officielle](https://huggingface.co/Qwen/Qwen3.5-0.8B)
- [Artificial Analysis : Qwen3.5 small models](https://artificialanalysis.ai/articles/qwen3-5-small-models)
- [InsiderLLM : Qwen models guide (mi-2026)](https://insiderllm.com/guides/qwen-models-guide/)
- [eWeek : Qwen3.8-27B sous Apache 2.0](https://www.eweek.com/news/alibaba-qwen3-8-27b-license-apac-china/)
- [ts_zip](https://bellard.org/ts_zip/)
- [Nacrith (arXiv 2602.19626)](https://arxiv.org/html/2602.19626v2)
- [LLMZip (arXiv 2306.04050)](https://arxiv.org/html/2306.04050)
- [I-LLM (arXiv 2405.17849)](https://arxiv.org/abs/2405.17849)
- [BitNet b1.58 2B4T](https://arxiv.org/pdf/2504.12285)
- [bitnet.cpp (Microsoft Research)](https://www.microsoft.com/en-us/research/?p=1100691)
