"""Enregistre les tontines dans SQLite pour les retrouver apres un redemarrage."""

import json
import sqlite3
from dataclasses import asdict

from .tontine import (Cotisation, Evenement, Membre, Statut, StatutCotisation, StatutMembre,
                      StatutVersement, Tontine, Tour)


def tontine_depuis_dict(d: dict) -> Tontine:
    membres = [Membre(**{**m, "statut": StatutMembre(m["statut"])}) for m in d["membres"]]
    tours = []
    for tour in d["tours"]:
        cotisations = {cle: Cotisation(**{**c, "statut": StatutCotisation(c["statut"])})
                       for cle, c in tour["cotisations"].items()}
        tours.append(Tour(**{**tour, "cotisations": cotisations,
                             "versement_statut": StatutVersement(tour["versement_statut"])}))
    evenements = [Evenement(**e) for e in d.get("evenements", [])]
    return Tontine(**{**d, "membres": membres, "tours": tours, "statut": Statut(d["statut"]),
                      "evenements": evenements})


class Stockage:
    def __init__(self, chemin: str):
        self.connexion = sqlite3.connect(chemin, check_same_thread=False)
        self.connexion.execute("CREATE TABLE IF NOT EXISTS tontines (id TEXT PRIMARY KEY, donnees TEXT NOT NULL)")
        self.connexion.commit()

    def sauver(self, t: Tontine):
        self.connexion.execute("INSERT OR REPLACE INTO tontines (id, donnees) VALUES (?, ?)",
                               (t.id, json.dumps(asdict(t))))
        self.connexion.commit()

    def charger(self) -> list[Tontine]:
        lignes = self.connexion.execute("SELECT donnees FROM tontines").fetchall()
        return [tontine_depuis_dict(json.loads(l[0])) for l in lignes]
