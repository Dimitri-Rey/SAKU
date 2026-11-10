/* Codec 2 de Saku : mélange de contextes en arithmétique entière, version 1.
 * Spécification : docs/CODEC-2.md (elle fait autorité). Aucune virgule flottante.
 * Doit produire exactement les mêmes octets que src/saku/cm_reference.py. */

#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define TAILLE_CTX (1u << 22)
#define TAILLE_MT (1u << 20)
#define LIMITE 255u
#define INITIAL ((uint32_t)(1u << 21) << 10)

static const int32_t T[33] = {1,    2,    4,    6,    10,   17,   27,   45,   74,   120,  194,
                              311,  488,  747,  1102, 1546, 2048, 2550, 2994, 3349, 3608, 3785,
                              3902, 3976, 4022, 4051, 4069, 4079, 4086, 4090, 4092, 4094, 4095};
static const uint32_t ORDRES[5] = {1, 2, 3, 4, 6};

typedef struct {
    int32_t S[4096];
    uint32_t DT[256];
    /* prédicteur */
    uint32_t c0, bp;
    const uint8_t *buf; /* octets déjà connus du bloc (entrée au codage, sortie au décodage) */
    size_t pos;
    uint32_t O0[256];
    uint32_t *C[5];
    uint32_t h[5];
    uint32_t MM[64];
    uint32_t *MT;
    uint32_t lg;
    size_t ptr;
    int32_t W[256][8];
    /* valeurs mémorisées par predire() pour mettre_a_jour() */
    uint32_t cases[6];
    uint32_t im;
    int32_t x[8];
    int32_t p;
} Etat;

static int64_t asr(int64_t x, int n) { return x >= 0 ? x >> n : ~((~x) >> n); }

static int32_t borner(int64_t x, int64_t a, int64_t b) {
    return (int32_t)(x < a ? a : (x > b ? b : x));
}

static int32_t squash(int32_t d) {
    int32_t e, i, w, r;
    d = borner(d, -2047, 2047);
    e = d + 2048;
    i = e / 128;
    w = e % 128;
    r = (T[i] * (128 - w) + T[i + 1] * w + 64) / 128;
    return borner(r, 1, 4095);
}

static void tables(Etat *et) {
    int32_t x, v, j, pi = 0;
    uint32_t n;
    for (x = -2047; x <= 2047; x++) {
        v = squash(x);
        for (j = pi; j <= v; j++) et->S[j] = x;
        pi = v + 1;
    }
    for (j = pi; j <= 4095; j++) et->S[j] = 2047;
    for (n = 0; n < 256; n++) et->DT[n] = 131072u / (2u * n + 3u);
}

static uint32_t compteur_maj(const Etat *et, uint32_t s, int y) {
    uint32_t p22 = s >> 10, n = s & 1023u;
    uint32_t cible = y ? 4194303u : 0u;
    if (cible > p22)
        p22 = p22 + (uint32_t)(((uint64_t)(cible - p22) * et->DT[n]) >> 16);
    else
        p22 = p22 - (uint32_t)(((uint64_t)(p22 - cible) * et->DT[n]) >> 16);
    if (n < LIMITE) n++;
    return (p22 << 10) | n;
}

static void hacher(Etat *et) {
    int k;
    uint32_t j, h, b;
    for (k = 0; k < 5; k++) {
        h = ORDRES[k] * 0x9E3779B1u;
        for (j = 1; j <= ORDRES[k]; j++) {
            b = j <= et->pos ? et->buf[et->pos - j] : 0u;
            h = (h ^ b) * 0x01000193u;
        }
        et->h[k] = h;
    }
}

