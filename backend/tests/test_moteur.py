import os

import pytest

os.environ["TONTINE_DB"] = ":memory:"

from app.conversion import CoursFixe, fcfa_vers_sats
from app.lightning import LightningFactice, preimage_valide
from app.stockage import Stockage
from app.tontine import (ErreurTontine, Moteur, Statut, StatutCotisation, StatutMembre,
                         StatutVersement, tirer_ordre)


def test_conversion():
    # 655 957 FCFA = 1 000 EUR ; a 100 000 EUR le BTC, cela fait 0,01 BTC
    assert fcfa_vers_sats(655_957, 100_000) == 1_000_000
    with pytest.raises(ValueError):
        fcfa_vers_sats(0, 100_000)


def test_tirage_reproductible():
    ids = ["a", "b", "c", "d"]
    assert tirer_ordre(ids, "graine") == tirer_ordre(list(reversed(ids)), "graine")
    assert sorted(tirer_ordre(ids, "graine")) == ids


def preparer(nombre=3, stockage=None, horloge=None, **options):
    ln = LightningFactice()
    args = {"horloge": horloge} if horloge else {}
    moteur = Moteur(ln, CoursFixe(100_000), stockage=stockage, **args)
    t = moteur.creer_tontine("Test", 10_000, "mensuelle", nombre, "Awa", "awa@wallet", **options)
    for i in range(nombre - 1):
        moteur.rejoindre(t.code_invitation, f"Membre{i}", f"m{i}@wallet")
    moteur.tirer_au_sort(t.id, t.jeton_organisateur)
    moteur.demarrer(t.id, t.jeton_organisateur)
    return moteur, ln, t


def payer(moteur, ln, t, membre_id):
    c = moteur.facture_cotisation(t.id, membre_id)
    moteur.confirmer_paiement(c.payment_hash, ln.preimages[c.payment_hash])
    return c


def payer_tous(moteur, ln, t):
    for m in t.membres:
        payer(moteur, ln, t, m.id)


def test_tour_complet_et_versement():
    moteur, ln, t = preparer()
    premier = t.tour_actuel
    payer_tous(moteur, ln, t)
    assert premier.complet
    assert premier.versement_statut == StatutVersement.FAIT
    assert premier.versement_sats == 3 * fcfa_vers_sats(10_000, 100_000)
    assert ln.versements[0][0] == t.membre(premier.beneficiaire_id).adresse_lightning
    assert len(t.tours) == 2


def test_cycle_entier():
    moteur, ln, t = preparer()
    for _ in range(3):
        payer_tous(moteur, ln, t)
    assert t.statut == Statut.TERMINEE
    assert {tour.beneficiaire_id for tour in t.tours} == {m.id for m in t.membres}


def test_paiement_compte_une_seule_fois():
    moteur, ln, t = preparer()
    c = moteur.facture_cotisation(t.id, t.membres[0].id)
    preimage = ln.preimages[c.payment_hash]
    moteur.confirmer_paiement(c.payment_hash, preimage)
    moteur.confirmer_paiement(c.payment_hash, preimage)
    assert c.statut == StatutCotisation.PAYE
    assert not ln.versements


def test_preimage_fausse_refusee():
    moteur, ln, t = preparer()
    c = moteur.facture_cotisation(t.id, t.membres[0].id)
    with pytest.raises(ErreurTontine):
        moteur.confirmer_paiement(c.payment_hash, "00" * 32)
    assert not preimage_valide("zz", c.payment_hash)


def test_regles_inscription():
    moteur, ln, t = preparer(nombre=2)
    with pytest.raises(ErreurTontine):
        moteur.rejoindre(t.code_invitation, "Tard", "x@wallet")
    t2 = moteur.creer_tontine("T2", 5_000, "hebdomadaire", 3, "Ibou", "ibou@wallet")
    with pytest.raises(ErreurTontine):
        moteur.demarrer(t2.id, t2.jeton_organisateur)  # il manque des membres
    with pytest.raises(ErreurTontine):
        moteur.tirer_au_sort(t2.id, t2.organisateur_id)  # l'identifiant public ne suffit pas


def test_retard_ajoute_amende_a_la_facture():
    maintenant = [1_000.0]
    moteur, ln, t = preparer(horloge=lambda: maintenant[0], delai_jours=1, amende_fcfa=500)
    membre = t.membres[0]
    assert moteur.situation(t)[0]["en_defaut"] is False

    maintenant[0] += 2 * 86_400
    moteur.etat(t.id)
    moteur.etat(t.id)  # l'amende n'est ajoutee qu'une fois
    assert membre.amendes_dues_fcfa == 500
    assert moteur.situation(t)[0] == {"membre_id": membre.id, "nom": "Awa", "statut": "actif",
                                      "en_defaut": True, "montant_du_fcfa": 10_500}

    c = payer(moteur, ln, t, membre.id)
    assert c.montant_sats == fcfa_vers_sats(10_500, 100_000)
    assert membre.amendes_dues_fcfa == 0
    assert moteur.situation(t)[0]["en_defaut"] is False


def test_exclusion_permet_de_finir_le_tour():
    maintenant = [1_000.0]
    moteur, ln, t = preparer(horloge=lambda: maintenant[0], delai_jours=1)
    tour = t.tour_actuel
    exclu = next(m for m in t.membres if m.id != tour.beneficiaire_id)
    with pytest.raises(ErreurTontine):
        moteur.exclure(t.id, t.jeton_organisateur, exclu.id)  # pas encore en retard

    maintenant[0] += 2 * 86_400
    with pytest.raises(ErreurTontine):
        moteur.exclure(t.id, t.jeton_organisateur, tour.beneficiaire_id)
    for m in t.membres:
        if m.id != exclu.id:
            payer(moteur, ln, t, m.id)
    assert not ln.versements

    moteur.exclure(t.id, t.jeton_organisateur, exclu.id)
    assert exclu.statut == StatutMembre.EXCLU
    assert ln.versements[0][1] == 2 * fcfa_vers_sats(10_000, 100_000)
    assert exclu.id not in t.ordre
    assert exclu.id not in t.tour_actuel.cotisations


