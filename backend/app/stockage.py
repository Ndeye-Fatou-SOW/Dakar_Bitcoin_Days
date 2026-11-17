"""Enregistre les tontines pour les retrouver apres un redemarrage.

SQLite par defaut (demo locale), PostgreSQL si DATABASE_URL est defini (par exemple sur Render).
Chaque tontine est gardee entiere, en JSON, dans une seule table.
"""

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


class StockagePostgres:
    """Meme fonctionnement que Stockage, avec PostgreSQL."""

    def __init__(self, url: str):
        import psycopg   # importe seulement si on utilise PostgreSQL
        self._psycopg = psycopg
        self.url = url
        self._connecter()
        self._executer("CREATE TABLE IF NOT EXISTS tontines (id TEXT PRIMARY KEY, donnees TEXT NOT NULL)")

    def _connecter(self):
        self.connexion = self._psycopg.connect(self.url, autocommit=True)

    def _executer(self, requete: str, valeurs: tuple = ()):
        # Un hebergeur peut couper une connexion restee inactive : on se reconnecte une fois.
        try:
            return self.connexion.execute(requete, valeurs)
        except self._psycopg.OperationalError:
            self._connecter()
            return self.connexion.execute(requete, valeurs)

    def sauver(self, t: Tontine):
        self._executer("INSERT INTO tontines (id, donnees) VALUES (%s, %s) "
                       "ON CONFLICT (id) DO UPDATE SET donnees = EXCLUDED.donnees",
                       (t.id, json.dumps(asdict(t))))

    def charger(self) -> list[Tontine]:
        lignes = self._executer("SELECT donnees FROM tontines").fetchall()
        return [tontine_depuis_dict(json.loads(l[0])) for l in lignes]


def ouvrir_stockage(adresse: str):
    """postgres://... ou postgresql://... : PostgreSQL. Sinon : chemin d'un fichier SQLite."""
    if adresse.startswith(("postgres://", "postgresql://")):
        return StockagePostgres(adresse)
    return Stockage(adresse)