static int initialiser(Etat *et, const uint8_t *buf) {
    int k, i;
    memset(et, 0, sizeof *et);
    tables(et);
    et->c0 = 1;
    et->buf = buf;
    for (i = 0; i < 256; i++) et->O0[i] = INITIAL;
    for (i = 0; i < 64; i++) et->MM[i] = INITIAL;
    for (k = 0; k < 5; k++) {
        uint32_t u;
        et->C[k] = malloc(TAILLE_CTX * sizeof(uint32_t));
        if (!et->C[k]) return -1;
        for (u = 0; u < TAILLE_CTX; u++) et->C[k][u] = INITIAL;
    }
    et->MT = calloc(TAILLE_MT, sizeof(uint32_t));
    if (!et->MT) return -1;
    for (i = 0; i < 256; i++)
        for (k = 0; k < 8; k++) et->W[i][k] = 16384;
    hacher(et);
    return 0;
}

static void liberer_etat(Etat *et) {
    int k;
    for (k = 0; k < 5; k++) free(et->C[k]);
    free(et->MT);
}

static int32_t predire(Etat *et) {
    int k, i;
    int64_t point = 0;
    et->cases[0] = et->c0;
    for (k = 0; k < 5; k++) {
        uint32_t x = et->h[k] ^ (et->c0 * 0x2545F491u);
        x = x * 0x9E3779B1u;
        x = x ^ (x >> 15);
        et->cases[k + 1] = x >> 10;
    }
    et->im = 0;
    if (et->lg > 0) {
        uint32_t attendu = et->buf[et->ptr];
        if (((attendu + 256u) >> (8u - et->bp)) == et->c0) {
            uint32_t bit_att = (attendu >> (7u - et->bp)) & 1u;
            et->im = (et->lg < 31u ? et->lg : 31u) * 2u + bit_att;
        } else {
            et->lg = 0;
        }
    }
    et->x[0] = et->S[et->O0[et->cases[0]] >> 20];
    for (k = 0; k < 5; k++) et->x[k + 1] = et->S[et->C[k][et->cases[k + 1]] >> 20];
    et->x[6] = et->S[et->MM[et->im] >> 20];
    et->x[7] = 256;
    for (i = 0; i < 8; i++) point += (int64_t)et->W[et->c0][i] * et->x[i];
    et->p = squash(borner(asr(point, 16), -2047, 2047));
    return et->p;
}

static void correspondance(Etat *et, uint32_t c) {
    if (et->lg > 0 && et->buf[et->ptr] == c) {
        et->lg = et->lg + 1 < 65535u ? et->lg + 1 : 65535u;
        et->ptr++;
    } else {
        et->lg = 0;
    }
    if (et->pos >= 6) {
        uint32_t g = 0, e;
        size_t j;
        for (j = 6; j >= 1; j--) g = g * 0x2F0B3A49u + et->buf[et->pos - j] + 1u;
        e = (g * 0x9E3779B1u) >> 12;
        if (et->lg == 0 && et->MT[e] > 0) {
            et->ptr = et->MT[e];
            et->lg = 0;
            while (et->lg < 32u && et->lg < et->ptr &&
                   et->buf[et->ptr - 1 - et->lg] == et->buf[et->pos - 1 - et->lg])
                et->lg++;
        }
        et->MT[e] = (uint32_t)et->pos;
    }
}

/* Après le bit y (section 9). Au 8e bit, l'octet doit déjà être dans buf : au codage buf est
 * l'entrée, au décodage l'appelant l'écrit dans la sortie avant l'appel. */
static void mettre_a_jour(Etat *et, int y) {
    int i, k;
    int64_t err = (int64_t)(((int32_t)y << 12) - et->p) * 6;
    for (i = 0; i < 8; i++)
        et->W[et->c0][i] =
            borner((int64_t)et->W[et->c0][i] + asr((int64_t)et->x[i] * err + 32768, 16),
                   -8388608, 8388607);
    et->O0[et->cases[0]] = compteur_maj(et, et->O0[et->cases[0]], y);
    for (k = 0; k < 5; k++)
        et->C[k][et->cases[k + 1]] = compteur_maj(et, et->C[k][et->cases[k + 1]], y);
    et->MM[et->im] = compteur_maj(et, et->MM[et->im], y);
    et->c0 = (et->c0 << 1) | (uint32_t)y;
    et->bp++;
    if (et->bp == 8) {
        uint32_t c = et->c0 & 255u;
        et->pos++;
        et->c0 = 1;
        et->bp = 0;
        correspondance(et, c);
        hacher(et);
    }
}

