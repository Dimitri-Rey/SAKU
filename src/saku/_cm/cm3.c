/* Saku, codec 3 : mélange de contextes en arithmétique entière (version 2).
 * Spécification : docs/CODEC-3.md (elle fait autorité). Aucune virgule flottante.
 * Doit produire exactement les mêmes octets que src/saku/cm3_reference.py. */
#include <stddef.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define LOGB 19 /* 2^LOGB seaux de 16 compteurs par ordre haché */
#define LIMITE 20u
#define LIMB 20u
#define LIMM 1023u
#define TAUX 6
#define NH 4 /* ordres hachés : 2, 3, 4, 6 */
#define NE (5 + NH) /* O0, O1, hachés, mot, corresp., biais */
#define TAILLE_MT (1u << 20)
#define INITIAL ((uint32_t)(1u << 21) << 10)

static const int32_t T[33] = {1,    2,    4,    6,    10,   17,   27,   45,   74,   120,  194,
                              311,  488,  747,  1102, 1546, 2048, 2550, 2994, 3349, 3608, 3785,
                              3902, 3976, 4022, 4051, 4069, 4079, 4086, 4090, 4092, 4094, 4095};
static const uint32_t ORDRES[NH] = {2, 3, 4, 6};

typedef struct {
    int32_t S[4096];
    uint32_t DT[1024];
    uint32_t c0, bp, c4;
    const uint8_t *buf;
    size_t pos;
    uint32_t O0[256];
    uint32_t O1[65536];
    uint32_t *H[NH + 1]; /* tables de seaux */
    uint32_t h[NH + 1];  /* empreinte de contexte à la frontière d'octet */
    uint32_t *seau[NH + 1];
    uint32_t mot, motp;
    uint32_t MM[64];
    uint32_t *MT;
    uint32_t lg;
    size_t ptr;
    int32_t W[1024][NE];
    uint16_t A1[256 * 33];
    uint16_t A2[65536 * 33];
    uint32_t *cpt[NE];
    uint32_t im, sel, a1i, a2i;
    int32_t x[NE];
    int32_t p, pm;
} Etat;

static int64_t asr(int64_t x, int n) { return x >= 0 ? x >> n : ~((~x) >> n); }
static int32_t borner(int64_t x, int64_t a, int64_t b) { return (int32_t)(x < a ? a : (x > b ? b : x)); }

static int32_t squash(int32_t d) {
    int32_t e, i, w, r;
    d = borner(d, -2047, 2047);
    e = d + 2048; i = e / 128; w = e % 128;
    r = (T[i] * (128 - w) + T[i + 1] * w + 64) / 128;
    return borner(r, 1, 4095);
}

static void tables(Etat *et) {
    int32_t x, v, j, pi = 0;
    uint32_t n;
    for (x = -2047; x <= 2047; x++) { v = squash(x); for (j = pi; j <= v; j++) et->S[j] = x; pi = v + 1; }
    for (j = pi; j <= 4095; j++) et->S[j] = 2047;
    for (n = 0; n < 1024; n++) et->DT[n] = 131072u / (2u * n + 3u);
}

static uint32_t compteur_maj(const Etat *et, uint32_t s, int y, uint32_t lim) {
    uint32_t p22 = s >> 10, n = s & 1023u, cible = y ? 4194303u : 0u;
    if (cible > p22) p22 += (uint32_t)(((uint64_t)(cible - p22) * et->DT[n]) >> 16);
    else p22 -= (uint32_t)(((uint64_t)(p22 - cible) * et->DT[n]) >> 16);
    if (n < lim) n++;
    return (p22 << 10) | n;
}

