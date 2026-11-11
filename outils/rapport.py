"""Injecte les résultats du banc de mesure dans docs/BENCHMARK.md et site/index.html.

Usage : python outils/rapport.py bench/sorties/resultats-*.json
Seules les lignes « vérifié » donnent des chiffres ; les autres sont reportées avec leur raison.
"""

from __future__ import annotations

import html
import json
import re
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent


def nombre(valeur: float, decimales: int) -> str:
    """Écrit un nombre à la française : espace fine insécable des milliers, virgule décimale."""
    return f"{valeur:,.{decimales}f}".replace(",", " ").replace(".", ",")


def lignes(resultat: dict) -> list[str]:
    if resultat["statut"] != "vérifié":
        return [resultat["outil"], f"{resultat['statut']} : {resultat['raison']}"]
    # Ratios recalculés depuis les octets : pas de double arrondi.
    brut, archive = resultat["octets_bruts"], resultat["octets_archive"]
    return [
        resultat["outil"],
        nombre(archive, 0),
        nombre(resultat["bits_par_octet"], 3),
        nombre(brut / archive, 2),
        nombre(brut / (archive + resultat["octets_modele"]), 2),
        nombre(resultat["compression_mo_s"], 3 if resultat["compression_mo_s"] < 1 else 1),
        nombre(resultat["decompression_mo_s"], 3 if resultat["decompression_mo_s"] < 1 else 1),
        nombre(resultat["ram_compression_mio"], 0),
        nombre(resultat["ram_decompression_mio"], 0),
    ]


TITRES = [
    "Outil",
    "Archive (octets)",
    "bits/octet",
    "Ratio",
    "Ratio, modèle compris",
    "Compression (Mo/s)",
    "Décompression (Mo/s)",
    "Mémoire compr. (Mio)",
    "Mémoire décompr. (Mio)",
]


def par_corpus(resultats: list[dict]) -> dict[str, list[dict]]:
    groupes: dict[str, list[dict]] = {}
    for resultat in resultats:
        groupes.setdefault(resultat["corpus"], []).append(resultat)
    return groupes


def legende(nom: str, groupe: list[dict]) -> str:
    fichiers, octets = groupe[0]["fichiers"], groupe[0]["octets_bruts"]
    return f"{nom} — {nombre(fichiers, 0)} fichiers, {nombre(octets, 0)} octets"


def en_markdown(resultats: list[dict]) -> str:
    sortie = []
    for nom, groupe in par_corpus(resultats).items():
        sortie += [f"**{legende(nom, groupe)}**", "", "| " + " | ".join(TITRES) + " |"]
        sortie.append("|---|" + "---:|" * (len(TITRES) - 1))
        sortie += ["| " + " | ".join(lignes(r)) + " |" for r in groupe]
        sortie.append("")
    return "\n".join(sortie)


def en_html(resultats: list[dict]) -> str:
    sortie = []
    for nom, groupe in par_corpus(resultats).items():
        sortie.append(
            f'<div class="defile"><table><caption>{html.escape(legende(nom, groupe))}</caption>'
        )
        sortie.append(
            "<thead><tr>" + "".join(f"<th>{t}</th>" for t in TITRES) + "</tr></thead><tbody>"
        )
        for resultat in groupe:
            cases = lignes(resultat)
            classe = ' class="saku"' if resultat["outil"].startswith("saku") else ""
            if len(cases) == 2:
                raison = html.escape(cases[1])
                corps = (
                    f'<td>{cases[0]}</td><td class="vide" colspan="{len(TITRES) - 1}">{raison}</td>'
                )
            else:
                corps = "".join(f"<td>{html.escape(c)}</td>" for c in cases)
            sortie.append(f"<tr{classe}>{corps}</tr>")
        sortie.append("</tbody></table></div>")
    return "\n".join(sortie)


def remplacer(texte: str, nom: str, contenu: str, origine: Path) -> str:
    debut, fin = f"<!--{nom}-->", f"<!--/{nom}-->"
    motif = re.compile(re.escape(debut) + ".*?" + re.escape(fin), re.DOTALL)
    if not motif.search(texte):
        raise SystemExit(f"{origine} : marqueurs {debut} … {fin} absents")
    return motif.sub(lambda _: f"{debut}\n{contenu}\n{fin}", texte)


def donnees_json(resultats: list[dict]) -> str:
    """Résultats bruts pour les graphiques du site ; « </ » neutralisé dans le script."""
    brut = json.dumps(resultats, ensure_ascii=False).replace("</", "<\\/")
    return f'<script type="application/json" id="donnees">{brut}</script>'


def main() -> int:
    # Un fichier plus loin dans la liste remplace la mesure (corpus, outil) d'un précédent.
    par_cle: dict[tuple[str, str], dict] = {}
    for fichier in sys.argv[1:]:
        for resultat in json.loads(Path(fichier).read_text())["resultats"]:
            par_cle[resultat["corpus"], resultat["outil"]] = resultat
    resultats = list(par_cle.values())
    if not resultats:
        raise SystemExit(__doc__)
    doc = RACINE / "docs" / "BENCHMARK.md"
    doc.write_text(remplacer(doc.read_text(), "MESURES", en_markdown(resultats), doc))
    gabarit = RACINE / "site" / "gabarit.html"
    page = remplacer(gabarit.read_text(), "MESURES", en_html(resultats), gabarit)
    page = remplacer(page, "DONNEES", donnees_json(resultats), gabarit)
    (RACINE / "site" / "index.html").write_text(page)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
