"""Codec 3 : implémentation de référence en Python pur (spécification : docs/CODEC-3.md)."""

from array import array

from .cm_reference import _Codeur, _Decodeur, _p12, _squash, _stretch

# ---------------------------------------------------------------------------
# Constantes (Section 1)
# ---------------------------------------------------------------------------

_LIM_BAS = 20
_LIM_HACH = 20
_LIM_CORR = 1023
_LOGB = 19
_NORDRES = [2, 3, 4, 6]  # k = 0..3
_NSEAUX = 1 << _LOGB  # 2^19
_NSEAU = 16

# DT[n] = 131072 / (2n + 3) pour n de 0 à 1023
_DT = array("I", [0] * 1024)
for _n in range(1024):
    _DT[_n] = 131072 // (2 * _n + 3)

# Ligne de départ d'un APM : squash((j - 16) * 128) * 16 pour j = 0..32
_LIGNE_APM = array("H", [_squash((j - 16) * 128) * 16 for j in range(33)])

# Valeur initiale d'un compteur : probabilité 1/2, n = 0
_INIT_COMPT = (1 << 21) << 10

# ---------------------------------------------------------------------------
# Compteur adaptatif avec limite variable
# ---------------------------------------------------------------------------


def _mettre_a_jour_compteur(s: int, y: int, lim: int) -> int:
    p22 = s >> 10
    n = s & 1023
    cible = 4194303 if y else 0
    if cible > p22:
        p22 = p22 + (((cible - p22) * _DT[n]) >> 16)
    else:
        p22 = p22 - (((p22 - cible) * _DT[n]) >> 16)
    if n < lim:
        n = n + 1
    return (p22 << 10) | n


# ---------------------------------------------------------------------------
# Hachage d'ordre (Section 3, k = 0..3)
# ---------------------------------------------------------------------------


def _hacher_ordre(k: int, buf: bytes, pos: int) -> int:
    N_k = _NORDRES[k]
    h = (N_k * 0x9E3779B1) & 0xFFFFFFFF
    for j in range(1, N_k + 1):
        b = buf[pos - j] if pos - j >= 0 else 0
        h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
    return h


# ---------------------------------------------------------------------------
# APM (Section 5)
# ---------------------------------------------------------------------------


def _apm(A: array, cx: int, pm: int) -> int:
    t = _stretch(pm) + 2048  # de 1 à 4095
    w = t & 127
    i = (t >> 7) + cx * 33
    # idx = i + (w >> 6)  (point le plus proche, pour la mise à jour)
    # renvoyer (A[i] * (128 - w) + A[i + 1] * w) >> 11
    return (A[i] * (128 - w) + A[i + 1] * w) >> 11


def _apm_idx(A: array, cx: int, pm: int) -> int:
    t = _stretch(pm) + 2048
    w = t & 127
    i = (t >> 7) + cx * 33
    return i + (w >> 6)


# ---------------------------------------------------------------------------
# Prédicteur (Sections 2, 3, 4, 5, 6)
# ---------------------------------------------------------------------------


