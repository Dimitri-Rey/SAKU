# Ce qui pourrait invalider l'approche

Liste tenue à jour de ce qui peut faire échouer Saku, avec pour chaque risque le test qui
tranche. Un risque sans test n'est qu'une inquiétude ; un test raté doit faire changer de plan,
pas de discours.

Les chiffres cités viennent de [BENCHMARK.md](BENCHMARK.md).

## 1. Le codec neuronal n'est pas reproductible

**Risque.** Un codeur arithmétique exige que le décodeur recalcule exactement les mêmes
probabilités que l'encodeur. En virgule flottante, le résultat dépend du processeur, de la
bibliothèque de calcul, du nombre de fils et de l'ordre des additions. Un seul bit d'écart et
tout le reste du bloc est perdu.

**Test.** La même archive, créée sur une machine, est décodée à l'identique sur au moins trois
environnements différents (x86-64 avec et sans AVX-512, ARM64), avec 1 fil et avec N fils.

**Seuil d'abandon.** Si l'inférence en arithmétique entière coûte plus de la moitié du gain de
compression obtenu en flottant, ou si elle est plus de dix fois plus lente, le codec 2 tel
qu'il est prévu ne tient pas.

## 2. Le gain ne paie pas le modèle

**Risque.** La règle du projet compte la taille du décodeur, modèle compris. Un modèle de
170 Mo ne se rembourse que sur des archives bien plus grosses que lui, ou s'il est partagé par
beaucoup d'archives — et dans ce cas il devient une dépendance que tout lecteur doit posséder.

**Test.** Pour chaque modèle candidat, calculer le volume à partir duquel
`archive + modèle` passe sous `xz -9`. La colonne « ratio modèle compris » du banc donne la
réponse pour ts_zip.

**Seuil d'abandon.** Si ce volume dépasse ce qu'un utilisateur archive réellement (quelques
gigaoctets de code et de texte), il faut un modèle beaucoup plus petit, ou renoncer.

## 3. Trop lent pour un archiveur

**Risque.** Les compresseurs neuronaux travaillent en kilooctets par seconde sur processeur.
cmix aussi. Un outil qui met une nuit pour un dépôt de code ne sera pas utilisé, quel que soit
son ratio.

**Test.** Débit de compression et de décompression mesuré sur processeur seul, sans carte
graphique.

**Seuil d'abandon.** À fixer avec le premier prototype ; en dessous de 1 Mo/s en
décompression sur un processeur courant, Saku ne peut pas servir d'archiveur du quotidien et
doit se présenter comme un outil d'archivage froid.

## 4. Les blocs indépendants mangent le gain

**Risque.** L'accès aléatoire impose de repartir de zéro à chaque bloc. Un modèle qui apprend
au fil du texte perd son contexte toutes les 8 Mio. Le même effet se voit déjà avec zstd :
Saku v0 compresse moins bien qu'un zstd à grande fenêtre sur un gros corpus.

**Test.** Mesurer le ratio en fonction de la taille de bloc (1, 8, 64 Mio, bloc unique).

**Seuil d'abandon.** Aucun : c'est un compromis à régler, pas un mur. Mais si le codec
neuronal n'est intéressant qu'en bloc unique, l'accès aléatoire devient une option et non le
comportement par défaut.

## 5. Sans le codec neuronal, Saku n'a pas de raison d'être

**Risque.** Aujourd'hui Saku fait ce que font déjà `tar | zstd | age`, 7-Zip, restic ou borg,
en moins bien rodé. La seule nouveauté prévue est le codec 2.

**Test.** Sur les corpus de code, le codec 2 doit battre `xz -9` et `zstd -22 --long`, modèle
compris, à un débit acceptable.

**Seuil d'abandon.** Si ce n'est pas le cas, le projet s'arrête ou change d'objet. Le
conteneur seul ne justifie pas un nouveau format.

## 6. Un modèle fait partie du format, pour toujours

**Risque.** Une archive neuronale est illisible sans le modèle exact qui l'a produite. Il faut
pouvoir le redistribuer dans vingt ans : licence des poids, licence des données
d'entraînement, hébergement.

**Test.** Chaque modèle admis a une licence qui autorise la redistribution, une empreinte
SHA-256 inscrite dans l'en-tête des archives, et une copie archivée hors du dépôt.

**Seuil d'abandon.** Pas de modèle dont la licence ou l'origine des données est floue.

## 7. La sécurité

- **Les tailles fuient.** Compresser puis chiffrer laisse voir la taille compressée de chaque
  bloc. Si un attaquant peut glisser du contenu à côté d'un secret et observer la taille, il
  peut deviner le secret (attaques de type CRIME). Saku est un archiveur de fichiers au repos ;
  il ne doit pas servir à chiffrer des flux où l'adversaire choisit une partie du contenu.
- **Le mot de passe est le maillon faible.** Argon2id ralentit l'attaquant, il ne sauve pas un
  mot de passe court.
- **Python ne permet ni d'effacer une clé de la mémoire ni de garantir un temps constant** en
  dehors de la bibliothèque de chiffrement.
- **Le décodeur neuronal sera une grosse surface d'attaque.** Il devra traiter le flux
  compressé comme hostile, avec des bornes sur tout.

**Test.** Lot d'archives hostiles dans `tests/test_archive_hostile.py`, à compléter par du
fuzzing ; relecture extérieure avant toute version annoncée comme stable.

## 8. Reconstruire à l'identique un conteneur déjà compressé

**Risque.** Déballer un `.docx`, un `.zip` ou un JPEG pour mieux le recompresser exige de
refabriquer ensuite le flux d'origine au bit près. Pour deflate, il faut retrouver les
réglages exacts de l'encodeur, ou stocker les différences. Sur des fichiers produits par des
outils variés, le taux d'échec peut être élevé.

**Test.** Sur un corpus de vrais documents, proportion de fichiers reconstruits à l'identique
et gain net par rapport au fichier laissé tel quel.

**Seuil d'abandon.** Tout fichier qui ne se reconstruit pas exactement est stocké tel quel ;
si c'est la majorité, la fonction ne vaut pas sa complexité.

## 9. Le mode avec perte brouille le message

**Risque.** Un archiveur qui peut, dans certains cas, rendre autre chose que ce qu'on lui a
confié perd la confiance de ses utilisateurs, même si le mode est facultatif.

**Test.** Le mode avec perte n'existe pas tant que le mode sans perte n'a pas fait ses
preuves. Quand il existera : jamais activé par défaut, jamais sur du texte ou des chiffres,
et l'archive dit clairement quels fichiers ne sont pas restitués à l'identique.

## 10. Le prototype en Python limite l'adoption

**Risque.** Python 3.14 est une dépendance lourde pour un outil d'archivage, et un format n'a
de valeur que si plusieurs lecteurs indépendants existent.

**Test.** La spécification doit suffire à écrire un second lecteur sans lire le code Python.

**Suite prévue.** Une implémentation en Rust ou en C une fois le format stabilisé.
