"""Ecriture et lecture d'une archive Saku v0 (voir docs/FORMAT-v0.md).

Principe de securite du lecteur : tout ce qui vient du fichier est hostile. Rien n'est alloue,
dechiffre ni ecrit avant d'avoir ete borne et verifie, et aucun contenu n'est rendu si son
empreinte SHA-256 ne concorde pas.
"""

from __future__ import annotations

import bisect
import contextlib
import hashlib
import itertools
import json
import logging
import os
import stat
import struct
import tempfile
import zlib
from collections import deque
from collections.abc import Iterable, Iterator, Sequence
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO

from .chiffrement import aad_entete, chiffrer_bloc, dechiffrer_bloc, deriver_cle
from .codecs import compresser, decompresser
from .erreurs import ArchiveInvalide, FichierAbsent, MotDePasseRequis, SourceInvalide
from .format import EnTete, EnTeteBloc, ParametresArgon2, pied_depuis_octets, pied_vers_octets
from .routage import DetecteurTexte, cle_de_flux

journal = logging.getLogger("saku")

TAILLE_ENTETE = 80
TAILLE_ENTETE_BLOC = 16
TAILLE_PIED = 16
TAILLE_ETIQUETTE = 16
TAILLE_INDEX_MAX = 1 << 30
TYPE_DONNEES = 1
TYPE_INDEX = 2
CODEC_STOCKE = 0
CODEC_ZSTD = 1
CODEC_CM1 = 2
CODEC_CM = 3
CODECS = {"zstd": CODEC_ZSTD, "cm": CODEC_CM, "cm1": CODEC_CM1}
_MORCEAU_LECTURE = 1 << 20
MEMOIRE_PAR_FIL = 256 << 20  # codec 3 : environ 230 Mio par bloc en cours


def _memoire_disponible() -> int | None:
    """Memoire disponible (MemAvailable sous Linux), ou None si inconnue."""
    try:
        with open("/proc/meminfo", encoding="ascii") as meminfo:
            for ligne in meminfo:
                if ligne.startswith("MemAvailable:"):
                    return int(ligne.split()[1]) * 1024
    except OSError, ValueError, IndexError:
        pass
    return None


