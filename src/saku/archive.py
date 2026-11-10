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
from collections.abc import Iterator, Sequence
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
CODEC_CM = 2
CODECS = {"zstd": CODEC_ZSTD, "cm": CODEC_CM}
_MORCEAU_LECTURE = 1 << 20
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
    """Ecrit les blocs l'un apres l'autre et tient la liste destinee a l'index."""

    def __init__(
        self, sortie: BinaryIO, entete: bytes, cle: bytes | None, niveau: int, codec: int
    ) -> None:
        self._sortie = sortie
        self._entete = entete
        self._cle = cle
        self._niveau = niveau
        self._codec = codec
        self.blocs: list[dict[str, int]] = []
        sortie.write(entete)

    def ecrire_donnees(self, clair: bytes) -> None:
        """Ecrit un bloc de donnees, en repli « stocke » si la compression ne gagne rien."""
        charge = compresser(self._codec, clair, self._niveau)
        id_codec = self._codec
        if len(charge) >= len(clair):
            charge, id_codec = clair, CODEC_STOCKE
        position = self._ecrire(TYPE_DONNEES, id_codec, len(clair), charge, len(self.blocs))
        self.blocs.append({"position": position, "taille_claire": len(clair), "id_codec": id_codec})

    def ecrire_index(self, clair: bytes) -> int:
        """Ecrit le bloc d'index (toujours en zstd) et rend sa position."""
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
) -> None:
    """Cree l'archive `destination` a partir de fichiers ou de dossiers.

    Le chemin archive est relatif au parent de chaque source. L'archive est chiffree si
    `mot_de_passe` est fourni. Leve `FileExistsError` si la destination existe,
    `SourceInvalide` si une source ne peut pas etre archivee fidelement, `ValueError` si un
    parametre est hors des bornes du format.

    `codec` : "zstd" (rapide) ou "cm" (codec 2, plus compact, bien plus lent).
    """
    destination = Path(destination)
    sources = [Path(source) for source in sources]
    if codec not in CODECS:
        raise ValueError(f"codec inconnu : {codec} (attendu : {', '.join(CODECS)})")
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
        try:
            ecrivain = _Ecrivain(sortie, entete_octets, cle, niveau, CODECS[codec])
            # Un bloc ne melange jamais textes et autres : un codec par groupe.
            for _, groupe in itertools.groupby(analysees, key=lambda s: s.texte):
                _remplir_blocs(ecrivain, list(groupe), taille_bloc)
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

    def __init__(self, flux: BinaryIO, mot_de_passe: str | None) -> None:
        self._flux = flux
        self._cache: tuple[int, bytes] | None = None
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
    def ouvrir(cls, chemin: str | os.PathLike[str], mot_de_passe: str | None = None) -> Archive:
        """Ouvre et valide l'archive : en-tete, pied, index, en-tete de chaque bloc.

        Leve `ArchiveInvalide`, `EchecAuthentification` (mauvais mot de passe ou archive
        modifiee) ou `MotDePasseRequis`.
        """
        flux = Path(chemin).open("rb")  # noqa: SIM115 — fermé par Archive.fermer()
        try:
            return cls(flux, mot_de_passe)
        except BaseException:
            flux.close()
            raise

    # ------------------------------------------------------------------ acces bas niveau

    def _lire_a(self, position: int, taille: int) -> bytes:
        self._flux.seek(position)
        donnees = self._flux.read(taille)
        if len(donnees) != taille:
            raise ArchiveInvalide("archive tronquée")
        return donnees

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

    def _clair_du_bloc(self, numero: int) -> bytes:
        """Rend le clair d'un bloc de donnees ; garde le dernier lu, et lui seul, en memoire."""
        if self._cache is None or self._cache[0] != numero:
            bloc = self._blocs[numero]
            clair = self._dechiffrer_et_decompresser(
                bloc.position, bloc.entete, bloc.octets_entete, numero
            )
            self._cache = (numero, clair)
        return self._cache[1]

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
        return b"".join(self._morceaux(self._trouver(chemin)))

    def verifier(self) -> None:
        """Relit tout : chaque bloc (CRC, authentification, decompression), chaque empreinte."""
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
        for fichier in self._fichiers:
            if voulus is None or fichier.chemin in voulus:
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
        """Ferme le fichier d'archive."""
        self._cache = None
        self._flux.close()

    def __enter__(self) -> Archive:
        return self

    def __exit__(self, *_: object) -> None:
        self.fermer()
