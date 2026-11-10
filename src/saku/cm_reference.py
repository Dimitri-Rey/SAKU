"""Codec 2 : implémentation de référence en Python pur (spécification : docs/CODEC-2.md)."""

from array import array

# ---------------------------------------------------------------------------
# Tables fixes (Section 3)
# ---------------------------------------------------------------------------

# 3.1 squash
_T = [
    1,
    2,
    4,
    6,
    10,
    17,
    27,
    45,
    74,
    120,
    194,
    311,
    488,
    747,
    1102,
    1546,
    2048,
    2550,
    2994,
    3349,
    3608,
    3785,
    3902,
    3976,
    4022,
    4051,
    4069,
    4079,
    4086,
    4090,
    4092,
    4094,
    4095,
]


def _squash(d: int) -> int:
    # clamp(d, -2047, 2047)
    if d < -2047:
        d = -2047
    elif d > 2047:
        d = 2047
    e = d + 2048
    i = e // 128
    w = e % 128
    r = (_T[i] * (128 - w) + _T[i + 1] * w + 64) // 128
    # clamp(r, 1, 4095)
    if r < 1:
        r = 1
    elif r > 4095:
        r = 4095
    return r


# 3.2 stretch
_S = array("h", [0] * 4096)  # signed short is enough for range [-2047, 2047]
_pi = 0
for _x in range(-2047, 2048):
    _v = _squash(_x)
    for _j in range(_pi, _v + 1):
        _S[_j] = _x
    _pi = _v + 1
for _j in range(_pi, 4096):
    _S[_j] = 2047


def _stretch(p: int) -> int:
    return _S[p]


# 3.3 DT
_DT = array("I", [0] * 256)
for _n in range(256):
    _DT[_n] = 131072 // (2 * _n + 3)
_LIMITE = 255

# ---------------------------------------------------------------------------
# Compteur adaptatif (Section 4)
# ---------------------------------------------------------------------------


def _p12(s: int) -> int:
    return s >> 20


def _mettre_a_jour_compteur(s: int, y: int) -> int:
    p22 = s >> 10
    n = s & 1023
    cible = 4194303 if y else 0
    if cible > p22:
        p22 = p22 + (((cible - p22) * _DT[n]) >> 16)
    else:
        p22 = p22 - (((p22 - cible) * _DT[n]) >> 16)
    if n < _LIMITE:
        n = n + 1
    return (p22 << 10) | n


# ---------------------------------------------------------------------------
# Hachage d'ordre (Section 6.1)
# ---------------------------------------------------------------------------

_N = [1, 2, 3, 4, 6]  # k=1..5


def _hacher_ordre(k: int, buf: bytes, pos: int) -> int:
    N_k = _N[k - 1]
    h = (N_k * 0x9E3779B1) & 0xFFFFFFFF
    for j in range(1, N_k + 1):
        b = buf[pos - j] if pos - j >= 0 else 0
        h = ((h ^ b) * 0x01000193) & 0xFFFFFFFF
    return h


# ---------------------------------------------------------------------------
# Case utilisée pour un bit (Section 6.2)
# ---------------------------------------------------------------------------


def _calculer_case(k: int, h_k: int, c0: int) -> int:
    if k == 0:
        return c0
    x = (h_k ^ (c0 * 0x2545F491) & 0xFFFFFFFF) & 0xFFFFFFFF
    x = (x * 0x9E3779B1) & 0xFFFFFFFF
    x = x ^ (x >> 15)
    return x >> 10


# ---------------------------------------------------------------------------
# Prédicteur (Sections 5, 6, 7, 8, 9)
# ---------------------------------------------------------------------------


