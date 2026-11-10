"""Lit la configuration du registre depuis nostr/.env (jamais envoye sur le depot)."""

from dataclasses import dataclass
from pathlib import Path

from nostr_sdk import Keys


@dataclass(frozen=True)
class Reglages:
    cles: Keys
    sel: str
    relais: list[str]
    minimum: int


def lire_env(chemin: Path) -> dict[str, str]:
    valeurs = {}
    for ligne in chemin.read_text(encoding="utf-8").splitlines():
        ligne = ligne.strip()
        if ligne and not ligne.startswith("#") and "=" in ligne:
            cle, valeur = ligne.split("=", 1)
            valeurs[cle.strip()] = valeur.strip()
    return valeurs


def charger(chemin: Path) -> Reglages:
    v = lire_env(chemin)
    manquants = [n for n in ("NOSTR_CLE_PRIVEE", "NOSTR_SEL", "NOSTR_RELAIS") if not v.get(n)]
    if manquants:
        raise RuntimeError(f"Reglages manquants dans {chemin} : {', '.join(manquants)}")
    relais = [r.strip() for r in v["NOSTR_RELAIS"].split(",") if r.strip()]
    return Reglages(Keys.parse(v["NOSTR_CLE_PRIVEE"]), v["NOSTR_SEL"], relais,
                    int(v.get("NOSTR_MINIMUM_RELAIS", "2")))