class _Predicteur:
    def __init__(self):
        self.c0 = 1
        self.bp = 0
        self.buf = bytearray()
        self.pos = 0
        self.c4 = 0
        self.O0 = array("I", [_INIT_COMPT] * 256)
        self.O1 = array("I", [_INIT_COMPT] * 65536)
        # H[k] : 16 * 2^19 entiers 32 bits, initialisés à 0
        self.H = [array("I", bytes(4 * 16 * _NSEAUX)) for _ in range(5)]
        self.h = [0] * 5
        self.seau = [0] * 5
        self.mot = 0
        self.motp = 0
        self.MM = array("I", [_INIT_COMPT] * 64)
        self.MT = array("I", bytes(4 << 20))
        self.lg = 0
        self.ptr = 0
        # W[s][i], s = 0..1023, i = 0..8
        self.W = [[16384] * 9 for _ in range(1024)]
        # A1 : 256 * 33 entiers 16 bits
        # A2 : 65536 * 33 entiers 16 bits ; même ligne de départ pour chaque contexte
        self.A1 = array("H", _LIGNE_APM * 256)
        self.A2 = array("H", _LIGNE_APM * 65536)

        # Valeurs mémorisées pour mettre_a_jour
        self._x = [0] * 9
        self._pm = 0
        self._idx1 = 0
        self._idx2 = 0
        self._s = 0
        self._cpt = [0] * 8
        self._j = 0
        self._im = 0

        # Calcul initial des h et seaux
        self._recalculer_h()
        self._recalculer_seaux()

    def _trouver(self, T: array, x: int) -> int:
        x = (x * 0x9E3779B1) & 0xFFFFFFFF
        x = x ^ (x >> 15)
        x = (x * 0x2545F491) & 0xFFFFFFFF
        x = x ^ (x >> 13)
        i = x >> (32 - _LOGB)
        chk = (x & 0x00FFFFFF) | 0x01000000  # jamais 0
        a = i * 16
        b = (i ^ 1) * 16
        if T[a] == chk:
            return a
        if T[b] == chk:
            return b
        # r = b si (T[b][1] & 1023) < (T[a][1] & 1023), sinon a
        r = b if (T[b + 1] & 1023) < (T[a + 1] & 1023) else a
        T[r] = chk
        for k in range(1, 16):
            T[r + k] = _INIT_COMPT
        return r

    def _recalculer_seaux(self):
        n = 0 if self.bp == 0 else (self.c0 * 0x6F4F2A35) & 0xFFFFFFFF
        for k in range(5):
            self.seau[k] = self._trouver(self.H[k], (self.h[k] + n) & 0xFFFFFFFF)

    def _recalculer_h(self):
        for k in range(4):
            self.h[k] = _hacher_ordre(k, self.buf, self.pos)
        # k = 4 (mot)
        self.h[4] = (
            (((self.mot ^ 0x5BD1E995) * 0x01000193) & 0xFFFFFFFF)
            + ((self.motp * 0x2F0B3A49) & 0xFFFFFFFF)
        ) & 0xFFFFFFFF

    def _maj_correspondance(self, c: int):
        # Section 7.1 du codec 2
        if self.lg > 0 and self.buf[self.ptr] == c:
            self.lg = min(self.lg + 1, 65535)
            self.ptr = self.ptr + 1
        else:
            self.lg = 0
        if self.pos >= 6:
            g = 0
            for j in range(6, 0, -1):
                g = (g * 0x2F0B3A49 + self.buf[self.pos - j] + 1) & 0xFFFFFFFF
            e = (g * 0x9E3779B1) & 0xFFFFFFFF
            e = e >> 12
            if self.lg == 0 and self.MT[e] > 0:
                self.ptr = self.MT[e]
                self.lg = 0
                while (
                    self.lg < 32
                    and self.lg < self.ptr
                    and self.buf[self.ptr - 1 - self.lg] == self.buf[self.pos - 1 - self.lg]
                ):
                    self.lg = self.lg + 1
            self.MT[e] = self.pos

    @staticmethod
    def _est_alphanumerique(c: int) -> bool:
        """'0'-'9', 'a'-'z', 'A'-'Z', '_' ou tout octet >= 128 (docs/CODEC-3.md §6)."""
        return 48 <= c <= 57 or 97 <= c <= 122 or 65 <= c <= 90 or c == 95 or c >= 128

    def predire(self) -> int:
        # Section 5 : indice dans le seau
        q = self.bp if self.bp < 4 else self.bp - 4
        self._j = (self.c0 & ((1 << q) - 1)) | (1 << q)

        # Section 7.2 du codec 2 : im (peut remettre lg à 0)
        if self.lg > 0:
            attendu = self.buf[self.ptr]
            if ((attendu + 256) >> (8 - self.bp)) == self.c0:
                bit_att = (attendu >> (7 - self.bp)) & 1
                im = min(self.lg, 31) * 2 + bit_att
            else:
                self.lg = 0
                im = 0
        else:
            im = 0
        self._im = im

        # Section 5 : x[i]
        self._x[0] = _stretch(_p12(self.O0[self.c0]))
        self._x[1] = _stretch(_p12(self.O1[((self.c4 & 255) << 8) | self.c0]))
        for i in range(2, 7):
            self._x[i] = _stretch(_p12(self.H[i - 2][self.seau[i - 2] + self._j]))
        self._x[7] = _stretch(_p12(self.MM[im]))
        self._x[8] = 256

        # l
        if self.lg == 0:
            tranche = 0
        elif self.lg < 16:
            tranche = 1
        elif self.lg < 32:
            tranche = 2
        else:
            tranche = 3

        s = self.c0 + 256 * tranche
        self._s = s

        # pm
        point = 0
        for i in range(9):
            point += self.W[s][i] * self._x[i]
        d = point >> 16
        if d < -2047:
            d = -2047
        elif d > 2047:
            d = 2047
        self._pm = _squash(d)

        # p1, p2
        p1 = _apm(self.A1, self.c0, self._pm)
        self._idx1 = _apm_idx(self.A1, self.c0, self._pm)
        p2 = _apm(self.A2, self.c0 | ((self.c4 & 255) << 8), self._pm)
        self._idx2 = _apm_idx(self.A2, self.c0 | ((self.c4 & 255) << 8), self._pm)

        # p
        p = (self._pm + p1 + 2 * p2 + 2) >> 2
        if p < 1:
            p = 1
        elif p > 4095:
            p = 4095

        # Mémoriser les compteurs pour la mise à jour
        self._cpt[0] = self.O0[self.c0]
        self._cpt[1] = self.O1[((self.c4 & 255) << 8) | self.c0]
        for i in range(2, 7):
            self._cpt[i] = self.H[i - 2][self.seau[i - 2] + self._j]
        self._cpt[7] = self.MM[im]

        return p

    def mettre_a_jour(self, y: int) -> None:
        # Section 6
        pm = self._pm
        err = ((y << 12) - pm) * 6

        # Mettre à jour W
        for i in range(9):
            delta = (self._x[i] * err + 32768) >> 16
            w = self.W[self._s][i] + delta
            if w < -8388608:
                w = -8388608
            elif w > 8388607:
                w = 8388607
            self.W[self._s][i] = w

        # Mettre à jour les compteurs
        self.O0[self.c0] = _mettre_a_jour_compteur(self._cpt[0], y, _LIM_BAS)
        self.O1[((self.c4 & 255) << 8) | self.c0] = _mettre_a_jour_compteur(
            self._cpt[1], y, _LIM_BAS
        )
        for i in range(2, 7):
            self.H[i - 2][self.seau[i - 2] + self._j] = _mettre_a_jour_compteur(
                self._cpt[i], y, _LIM_HACH
            )
        self.MM[self._im] = _mettre_a_jour_compteur(self._cpt[7], y, _LIM_CORR)

        # Mettre à jour A1 et A2
        g = (y << 16) + (y << 7) - 2 * y
        self.A1[self._idx1] = self.A1[self._idx1] + ((g - self.A1[self._idx1]) >> 7)
        self.A2[self._idx2] = self.A2[self._idx2] + ((g - self.A2[self._idx2]) >> 7)

        self.c0 = (self.c0 << 1) | y
        self.bp = self.bp + 1
        if self.bp == 8:
            c = self.c0 & 255
            self.buf.append(c)
            self.pos = self.pos + 1
            self.c0 = 1
            self.bp = 0
            self.c4 = (self.c4 << 8 | c) & 0xFFFFFFFF
            if self._est_alphanumerique(c):
                self.mot = (self.mot ^ c) * 0x01000193 & 0xFFFFFFFF
            elif self.mot != 0:
                self.motp = self.mot
                self.mot = 0
            self._maj_correspondance(c)
            self._recalculer_h()
            self._recalculer_seaux()
        elif self.bp == 4:
            self._recalculer_seaux()


# ---------------------------------------------------------------------------
# Interface publique
# ---------------------------------------------------------------------------


def compresser(clair: bytes) -> bytes:
    pred = _Predicteur()
    codeur = _Codeur()
    for octet in clair:
        for bp in range(8):
            p = pred.predire()
            y = (octet >> (7 - bp)) & 1
            codeur.coder(y, p)
            pred.mettre_a_jour(y)
    return codeur.fin()


def decompresser(charge: bytes, taille_claire: int) -> bytes:
    if taille_claire < 0:
        raise ValueError("taille_claire < 0")
    pred = _Predicteur()
    decodeur = _Decodeur(charge)
    out = bytearray()
    for _ in range(taille_claire):
        octet = 0
        for _bp in range(8):
            p = pred.predire()
            y = decodeur.decoder(p)
            octet = (octet << 1) | y
            pred.mettre_a_jour(y)
        out.append(octet)
    return bytes(out)
