"""Stockage SQLite et PostgreSQL.

Les tests PostgreSQL ne tournent que si TEST_POSTGRES_URL pointe vers une base de test, par exemple :
    docker run -d --name pg-test -e POSTGRES_PASSWORD=test -p 55432:5432 postgres:16
    $env:TEST_POSTGRES_URL="postgresql://postgres:test@127.0.0.1:55432/postgres"
"""

import os
import uuid

import pytest

from app.conversion import CoursFixe
from app.lightning import LightningFactice
from app.stockage import Stockage, StockagePostgres, ouvrir_stockage
from app.tontine import Moteur, Statut, StatutCotisation, StatutVersement

URL_TEST = os.environ.get("TEST_POSTGRES_URL", "")
avec_postgres = pytest.mark.skipif(not URL_TEST, reason="TEST_POSTGRES_URL non defini")


def test_ouvrir_stockage_choisit_sqlite_par_defaut(tmp_path):
    assert isinstance(ouvrir_stockage(str(tmp_path / "t.db")), Stockage)
    assert isinstance(ouvrir_stockage(":memory:"), Stockage)


def tour_complet_puis_redemarrage(ouvrir):
    """Joue un tour, redemarre le moteur sur la meme base, et verifie que tout est retrouve."""
    ln = LightningFactice()
    moteur = Moteur(ln, CoursFixe(100_000), stockage=ouvrir())
    t = moteur.creer_tontine(f"T-{uuid.uuid4().hex[:6]}", 10_000, "mensuelle", 2, "Awa", "awa@wallet")
    moteur.rejoindre(t.code_invitation, "Ibou", "ibou@wallet")
    moteur.tirer_au_sort(t.id, t.jeton_organisateur)
    moteur.demarrer(t.id, t.jeton_organisateur)
    premier = t.membres[0]
    c = moteur.facture_cotisation(t.id, premier.id)
    moteur.confirmer_paiement(c.payment_hash, ln.preimages[c.payment_hash])

    relance = Moteur(ln, CoursFixe(100_000), stockage=ouvrir())
    t2 = relance.tontine(t.id)
    assert t2.statut == Statut.EN_COURS
    assert t2.tour_actuel.cotisations[premier.id].statut == StatutCotisation.PAYE
    assert [e.type for e in relance.evenements(t.id)] == [e.type for e in moteur.evenements(t.id)]

    second = t.membres[1]
    c2 = relance.facture_cotisation(t.id, second.id)
    relance.confirmer_paiement(c2.payment_hash, ln.preimages[c2.payment_hash])
    assert t2.tours[0].versement_statut == StatutVersement.FAIT
    assert len(ln.versements) == 1


def test_sqlite_reprise_apres_redemarrage(tmp_path):
    chemin = str(tmp_path / "t.db")
    tour_complet_puis_redemarrage(lambda: ouvrir_stockage(chemin))


@avec_postgres
def test_postgres_choisi_selon_l_adresse():
    assert isinstance(ouvrir_stockage(URL_TEST), StockagePostgres)
    assert isinstance(ouvrir_stockage(URL_TEST.replace("postgresql://", "postgres://", 1)), StockagePostgres)


@avec_postgres
def test_postgres_reprise_apres_redemarrage():
    tour_complet_puis_redemarrage(lambda: ouvrir_stockage(URL_TEST))


@avec_postgres
def test_postgres_se_reconnecte_apres_une_coupure():
    stockage = StockagePostgres(URL_TEST)
    ln = LightningFactice()
    moteur = Moteur(ln, CoursFixe(100_000), stockage=stockage)
    stockage.connexion.close()          # l'hebergeur coupe la connexion
    t = moteur.creer_tontine("Coupure", 1_000, "mensuelle", 2, "Awa", "awa@wallet")
    assert any(x.id == t.id for x in StockagePostgres(URL_TEST).charger())