class _Predicteur:
    def __init__(self):
        self.c0 = 1
        self.bp = 0
        self.buf = bytearray()
        self.pos = 0
        self.O0 = array("I", [(1 << 21) << 10] * 256)
        self.Ck = [array("I", [(1 << 21) << 10] * (1 << 22)) for _ in range(5)]
        self.h = [_hacher_ordre(k, self.buf, 0) for k in range(1, 6)]  # section 5
        self.MM = array("I", [(1 << 21) << 10] * 64)
        self.MT = array("I", [0] * (1 << 20))
        self.lg = 0
        self.ptr = 0
        self.W = [[16384] * 8 for _ in range(256)]
        # Valeurs mémorisées pour mettre_a_jour
        self._cases = [0] * 6  # case[0..5]
        self._im = 0
        self._x = [0] * 8
        self._p = 2048

    def _maj_correspondance(self, c: int):
        # Section 7.1
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

    def _recalculer_h(self):
        for k in range(1, 6):
            self.h[k - 1] = _hacher_ordre(k, self.buf, self.pos)

    def predire(self) -> int:
        # Section 6.2 : calculer les cases
        self._cases[0] = self.c0
        for k in range(1, 6):
            self._cases[k] = _calculer_case(k, self.h[k - 1], self.c0)

        # Section 7.2 : im
        if self.lg > 0:
            attendu = self.buf[self.ptr]
            if ((attendu + 256) >> (8 - self.bp)) == self.c0:
                bit_att = (attendu >> (7 - self.bp)) & 1
                self._im = min(self.lg, 31) * 2 + bit_att
            else:
                self.lg = 0
                self._im = 0
        else:
            self._im = 0

        # Section 8 : prédiction
        self._x[0] = _stretch(_p12(self.O0[self._cases[0]]))
        for k in range(1, 6):
            self._x[k] = _stretch(_p12(self.Ck[k - 1][self._cases[k]]))
        self._x[6] = _stretch(_p12(self.MM[self._im]))
        self._x[7] = 256

        point = 0
        for i in range(8):
            point += self.W[self.c0][i] * self._x[i]

        d = point >> 16
        if d < -2047:
            d = -2047
        elif d > 2047:
            d = 2047

        p = _squash(d)
        self._p = p
        return p

    def mettre_a_jour(self, y: int) -> None:
        # Section 9
        p = self._p
        err = ((y << 12) - p) * 6

        for i in range(8):
            delta = (self._x[i] * err + 32768) >> 16
            w = self.W[self.c0][i] + delta
            if w < -8388608:
                w = -8388608
            elif w > 8388607:
                w = 8388607
            self.W[self.c0][i] = w

        # Mettre à jour les compteurs
        self.O0[self._cases[0]] = _mettre_a_jour_compteur(self.O0[self._cases[0]], y)
        for k in range(1, 6):
            self.Ck[k - 1][self._cases[k]] = _mettre_a_jour_compteur(
                self.Ck[k - 1][self._cases[k]], y
            )
        self.MM[self._im] = _mettre_a_jour_compteur(self.MM[self._im], y)

        self.c0 = (self.c0 << 1) | y
        self.bp = self.bp + 1
        if self.bp == 8:
            c = self.c0 & 255
            self.buf.append(c)
            self.pos = self.pos + 1
            self.c0 = 1
            self.bp = 0
            self._maj_correspondance(c)
            self._recalculer_h()


# ---------------------------------------------------------------------------
# Codeur arithmétique binaire (Section 10)
# ---------------------------------------------------------------------------


class _Codeur:
    def __init__(self):
        self.x1 = 0
        self.x2 = 0xFFFFFFFF
        self.out = bytearray()

    def coder(self, y: int, p: int) -> None:
        r = self.x2 - self.x1
        xm = self.x1 + (r >> 12) * p + (((r & 0xFFF) * p) >> 12)
        if y == 1:
            self.x2 = xm
        else:
            self.x1 = xm + 1
        while ((self.x1 ^ self.x2) & 0xFF000000) == 0:
            self.out.append(self.x2 >> 24)
            self.x1 = (self.x1 << 8) & 0xFFFFFFFF
            self.x2 = ((self.x2 << 8) | 255) & 0xFFFFFFFF

    def fin(self) -> bytes:
        # Émettre x1 sur 4 octets, poids fort d'abord
        self.out.append((self.x1 >> 24) & 0xFF)
        self.out.append((self.x1 >> 16) & 0xFF)
        self.out.append((self.x1 >> 8) & 0xFF)
        self.out.append(self.x1 & 0xFF)
        return bytes(self.out)


# ---------------------------------------------------------------------------
# Décodeur arithmétique binaire (Section 10)
# ---------------------------------------------------------------------------


class _Decodeur:
    def __init__(self, charge: bytes):
        self.x1 = 0
        self.x2 = 0xFFFFFFFF
        self.charge = charge
        self.pos = 0
        # x = les 4 premiers octets de la charge, poids fort d'abord
        x = 0
        for i in range(4):
            x = x << 8 | charge[i] if i < len(charge) else x << 8 | 0
        self.x = x
        self.pos = 4  # les 4 premiers octets sont consommés

    def _lire_octet(self) -> int:
        b = self.charge[self.pos] if self.pos < len(self.charge) else 0
        self.pos += 1
        return b

    def decoder(self, p: int) -> int:
        r = self.x2 - self.x1
        xm = self.x1 + (r >> 12) * p + (((r & 0xFFF) * p) >> 12)
        y = 1 if self.x <= xm else 0
        if y == 1:
            self.x2 = xm
        else:
            self.x1 = xm + 1
        while ((self.x1 ^ self.x2) & 0xFF000000) == 0:
            self.x1 = (self.x1 << 8) & 0xFFFFFFFF
            self.x2 = ((self.x2 << 8) | 255) & 0xFFFFFFFF
            self.x = ((self.x << 8) | self._lire_octet()) & 0xFFFFFFFF
        return y


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