def fils_par_defaut() -> int:
    """Blocs traites en meme temps : un par coeur, sans depasser la moitie de la memoire libre."""
    fils = os.cpu_count() or 1
    memoire = _memoire_disponible()
    if memoire is not None:
        fils = min(fils, memoire // 2 // MEMOIRE_PAR_FIL)
    return max(1, fils)


def _compresser_bloc(codec: int, clair: bytes, niveau: int) -> tuple[int, bytes]:
    """Compresse un bloc de données ; repli « stocké » si la compression ne gagne rien."""
    charge = compresser(codec, clair, niveau)
    if len(charge) >= len(clair):
        return CODEC_STOCKE, clair
    return codec, charge


_PREFIXE_TEMPORAIRE = ".saku-"


@dataclass(frozen=True)
class FichierArchive:
    """Un fichier tel que decrit par l'index de l'archive."""

    chemin: str
    taille: int
    mode: int
    mtime_ns: int
    sha256: str


# --------------------------------------------------------------------------- ecriture


@dataclass(frozen=True)
class _Source:
    """Un fichier a archiver, avec ce que la passe de classement en a mesure."""

    chemin_reel: Path
    description: FichierArchive
    texte: bool


def _analyser(chemin_reel: Path, chemin: str) -> _Source:
    """Mesure un fichier (taille, empreinte, texte ou non) sans le charger en memoire."""
    empreinte = hashlib.sha256()
    detecteur = DetecteurTexte()
    taille = 0
    with chemin_reel.open("rb") as flux:
        etat = os.fstat(flux.fileno())
        while morceau := flux.read(_MORCEAU_LECTURE):
            empreinte.update(morceau)
            detecteur.alimenter(morceau)
            taille += len(morceau)
    description = FichierArchive(
        chemin=chemin,
        taille=taille,
        mode=stat.S_IMODE(etat.st_mode) & 0o777,
        mtime_ns=etat.st_mtime_ns,
        sha256=empreinte.hexdigest(),
    )
    return _Source(chemin_reel, description, detecteur.conclure())


def _collecter(sources: Sequence[Path]) -> list[tuple[Path, str]]:
    """Liste les fichiers ordinaires a archiver : (chemin reel, chemin dans l'archive)."""
    trouves: list[tuple[Path, str]] = []
    for source in sources:
        racine = Path(os.path.abspath(source))
        if racine.is_symlink():
            journal.warning("lien symbolique ignoré : %s", racine)
        elif racine.is_file():
            trouves.append((racine, racine.name))
        elif racine.is_dir():
            for dossier, sous_dossiers, noms in os.walk(racine, followlinks=False):
                sous_dossiers.sort()
                for nom in sorted(noms):
                    reel = Path(dossier, nom)
                    if stat.S_ISREG(reel.lstat().st_mode):
                        trouves.append((reel, reel.relative_to(racine.parent).as_posix()))
                    else:
                        journal.warning("fichier non ordinaire ignoré : %s", reel)
        else:
            raise SourceInvalide(f"source introuvable ou non prise en charge : {source}")
    vus: set[str] = set()
    for _, chemin in trouves:
        try:
            chemin.encode("utf-8")
            _valider_chemin(chemin)
        except (UnicodeEncodeError, ArchiveInvalide) as erreur:
            raise SourceInvalide(f"nom de fichier non archivable : {chemin!r}") from erreur
        if chemin in vus:
            raise SourceInvalide(f"deux sources donnent le même chemin : {chemin}")
        vus.add(chemin)
    return trouves


class _Ecrivain:
    """Ecrit les blocs dans l'ordre et tient la liste destinee a l'index.

    Les blocs sont compresses en parallele (`fils` a la fois) mais ecrits dans l'ordre ou ils
    arrivent : l'archive est la meme au bit pres quel que soit le nombre de fils. Le codec C
    et zstd relachent le GIL pendant le calcul.
    """

    def __init__(
        self,
        sortie: BinaryIO,
        entete: bytes,
        cle: bytes | None,
        niveau: int,
        codec: int,
        executeur: ThreadPoolExecutor,
        fils: int,
    ) -> None:
        self._sortie = sortie
        self._entete = entete
        self._cle = cle
        self._niveau = niveau
        self._codec = codec
        self._executeur = executeur
        self._fils = fils
        self._en_cours: deque[tuple[int, Future[tuple[int, bytes]]]] = deque()
        self.blocs: list[dict[str, int]] = []
        sortie.write(entete)

    def ecrire_donnees(self, clair: bytes) -> None:
        """Confie un bloc de donnees a un fil ; ecrit les plus anciens quand la file est pleine."""
        travail = self._executeur.submit(_compresser_bloc, self._codec, clair, self._niveau)
        self._en_cours.append((len(clair), travail))
        while len(self._en_cours) > self._fils:
            self._ecrire_le_plus_ancien()

    def vider(self) -> None:
        """Ecrit tous les blocs encore en cours, dans l'ordre."""
        while self._en_cours:
            self._ecrire_le_plus_ancien()

    def _ecrire_le_plus_ancien(self) -> None:
        taille, travail = self._en_cours.popleft()
        id_codec, charge = travail.result()
        position = self._ecrire(TYPE_DONNEES, id_codec, taille, charge, len(self.blocs))
        self.blocs.append({"position": position, "taille_claire": taille, "id_codec": id_codec})

    def ecrire_index(self, clair: bytes) -> int:
        """Ecrit le bloc d'index (toujours en zstd) et rend sa position."""
        self.vider()
        if len(clair) > TAILLE_INDEX_MAX:
            raise SourceInvalide("trop de fichiers : l'index dépasse 1 Gio")
        charge = compresser(CODEC_ZSTD, clair, self._niveau)
        return self._ecrire(TYPE_INDEX, CODEC_ZSTD, len(clair), charge, 0)

    def _ecrire(self, type_bloc: int, id_codec: int, taille: int, charge: bytes, n: int) -> int:
        position = self._sortie.tell()
        if self._cle is not None:
            # taille_charge entre dans l'AAD : elle est fixee avant de chiffrer.
            provisoire = EnTeteBloc(type_bloc, id_codec, taille, len(charge) + TAILLE_ETIQUETTE, 0)
            aad = aad_entete(self._entete, provisoire.vers_octets())
            charge = chiffrer_bloc(self._cle, n, type_bloc == TYPE_INDEX, charge, aad)
        entete_bloc = EnTeteBloc(type_bloc, id_codec, taille, len(charge), zlib.crc32(charge))
        self._sortie.write(entete_bloc.vers_octets())
        self._sortie.write(charge)
        return position


def _remplir_blocs(ecrivain: _Ecrivain, groupe: Sequence[_Source], taille_bloc: int) -> None:
    """Verse un groupe de fichiers dans des blocs pleins, puis vide le reliquat."""
    tampon = bytearray()
    for source in groupe:
        empreinte = hashlib.sha256()
        with source.chemin_reel.open("rb") as flux:
            while morceau := flux.read(min(_MORCEAU_LECTURE, taille_bloc - len(tampon))):
                empreinte.update(morceau)
                tampon += morceau
                if len(tampon) == taille_bloc:
                    ecrivain.ecrire_donnees(bytes(tampon))
                    tampon.clear()
        # L'index porte l'empreinte de la passe de classement : si le fichier a bouge
        # entre-temps, l'archive serait incoherente. On s'arrete net.
        if empreinte.hexdigest() != source.description.sha256:
            raise SourceInvalide(f"fichier modifié pendant l'archivage : {source.chemin_reel}")
    if tampon:
        ecrivain.ecrire_donnees(bytes(tampon))


def creer_archive(
    destination: str | os.PathLike[str],
    sources: Sequence[str | os.PathLike[str]],
    *,
    mot_de_passe: str | None = None,
    taille_bloc: int = 8 * 1024 * 1024,
    niveau: int = 19,
    argon2: ParametresArgon2 | None = None,
    codec: str = "zstd",
    fils: int | None = None,
) -> None:
    """Cree l'archive `destination` a partir de fichiers ou de dossiers.

    Le chemin archive est relatif au parent de chaque source. L'archive est chiffree si
    `mot_de_passe` est fourni. Leve `FileExistsError` si la destination existe,
    `SourceInvalide` si une source ne peut pas etre archivee fidelement, `ValueError` si un
    parametre est hors des bornes du format.

    `codec` : "zstd" (rapide), "cm" (codec 3, plus compact, bien plus lent) ou "cm1"
    (codec 2, l'ancienne version du mélange de contextes, gardée pour comparaison).
    `fils` : blocs compressés en même temps (par défaut `fils_par_defaut()`) ; l'archive
    produite ne dépend pas de ce nombre.
    """
    destination = Path(destination)
    sources = [Path(source) for source in sources]
    if codec not in CODECS:
        raise ValueError(f"codec inconnu : {codec} (attendu : {', '.join(CODECS)})")
    fils = fils_par_defaut() if fils is None else fils
    if fils < 1:
        raise ValueError("fils doit valoir au moins 1")
    if destination.exists():
        raise FileExistsError(f"la destination existe déjà : {destination}")
    if mot_de_passe is not None and not mot_de_passe:
        raise MotDePasseRequis("mot de passe vide interdit")
    chiffree = mot_de_passe is not None
    parametres = (argon2 or ParametresArgon2()) if chiffree else ParametresArgon2(0, 0, 0)
    sel = os.urandom(16) if chiffree else bytes(16)
    entete = EnTete(
        version=0,
        chiffree=chiffree,
        id_aead=int(chiffree),
        id_kdf=int(chiffree),
        argon2_passes=parametres.passes,
        argon2_parallelisme=parametres.parallelisme,
        argon2_memoire_kio=parametres.memoire_kio,
        sel=sel,
        empreinte_modele=bytes(32),
        taille_bloc=taille_bloc,
    )
    try:
        # Relire ce qu'on s'apprete a ecrire applique les bornes du format aux parametres.
        entete_octets = entete.vers_octets()
        EnTete.depuis_octets(entete_octets)
    except (ArchiveInvalide, ValueError, OverflowError, struct.error) as erreur:
        raise ValueError(f"paramètres hors des bornes du format : {erreur}") from erreur
    cle = deriver_cle(mot_de_passe, sel, parametres) if mot_de_passe else None

    analysees = [_analyser(reel, chemin) for reel, chemin in _collecter(sources)]
    analysees.sort(key=lambda s: cle_de_flux(s.description.chemin, s.texte))

    with tempfile.NamedTemporaryFile(
        dir=destination.parent, prefix=_PREFIXE_TEMPORAIRE, delete=False
    ) as sortie:
        temporaire = Path(sortie.name)
        # Les fils ne demarrent qu'au premier bloc ; arretes dans le finally ci-dessous.
        executeur = ThreadPoolExecutor(fils, thread_name_prefix="saku")
        try:
            ecrivain = _Ecrivain(sortie, entete_octets, cle, niveau, CODECS[codec], executeur, fils)
            # Un bloc ne melange jamais textes et autres : un codec par groupe.
            for _, groupe in itertools.groupby(analysees, key=lambda s: s.texte):
                _remplir_blocs(ecrivain, list(groupe), taille_bloc)
            ecrivain.vider()  # positions definitives avant de construire l'index
            index = {
                "blocs": ecrivain.blocs,
                "fichiers": [vars(s.description) for s in analysees],
            }
            clair = json.dumps(index, ensure_ascii=False, separators=(",", ":")).encode()
            sortie.write(pied_vers_octets(ecrivain.ecrire_index(clair)))
            sortie.flush()
            os.fsync(sortie.fileno())
            _publier(temporaire, destination)
        finally:
            executeur.shutdown(cancel_futures=True)
            temporaire.unlink(missing_ok=True)


def _publier(temporaire: Path, destination: Path) -> None:
    """Met l'archive terminee a sa place sans jamais ecraser un fichier existant."""
    try:
        # link() echoue si la destination est apparue entre-temps.
        os.link(temporaire, destination)
    except FileExistsError:
        raise
    except OSError:
        # Systemes de fichiers sans liens physiques (exFAT, certains partages reseau).
        if destination.exists():
            raise FileExistsError(f"la destination existe déjà : {destination}") from None
        os.replace(temporaire, destination)


# ---------------------------------------------------------------------------- lecture


def _valider_chemin(chemin: object) -> str:
    """Applique les rejets de la section 5 a un chemin d'index."""
    if not isinstance(chemin, str) or not chemin:
        raise ArchiveInvalide("chemin d'index absent ou vide")
    if chemin.startswith("/") or "\x00" in chemin or "\\" in chemin:
        raise ArchiveInvalide(f"chemin d'index dangereux : {chemin!r}")
    if any(composant in ("", ".", "..") for composant in chemin.split("/")):
        raise ArchiveInvalide(f"chemin d'index dangereux : {chemin!r}")
    try:
        chemin.encode("utf-8")
    except UnicodeEncodeError as erreur:
        raise ArchiveInvalide("chemin d'index non UTF-8") from erreur
    return chemin


def _entier(valeur: object, nom: str, mini: int, maxi: int) -> int:
    """Exige un vrai entier JSON dans [mini, maxi] (un booleen n'en est pas un)."""
    if type(valeur) is not int or not mini <= valeur <= maxi:
        raise ArchiveInvalide(f"index : champ {nom} invalide")
    return valeur


def _champs(objet: object, attendus: set[str]) -> dict[str, object]:
    if not isinstance(objet, dict) or set(objet) != attendus:
        raise ArchiveInvalide("index : structure inattendue")
    return objet


def _lire_fichiers(brut: object) -> tuple[FichierArchive, ...]:
    """Valide la liste `fichiers` de l'index."""
    if not isinstance(brut, list):
        raise ArchiveInvalide("index : structure inattendue")
    fichiers: list[FichierArchive] = []
    for objet in brut:
        champs = _champs(objet, {"chemin", "taille", "mode", "mtime_ns", "sha256"})
        sha256 = champs["sha256"]
        if (
            not isinstance(sha256, str)
            or len(sha256) != 64
            or set(sha256) - set("0123456789abcdef")
        ):
            raise ArchiveInvalide("index : empreinte SHA-256 mal formée")
        fichiers.append(
            FichierArchive(
                chemin=_valider_chemin(champs["chemin"]),
                taille=_entier(champs["taille"], "taille", 0, 2**63 - 1),
                mode=_entier(champs["mode"], "mode", 0, 0o7777),
                mtime_ns=_entier(champs["mtime_ns"], "mtime_ns", -(2**63), 2**63 - 1),
                sha256=sha256,
            )
        )
    chemins = {f.chemin for f in fichiers}
    if len(chemins) != len(fichiers):
        raise ArchiveInvalide("index : chemin en double")
    for chemin in chemins:
        parent = chemin.rpartition("/")[0]
        while parent:
            if parent in chemins:
                raise ArchiveInvalide(f"index : {parent!r} est à la fois fichier et dossier")
            parent = parent.rpartition("/")[0]
    return tuple(fichiers)


@dataclass(frozen=True)
class _Bloc:
    """Un bloc de donnees dont l'en-tete sur disque a ete confronte a l'index."""

    position: int
    entete: EnTeteBloc
    octets_entete: bytes
    debut_flux: int


class Archive:
    """Archive ouverte en lecture. S'utilise avec `with Archive.ouvrir(...) as archive:`."""

    def __init__(self, flux: BinaryIO, mot_de_passe: str | None, fils: int | None = None) -> None:
        self._flux = flux
        self._cache: tuple[int, bytes] | None = None
        self._fils = fils_par_defaut() if fils is None else fils
        if self._fils < 1:
            raise ValueError("fils doit valoir au moins 1")
        self._executeur: ThreadPoolExecutor | None = None
        self._avance: dict[int, Future[bytes]] = {}
        self._plan: deque[int] = deque()
        taille = os.fstat(flux.fileno()).st_size
        if taille < TAILLE_ENTETE + TAILLE_ENTETE_BLOC + TAILLE_PIED:
            raise ArchiveInvalide("fichier trop court pour être une archive Saku")
        self._entete_octets = self._lire_a(0, TAILLE_ENTETE)
        self._entete = EnTete.depuis_octets(self._entete_octets)
        self._cle: bytes | None = None
        if self._entete.chiffree:
            if not mot_de_passe:
                raise MotDePasseRequis("cette archive est chiffrée : mot de passe requis")
            parametres = ParametresArgon2(
                self._entete.argon2_passes,
                self._entete.argon2_parallelisme,
                self._entete.argon2_memoire_kio,
            )
            self._cle = deriver_cle(mot_de_passe, self._entete.sel, parametres)

        position_index = pied_depuis_octets(self._lire_a(taille - TAILLE_PIED, TAILLE_PIED))
        if not TAILLE_ENTETE <= position_index <= taille - TAILLE_PIED - TAILLE_ENTETE_BLOC:
            raise ArchiveInvalide("position de l'index hors du fichier")
        octets_entete = self._lire_a(position_index, TAILLE_ENTETE_BLOC)
        entete_index = EnTeteBloc.depuis_octets(octets_entete)
        fin_attendue = position_index + TAILLE_ENTETE_BLOC + entete_index.taille_charge
        if (
            entete_index.type != TYPE_INDEX
            or entete_index.id_codec != CODEC_ZSTD
            or entete_index.taille_claire > TAILLE_INDEX_MAX
            or fin_attendue != taille - TAILLE_PIED
        ):
            raise ArchiveInvalide("bloc d'index incohérent")
        clair = self._dechiffrer_et_decompresser(position_index, entete_index, octets_entete, 0)
        try:
            index = _champs(json.loads(clair), {"blocs", "fichiers"})
        except (ValueError, RecursionError) as erreur:
            raise ArchiveInvalide("index illisible") from erreur
        self._fichiers = _lire_fichiers(index["fichiers"])
        self._blocs = self._lire_blocs(index["blocs"], position_index)

        self._debuts_blocs = [bloc.debut_flux for bloc in self._blocs]
        taille_flux = sum(bloc.entete.taille_claire for bloc in self._blocs)
        if sum(f.taille for f in self._fichiers) != taille_flux:
            raise ArchiveInvalide("index : tailles des fichiers et des blocs incohérentes")
        debuts = itertools.accumulate((f.taille for f in self._fichiers), initial=0)
        self._debuts_fichiers = dict(zip((f.chemin for f in self._fichiers), debuts, strict=False))
        self._par_chemin = {f.chemin: f for f in self._fichiers}

    @classmethod
    def ouvrir(
        cls,
        chemin: str | os.PathLike[str],
        mot_de_passe: str | None = None,
        *,
        fils: int | None = None,
    ) -> Archive:
        """Ouvre et valide l'archive : en-tete, pied, index, en-tete de chaque bloc.

        `fils` : blocs decompresses a l'avance en parallele pendant une lecture
        (par defaut `fils_par_defaut()`).

        Leve `ArchiveInvalide`, `EchecAuthentification` (mauvais mot de passe ou archive
        modifiee) ou `MotDePasseRequis`.
        """
        flux = Path(chemin).open("rb")  # noqa: SIM115 — fermé par Archive.fermer()
        try:
            return cls(flux, mot_de_passe, fils)
        except BaseException:
            flux.close()
            raise

    # ------------------------------------------------------------------ acces bas niveau

    def _lire_a(self, position: int, taille: int) -> bytes:
        # pread ne deplace pas de curseur partage : sur pour plusieurs fils a la fois.
        morceaux = []
        while taille > 0:
            donnees = os.pread(self._flux.fileno(), taille, position)
            if not donnees:
                raise ArchiveInvalide("archive tronquée")
            morceaux.append(donnees)
            position += len(donnees)
            taille -= len(donnees)
        return b"".join(morceaux)

    def _dechiffrer_et_decompresser(
        self, position: int, entete: EnTeteBloc, octets_entete: bytes, numero: int
    ) -> bytes:
        """Lit la charge d'un bloc dont les bornes ont deja ete validees, et rend son clair."""
        charge = self._lire_a(position + TAILLE_ENTETE_BLOC, entete.taille_charge)
        if zlib.crc32(charge) != entete.crc_charge:
            raise ArchiveInvalide("bloc corrompu (CRC)")
        if self._cle is not None:
            aad = aad_entete(self._entete_octets, octets_entete)
            charge = dechiffrer_bloc(self._cle, numero, entete.type == TYPE_INDEX, charge, aad)
        return decompresser(entete.id_codec, charge, entete.taille_claire)

    def _lire_blocs(self, brut: object, position_index: int) -> tuple[_Bloc, ...]:
        """Valide la liste `blocs` de l'index contre les en-tetes reellement sur disque."""
        if not isinstance(brut, list):
            raise ArchiveInvalide("index : structure inattendue")
        blocs: list[_Bloc] = []
        position_attendue = TAILLE_ENTETE
        debut_flux = 0
        for objet in brut:
            champs = _champs(objet, {"position", "taille_claire", "id_codec"})
            position = _entier(champs["position"], "position", TAILLE_ENTETE, position_index)
            taille = _entier(champs["taille_claire"], "taille_claire", 1, self._entete.taille_bloc)
            id_codec = _entier(champs["id_codec"], "id_codec", 0, 255)
            if position != position_attendue or position + TAILLE_ENTETE_BLOC > position_index:
                raise ArchiveInvalide("index : blocs non contigus")
            octets_entete = self._lire_a(position, TAILLE_ENTETE_BLOC)
            entete = EnTeteBloc.depuis_octets(octets_entete)
            if (entete.type, entete.id_codec, entete.taille_claire) != (
                TYPE_DONNEES,
                id_codec,
                taille,
            ):
                raise ArchiveInvalide("bloc en désaccord avec l'index")
            blocs.append(_Bloc(position, entete, octets_entete, debut_flux))
            position_attendue = position + TAILLE_ENTETE_BLOC + entete.taille_charge
            debut_flux += taille
        if position_attendue != position_index:
            raise ArchiveInvalide("index : blocs non contigus")
        return tuple(blocs)

    def _ouvrir_bloc(self, numero: int) -> bytes:
        bloc = self._blocs[numero]
        return self._dechiffrer_et_decompresser(
            bloc.position, bloc.entete, bloc.octets_entete, numero
        )

    def _clair_du_bloc(self, numero: int) -> bytes:
        """Rend le clair d'un bloc de donnees ; garde le dernier lu, et lui seul, en memoire.

        Un bloc prepare a l'avance (voir `_planifier`) est pris tel quel ; son erreur
        eventuelle (CRC, authentification, decompression) remonte ici, a son tour.
        """
        if self._cache is None or self._cache[0] != numero:
            travail = self._avance.pop(numero, None)
            clair = travail.result() if travail is not None else self._ouvrir_bloc(numero)
            self._cache = (numero, clair)
            self._alimenter()
        return self._cache[1]

    def _planifier(self, fichiers: Iterable[FichierArchive]) -> None:
        """Annonce les blocs qui vont etre lus, dans l'ordre, pour les preparer en parallele."""
        if self._fils <= 1:
            return
        numeros: dict[int, None] = {}
        for fichier in fichiers:
            if fichier.taille == 0:
                continue
            debut = self._debuts_fichiers[fichier.chemin]
            premier = bisect.bisect_right(self._debuts_blocs, debut) - 1
            dernier = bisect.bisect_right(self._debuts_blocs, debut + fichier.taille - 1) - 1
            numeros.update(dict.fromkeys(range(premier, dernier + 1)))
        for numero in [n for n in self._avance if n not in numeros]:
            self._avance.pop(numero).cancel()
        self._plan = deque(n for n in numeros if n not in self._avance)
        self._alimenter()

    def _alimenter(self) -> None:
        while self._plan and len(self._avance) < self._fils:
            numero = self._plan.popleft()
            if self._cache is not None and self._cache[0] == numero:
                continue
            if self._executeur is None:
                self._executeur = ThreadPoolExecutor(self._fils, thread_name_prefix="saku")
            self._avance[numero] = self._executeur.submit(self._ouvrir_bloc, numero)

    def _morceaux(self, fichier: FichierArchive) -> Iterator[bytes]:
        """Rend le contenu d'un fichier bloc par bloc, sans jamais le rendre non verifie.

        L'empreinte est controlee a la fin : l'appelant ne doit rien tenir pour valide tant
        que l'iteration n'est pas allee au bout sans erreur.
        """
        empreinte = hashlib.sha256()
        position = self._debuts_fichiers[fichier.chemin]
        fin = position + fichier.taille
        numero = bisect.bisect_right(self._debuts_blocs, position) - 1
        while position < fin:
            clair = self._clair_du_bloc(numero)
            debut = position - self._blocs[numero].debut_flux
            morceau = clair[debut : debut + fin - position]
            empreinte.update(morceau)
            yield morceau
            position += len(morceau)
            numero += 1
        if empreinte.hexdigest() != fichier.sha256:
            raise ArchiveInvalide(f"empreinte SHA-256 fausse pour {fichier.chemin!r}")

    def _trouver(self, chemin: str) -> FichierArchive:
        try:
            return self._par_chemin[chemin]
        except KeyError:
            raise FichierAbsent(f"absent de l'archive : {chemin!r}") from None

    # ------------------------------------------------------------------------ API publique

    @property
    def fichiers(self) -> tuple[FichierArchive, ...]:
        """Les fichiers de l'archive, dans l'ordre du flux logique."""
        return self._fichiers

    def lire(self, chemin: str) -> bytes:
        """Rend le contenu d'un fichier, empreinte verifiee ; ne lit que les blocs utiles."""
        fichier = self._trouver(chemin)
        self._planifier([fichier])
        return b"".join(self._morceaux(fichier))

    def verifier(self) -> None:
        """Relit tout : chaque bloc (CRC, authentification, decompression), chaque empreinte."""
        self._planifier(self._fichiers)
        for fichier in self._fichiers:
            for _ in self._morceaux(fichier):
                pass

    def extraire(
        self, destination: str | os.PathLike[str], chemins: Sequence[str] | None = None
    ) -> None:
        """Extrait tout, ou les seuls `chemins` demandes, sous `destination`.

        Un fichier n'apparait a sa place qu'une fois son empreinte verifiee. Refuse de
        traverser un lien symbolique existant dans la destination.
        """
        voulus = None if chemins is None else {self._trouver(c).chemin for c in chemins}
        destination = Path(destination)
        destination.mkdir(parents=True, exist_ok=True)
        racine = destination.resolve(strict=True)
        a_extraire = [f for f in self._fichiers if voulus is None or f.chemin in voulus]
        self._planifier(a_extraire)
        for fichier in a_extraire:
            self._extraire_un(racine, fichier)

    def _extraire_un(self, racine: Path, fichier: FichierArchive) -> None:
        *dossiers, nom = fichier.chemin.split("/")
        parent = racine
        for composant in dossiers:
            parent = parent / composant
            if parent.is_symlink():
                raise ArchiveInvalide(f"lien symbolique sur le chemin d'extraction : {parent}")
            parent.mkdir(exist_ok=True)
        if not parent.resolve(strict=True).is_relative_to(racine):
            raise ArchiveInvalide(f"extraction hors de la destination : {fichier.chemin!r}")
        descripteur, nom_temporaire = tempfile.mkstemp(dir=parent, prefix=_PREFIXE_TEMPORAIRE)
        temporaire = Path(nom_temporaire)
        try:
            with os.fdopen(descripteur, "wb") as sortie:
                for morceau in self._morceaux(fichier):
                    sortie.write(morceau)
                os.fchmod(sortie.fileno(), fichier.mode & 0o777)
            os.utime(temporaire, ns=(fichier.mtime_ns, fichier.mtime_ns))
            os.replace(temporaire, parent / nom)
        finally:
            with contextlib.suppress(FileNotFoundError):
                temporaire.unlink()

    def fermer(self) -> None:
        """Ferme le fichier d'archive et arrete les fils de lecture anticipee."""
        self._cache = None
        self._plan.clear()
        self._avance.clear()
        if self._executeur is not None:
            self._executeur.shutdown(wait=True, cancel_futures=True)
            self._executeur = None
        self._flux.close()

    def __enter__(self) -> Archive:
        return self

    def __exit__(self, *_: object) -> None:
        self.fermer()