def test_versement_en_echec_peut_etre_relance():
    moteur, ln, t = preparer()
    premier = t.tour_actuel
    payer_normal = ln.payer

    def panne(*args):
        raise RuntimeError("noeud injoignable")

    ln.payer = panne
    payer_tous(moteur, ln, t)
    assert premier.versement_statut == StatutVersement.ECHEC
    assert len(t.tours) == 1

    ln.payer = payer_normal
    moteur.relancer_versement(t.id, t.jeton_organisateur)
    assert premier.versement_statut == StatutVersement.FAIT
    assert len(t.tours) == 2
    assert len(ln.versements) == 1
    with pytest.raises(ErreurTontine):
        moteur.relancer_versement(t.id, t.jeton_organisateur)


def test_reprise_apres_redemarrage(tmp_path):
    chemin = str(tmp_path / "test.db")
    moteur, ln, t = preparer(stockage=Stockage(chemin))
    payer(moteur, ln, t, t.membres[0].id)
    c = moteur.facture_cotisation(t.id, t.membres[1].id)

    relance = Moteur(ln, CoursFixe(100_000), stockage=Stockage(chemin))
    t2 = relance.tontine(t.id)
    assert t2.tour_actuel.cotisations[t.membres[0].id].statut == StatutCotisation.PAYE
    relance.confirmer_paiement(c.payment_hash, ln.preimages[c.payment_hash])
    payer(relance, ln, t2, t.membres[2].id)
    assert t2.tours[0].versement_statut == StatutVersement.FAIT
    assert len(t2.tours) == 2
    assert t2.statut == Statut.EN_COURS


def test_journal_d_un_tour_sans_donnees_personnelles():
    moteur, ln, t = preparer()
    payer_tous(moteur, ln, t)
    assert [e.type for e in moteur.evenements(t.id)] == [
        "membre_inscrit", "membre_inscrit", "ordre_fixe", "nouveau_tour",
        "cotisation_payee", "cotisation_payee", "cotisation_payee",
        "versement_fait", "nouveau_tour"]
    assert [e.numero for e in moteur.evenements(t.id)] == list(range(1, 10))
    assert [e.numero for e in moteur.evenements(t.id, depuis=8)] == [9]
    texte = str(moteur.evenements(t.id))
    assert "Membre0" not in texte and "Awa" not in texte and "@wallet" not in texte


def test_signaux_recus_malgre_un_abonne_en_panne():
    moteur, ln, t = preparer()
    recus = []

    def abonne_en_panne(evenement):
        raise RuntimeError("relai Nostr injoignable")

    moteur.abonner(abonne_en_panne)
    moteur.abonner(lambda evenement: recus.append(evenement.type))
    payer_tous(moteur, ln, t)
    moteur.attendre_diffusion()
    assert recus == ["cotisation_payee"] * 3 + ["versement_fait", "nouveau_tour"]
    assert t.tours[0].versement_statut == StatutVersement.FAIT


def test_signal_de_fin_et_d_echec():
    moteur, ln, t = preparer(nombre=2)

    def panne(*args):
        raise RuntimeError("noeud injoignable")

    payer_normal, ln.payer = ln.payer, panne
    payer_tous(moteur, ln, t)
    assert moteur.evenements(t.id)[-1].type == "versement_echec"
    ln.payer = payer_normal
    moteur.relancer_versement(t.id, t.jeton_organisateur)
    payer_tous(moteur, ln, t)
    assert moteur.evenements(t.id)[-1].type == "tontine_terminee"


def test_journal_conserve_apres_redemarrage(tmp_path):
    chemin = str(tmp_path / "test.db")
    moteur, ln, t = preparer(stockage=Stockage(chemin))
    payer(moteur, ln, t, t.membres[0].id)
    nombre = len(moteur.evenements(t.id))

    relance = Moteur(ln, CoursFixe(100_000), stockage=Stockage(chemin))
    assert len(relance.evenements(t.id)) == nombre
    payer(relance, ln, relance.tontine(t.id), t.membres[1].id)
    assert relance.evenements(t.id)[-1].numero == nombre + 1


def test_api_evenements():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    r = client.post("/tontines", json={"nom": "T", "montant_fcfa": 1000, "nombre_membres": 2,
                                       "nom_organisateur": "Awa", "adresse_lightning": "a@w"}).json()
    tid = r["tontine"]["id"]
    assert "evenements" not in r["tontine"]
    client.post(r["lien_invitation"], json={"nom": "Ibou", "adresse_lightning": "i@w"})
    journal = client.get(f"/tontines/{tid}/evenements").json()
    assert [e["type"] for e in journal] == ["membre_inscrit"]
    assert client.get(f"/tontines/{tid}/evenements", params={"depuis": 1}).json() == []


def test_api_ne_montre_pas_le_jeton():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    r = client.post("/tontines", json={"nom": "T", "montant_fcfa": 1000, "nombre_membres": 2,
                                       "nom_organisateur": "Awa", "adresse_lightning": "a@w"}).json()
    tid, jeton = r["tontine"]["id"], r["jeton_organisateur"]
    assert "jeton_organisateur" not in r["tontine"]
    assert jeton not in str(client.get(f"/tontines/{tid}").json())
    refus = client.post(f"/tontines/{tid}/tirage", json={"jeton_organisateur": r["tontine"]["organisateur_id"]})
    assert refus.status_code == 400