static int estalnum(uint32_t c) {
    return (c >= '0' && c <= '9') || (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || c == '_' || c >= 128;
}

static void hacher(Etat *et) {
    int k;
    uint32_t j, h, b;
    for (k = 0; k < NH; k++) {
        h = ORDRES[k] * 0x9E3779B1u;
        for (j = 1; j <= ORDRES[k]; j++) { b = j <= et->pos ? et->buf[et->pos - j] : 0u; h = (h ^ b) * 0x01000193u; }
        et->h[k] = h;
    }
    et->h[NH] = (et->mot ^ 0x5bd1e995u) * 0x01000193u + et->motp * 0x2F0B3A49u;
}

/* Seau de 16 compteurs (case 0 = vérification) pour le demi-octet courant ; deux voies. */
static uint32_t *trouver(uint32_t *tab, uint32_t x) {
    uint32_t chk, i, *a, *b, *r;
    int j;
    x = x * 0x9E3779B1u; x ^= x >> 15; x *= 0x2545F491u; x ^= x >> 13;
    i = x >> (32 - LOGB);
    chk = (x & 0x00FFFFFFu) | 0x01000000u;
    a = tab + (size_t)i * 16; b = tab + (size_t)(i ^ 1u) * 16;
    if (a[0] == chk) return a;
    if (b[0] == chk) return b;
    r = (b[1] & 1023u) < (a[1] & 1023u) ? b : a;
    r[0] = chk;
    for (j = 1; j < 16; j++) r[j] = INITIAL;
    return r;
}

static void seaux(Etat *et) {
    int k;
    uint32_t n = et->bp == 0 ? 0u : (et->c0 * 0x6F4F2A35u);
    for (k = 0; k < NH + 1; k++) et->seau[k] = trouver(et->H[k], et->h[k] + n);
}

static int initialiser(Etat *et, const uint8_t *buf) {
    int k, i;
    memset(et, 0, sizeof *et);
    tables(et);
    et->c0 = 1; et->buf = buf;
    for (i = 0; i < 256; i++) et->O0[i] = INITIAL;
    for (i = 0; i < 65536; i++) et->O1[i] = INITIAL;
    for (i = 0; i < 64; i++) et->MM[i] = INITIAL;
    for (k = 0; k < NH + 1; k++) { et->H[k] = calloc((size_t)16 << LOGB, sizeof(uint32_t)); if (!et->H[k]) return -1; }
    et->MT = calloc(TAILLE_MT, sizeof(uint32_t));
    if (!et->MT) return -1;
    for (i = 0; i < 1024; i++) for (k = 0; k < NE; k++) et->W[i][k] = 16384;
    for (i = 0; i < 256; i++) for (k = 0; k < 33; k++) et->A1[i * 33 + k] = (uint16_t)(squash((k - 16) * 128) * 16);
    for (i = 0; i < 65536; i++) for (k = 0; k < 33; k++) et->A2[i * 33 + k] = (uint16_t)(squash((k - 16) * 128) * 16);
    hacher(et); seaux(et);
    return 0;
}

static void liberer_etat(Etat *et) { int k; for (k = 0; k < NH + 1; k++) free(et->H[k]); free(et->MT); }

/* APM : 33 points sur stretch(p), interpolation ; mémorise le point le plus proche. */
static int32_t apm(const int32_t *S, const uint16_t *t, uint32_t cx, int32_t p, uint32_t *idx) {
    int32_t s = S[p] + 2048, w = s & 127;
    uint32_t i = (uint32_t)(s >> 7) + cx * 33u;
    *idx = i + (uint32_t)(w >> 6);
    return (t[i] * (128 - w) + t[i + 1] * w) >> 11;
}
static void apm_maj(uint16_t *t, uint32_t i, int y) {
    int32_t g = (y << 16) + (y << 7) - y - y;
    t[i] = (uint16_t)(t[i] + asr(g - t[i], 7));
}

static int32_t predire(Etat *et) {
    int k, i;
    int64_t point = 0;
    uint32_t j = et->bp < 4 ? (et->c0 & ((1u << et->bp) - 1u)) | (1u << et->bp)
                            : (et->c0 & ((1u << (et->bp - 4)) - 1u)) | (1u << (et->bp - 4));
    et->cpt[0] = &et->O0[et->c0];
    et->cpt[1] = &et->O1[((et->c4 & 255u) << 8) | et->c0];
    for (k = 0; k < NH + 1; k++) et->cpt[2 + k] = &et->seau[k][j];
    et->im = 0;
    if (et->lg > 0) {
        uint32_t attendu = et->buf[et->ptr];
        if (((attendu + 256u) >> (8u - et->bp)) == et->c0) {
            uint32_t bit_att = (attendu >> (7u - et->bp)) & 1u;
            et->im = (et->lg < 31u ? et->lg : 31u) * 2u + bit_att;
        } else et->lg = 0;
    }
    et->cpt[NE - 2] = &et->MM[et->im];
    for (k = 0; k < NE - 1; k++) et->x[k] = et->S[*et->cpt[k] >> 20];
    et->x[NE - 1] = 256;
    { uint32_t l = et->lg == 0 ? 0u : et->lg < 16u ? 1u : et->lg < 32u ? 2u : 3u; et->sel = et->c0 + 256u * l; }
    for (i = 0; i < NE; i++) point += (int64_t)et->W[et->sel][i] * et->x[i];
    et->pm = squash(borner(asr(point, 16), -2047, 2047));
    {
        int32_t p1 = apm(et->S, et->A1, et->c0, et->pm, &et->a1i);
        int32_t p2 = apm(et->S, et->A2, et->c0 | ((et->c4 & 255u) << 8), et->pm, &et->a2i);
        et->p = borner((et->pm + p1 + 2 * p2 + 2) >> 2, 1, 4095);
    }
    return et->p;
}

static void correspondance(Etat *et, uint32_t c) {
    if (et->lg > 0 && et->buf[et->ptr] == c) { et->lg = et->lg + 1 < 65535u ? et->lg + 1 : 65535u; et->ptr++; }
    else et->lg = 0;
    if (et->pos >= 6) {
        uint32_t g = 0, e;
        size_t j;
        for (j = 6; j >= 1; j--) g = g * 0x2F0B3A49u + et->buf[et->pos - j] + 1u;
        e = (g * 0x9E3779B1u) >> 12;
        if (et->lg == 0 && et->MT[e] > 0) {
            et->ptr = et->MT[e]; et->lg = 0;
            while (et->lg < 32u && et->lg < et->ptr && et->buf[et->ptr - 1 - et->lg] == et->buf[et->pos - 1 - et->lg]) et->lg++;
        }
        et->MT[e] = (uint32_t)et->pos;
    }
}

static void mettre_a_jour(Etat *et, int y) {
    int i, k;
    int64_t err = (int64_t)(((int32_t)y << 12) - et->pm) * TAUX;
    for (i = 0; i < NE; i++)
        et->W[et->sel][i] = borner((int64_t)et->W[et->sel][i] + asr((int64_t)et->x[i] * err + 32768, 16), -8388608, 8388607);
    for (k = 0; k < NE - 1; k++) *et->cpt[k] = compteur_maj(et, *et->cpt[k], y, k < 2 ? LIMB : k == NE - 2 ? LIMM : LIMITE);
    apm_maj(et->A1, et->a1i, y); apm_maj(et->A2, et->a2i, y);
    et->c0 = (et->c0 << 1) | (uint32_t)y;
    et->bp++;
    if (et->bp == 8) {
        uint32_t c = et->c0 & 255u;
        et->pos++; et->c0 = 1; et->bp = 0;
        et->c4 = (et->c4 << 8) | c;
        if (estalnum(c)) et->mot = (et->mot ^ c) * 0x01000193u;
        else if (et->mot) { et->motp = et->mot; et->mot = 0; }
        correspondance(et, c);
        hacher(et);
        seaux(et);
    } else if (et->bp == 4) seaux(et);
}

static uint32_t milieu(uint32_t x1, uint32_t x2, int32_t p) {
    uint32_t r = x2 - x1;
    return x1 + (uint32_t)((uint64_t)(r >> 12) * (uint32_t)p) + (uint32_t)(((uint64_t)(r & 0xFFFu) * (uint32_t)p) >> 12);
}
int saku_cm3_version(void) { return 2; }

void saku_cm3_liberer(void *p) { free(p); }

int saku_cm3_compresser(const uint8_t *entree, size_t n, uint8_t **sortie, size_t *taille_sortie) {
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

int saku_cm3_decompresser(const uint8_t *charge, size_t n, uint8_t *sortie, size_t taille) {
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
