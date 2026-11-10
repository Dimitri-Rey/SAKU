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
DEBUT, FIN = "<!--MESURES-->", "<!--/MESURES-->"


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


def injecter(chemin: Path, contenu: str, source: Path | None = None) -> None:
    texte = (source or chemin).read_text()
    motif = re.compile(re.escape(DEBUT) + ".*?" + re.escape(FIN), re.DOTALL)
    if not motif.search(texte):
        raise SystemExit(f"{source or chemin} : marqueurs {DEBUT} … {FIN} absents")
    chemin.write_text(motif.sub(lambda _: f"{DEBUT}\n{contenu}\n{FIN}", texte))


def main() -> int:
    resultats: list[dict] = []
    for fichier in sys.argv[1:]:
        resultats += json.loads(Path(fichier).read_text())["resultats"]
    if not resultats:
        raise SystemExit(__doc__)
    injecter(RACINE / "docs" / "BENCHMARK.md", en_markdown(resultats))
    injecter(RACINE / "site" / "index.html", en_html(resultats), RACINE / "site" / "gabarit.html")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