static uint32_t milieu(uint32_t x1, uint32_t x2, int32_t p) {
    uint32_t r = x2 - x1;
    return x1 + (uint32_t)((uint64_t)(r >> 12) * (uint32_t)p) +
           (uint32_t)(((uint64_t)(r & 0xFFFu) * (uint32_t)p) >> 12);
}

int saku_cm_version(void) { return 1; }

void saku_cm_liberer(void *p) { free(p); }

int saku_cm_compresser(const uint8_t *entree, size_t n, uint8_t **sortie, size_t *taille_sortie) {
    Etat *et = calloc(1, sizeof *et);
    uint8_t *out;
    size_t cap = n / 2 + 64, lg = 0, i;
    uint32_t x1 = 0, x2 = 0xFFFFFFFFu;
    int b, k;
    *sortie = NULL;
    *taille_sortie = 0;
    out = malloc(cap);
    if (!et || !out || initialiser(et, entree) != 0) {
        if (et) liberer_etat(et);
        free(et);
        free(out);
        return -1;
    }
    for (i = 0; i < n; i++) {
        for (b = 7; b >= 0; b--) {
            int y = (entree[i] >> b) & 1;
            int32_t p = predire(et);
            uint32_t xm = milieu(x1, x2, p);
            if (y) x2 = xm; else x1 = xm + 1;
            while (((x1 ^ x2) & 0xFF000000u) == 0) {
                if (lg + 4 >= cap) {
                    uint8_t *plus = realloc(out, cap * 2);
                    if (!plus) { liberer_etat(et); free(et); free(out); return -1; }
                    out = plus;
                    cap *= 2;
                }
                out[lg++] = (uint8_t)(x2 >> 24);
                x1 <<= 8;
                x2 = (x2 << 8) | 255u;
            }
            mettre_a_jour(et, y);
        }
    }
    if (lg + 4 > cap) {
        uint8_t *plus = realloc(out, lg + 4);
        if (!plus) { liberer_etat(et); free(et); free(out); return -1; }
        out = plus;
    }
    for (k = 3; k >= 0; k--) out[lg++] = (uint8_t)(x1 >> (8 * k));
    liberer_etat(et);
    free(et);
    *sortie = out;
    *taille_sortie = lg;
    return 0;
}

int saku_cm_decompresser(const uint8_t *charge, size_t n, uint8_t *sortie, size_t taille) {
    Etat *et = calloc(1, sizeof *et);
    size_t lu = 0, i;
    uint32_t x1 = 0, x2 = 0xFFFFFFFFu, x = 0;
    int b;
    if (!et || initialiser(et, sortie) != 0) {
        if (et) liberer_etat(et);
        free(et);
        return -1;
    }
    for (b = 0; b < 4; b++) x = (x << 8) | (lu < n ? charge[lu++] : 0u);
    for (i = 0; i < taille; i++) {
        uint32_t octet = 0;
        for (b = 0; b < 8; b++) {
            int32_t p = predire(et);
            uint32_t xm = milieu(x1, x2, p);
            int y = x <= xm;
            if (y) x2 = xm; else x1 = xm + 1;
            while (((x1 ^ x2) & 0xFF000000u) == 0) {
                x1 <<= 8;
                x2 = (x2 << 8) | 255u;
                x = (x << 8) | (lu < n ? charge[lu++] : 0u);
            }
            octet = (octet << 1) | (uint32_t)y;
            /* L'octet doit être dans buf avant la mise à jour qui le termine (bit 8). */
            if (b == 7) sortie[i] = (uint8_t)octet;
            mettre_a_jour(et, y);
        }
    }
    liberer_etat(et);
    free(et);
    return 0;
}
