"""Envoie un prompt au modèle local (Qwen, API compatible OpenAI) et écrit les fichiers rendus.

Usage : python outils/qwen.py PROMPT.md [CONTEXTE...] [--sortie DOSSIER] [--brut FICHIER]

Le prompt et les fichiers de contexte sont concaténés dans un seul message. Si la réponse
contient des marqueurs `=== FICHIER: chemin ===`, chaque section est écrite sous --sortie ;
sinon la réponse entière va dans --brut (ou sur la sortie standard).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

URL = os.environ.get("SAKU_IA_URL", "http://127.0.0.1:8080/v1/chat/completions")
MODELE = os.environ.get("SAKU_IA_MODELE", "qwen3.8-27b-ampere")
MARQUEUR = re.compile(r"^=== FICHIER: (.+?) ===\s*$", re.MULTILINE)
DELAI_S = 1800


def interroger(message: str, jetons_max: int, effort: str) -> str:
    """Appelle le modèle et rend le texte de sa réponse (sans le raisonnement)."""
    charge: dict[str, object] = {
        "model": MODELE,
        "messages": [{"role": "user", "content": message}],
        "max_tokens": jetons_max,
        "temperature": 0.2,
    }
    # Constat du 2026-11-10 : en réflexion, même « low », le modèle rédige toute sa réponse
    # dans le raisonnement et rend un contenu vide sur les longues tâches de code.
    if effort == "none":
        charge["chat_template_kwargs"] = {"enable_thinking": False}
    else:
        charge["reasoning_effort"] = effort
    corps = json.dumps(charge).encode()
    requete = urllib.request.Request(URL, corps, {"Content-Type": "application/json"})
    with urllib.request.urlopen(requete, timeout=DELAI_S) as reponse:
        donnees = json.load(reponse)
    choix = donnees["choices"][0]
    if choix.get("finish_reason") == "length":
        print("ATTENTION : réponse tronquée (max_tokens atteint)", file=sys.stderr)
    print(f"jetons : {donnees['usage']}", file=sys.stderr)
    return choix["message"]["content"] or ""


def sans_cloture(texte: str) -> str:
    """Retire la clôture Markdown dont le modèle entoure parfois un fichier, malgré la consigne."""
    texte = re.sub(r"\A\s*```[\w-]*\n", "", texte)
    return re.sub(r"\n```\s*\Z", "\n", texte)


def ecrire_fichiers(reponse: str, sortie: Path) -> list[Path]:
    """Découpe la réponse selon les marqueurs et écrit chaque fichier sous `sortie`."""
    morceaux = MARQUEUR.split(reponse)
    ecrits: list[Path] = []
    racine = sortie.resolve()
    for chemin, contenu in zip(morceaux[1::2], morceaux[2::2], strict=True):
        cible = (racine / chemin.strip()).resolve()
        if not cible.is_relative_to(racine):
            raise ValueError(f"chemin hors du dossier de sortie : {chemin!r}")
        texte = sans_cloture(contenu)
        cible.parent.mkdir(parents=True, exist_ok=True)
        cible.write_text(texte.strip("\n") + "\n", encoding="utf-8")
        ecrits.append(cible)
    return ecrits


def main() -> int:
    analyseur = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    analyseur.add_argument("prompt", type=Path)
    analyseur.add_argument("contexte", type=Path, nargs="*")
    analyseur.add_argument("--sortie", type=Path)
    analyseur.add_argument("--brut", type=Path)
    analyseur.add_argument("--jetons-max", type=int, default=30000)
    analyseur.add_argument("--effort", choices=("none", "low", "medium", "xhigh"), default="none")
    args = analyseur.parse_args()

    parties = [args.prompt.read_text(encoding="utf-8")]
    for fichier in args.contexte:
        parties.append(
            f'\n<fichier chemin="{fichier}">\n{fichier.read_text(encoding="utf-8")}\n</fichier>'
        )
    reponse = interroger("\n".join(parties), args.jetons_max, args.effort)

    if args.brut:
        args.brut.parent.mkdir(parents=True, exist_ok=True)
        args.brut.write_text(sans_cloture(reponse).strip("\n") + "\n", encoding="utf-8")
    if args.sortie and MARQUEUR.search(reponse):
        for cible in ecrire_fichiers(reponse, args.sortie):
            print(f"écrit : {cible}")
    elif not args.brut:
        print(reponse)
    return 0


if __name__ == "__main__":
    sys.exit(main())
