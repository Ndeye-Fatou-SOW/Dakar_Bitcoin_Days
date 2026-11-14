import os

import pytest

os.environ["TONTINE_DB"] = ":memory:"

from app.conversion import CoursFixe, fcfa_vers_sats
from app.lightning import LightningFactice, preimage_valide
from app.stockage import Stockage
from app.tontine import (ErreurTontine, Moteur, Statut, StatutCotisation, StatutMembre,
                         StatutVersement, VersementEnAttente, tirer_ordre)


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
    entete = {"X-Jeton": r["jeton_organisateur"]}
    journal = client.get(f"/tontines/{tid}/evenements", headers=entete).json()
    assert [e["type"] for e in journal] == ["membre_inscrit"]
    assert client.get(f"/tontines/{tid}/evenements", params={"depuis": 1}, headers=entete).json() == []


def test_preimage_valide_mais_argent_non_recu_refusee():
    moteur, ln, t = preparer()
    ln.cotisation_recue = lambda payment_hash: False
    c = moteur.facture_cotisation(t.id, t.membres[0].id)
    with pytest.raises(ErreurTontine, match="non recu"):
        moteur.confirmer_paiement(c.payment_hash, ln.preimages[c.payment_hash])
    assert c.statut == StatutCotisation.EN_ATTENTE


def test_tontines_homonymes_versees_separement():
    ln = LightningFactice()
    moteur = Moteur(ln, CoursFixe(100_000))
    for _ in range(2):
        t = moteur.creer_tontine("Test", 10_000, "mensuelle", 2, "Awa", "awa@wallet")
        m = moteur.rejoindre(t.code_invitation, "Ibou", "ibou@wallet")[1]
        moteur.fixer_ordre(t.id, t.jeton_organisateur, [t.organisateur_id, m.id])
        moteur.demarrer(t.id, t.jeton_organisateur)
        payer_tous(moteur, ln, t)
    assert len(ln.versements) == 2


def test_faux_lightning_ne_repaie_jamais():
    ln = LightningFactice()
    assert ln.payer("a@w", 10, "x") == ln.payer("a@w", 10, "x")
    assert len(ln.versements) == 1


def en_attente_puis_normal(ln):
    payer_normal = ln.payer

    def en_attente(*args):
        raise VersementEnAttente("en vol", "ab" * 32)

    ln.payer = en_attente
    return payer_normal


def test_versement_en_vol_n_est_pas_un_echec_et_peut_etre_relance():
    moteur, ln, t = preparer()
    premier = t.tour_actuel
    payer_normal = en_attente_puis_normal(ln)
    payer_tous(moteur, ln, t)
    assert premier.versement_statut == StatutVersement.EN_COURS
    assert "versement_echec" not in [e.type for e in moteur.evenements(t.id)]
    assert len(t.tours) == 1

    ln.payer = payer_normal
    moteur.relancer_versement(t.id, t.jeton_organisateur)
    assert premier.versement_statut == StatutVersement.FAIT
    assert len(t.tours) == 2
    assert len(ln.versements) == 1


def test_versement_interrompu_repris_au_demarrage(tmp_path):
    chemin = str(tmp_path / "test.db")
    moteur, ln, t = preparer(stockage=Stockage(chemin))
    payer_normal = en_attente_puis_normal(ln)
    payer_tous(moteur, ln, t)

    ln.payer = payer_normal
    relance = Moteur(ln, CoursFixe(100_000), stockage=Stockage(chemin))
    relance.reprendre_versements()
    t2 = relance.tontine(t.id)
    assert t2.tours[0].versement_statut == StatutVersement.FAIT
    assert len(t2.tours) == 2
    assert len(ln.versements) == 1


def test_confirmation_reservee_au_pont(monkeypatch):
    from fastapi.testclient import TestClient
    from app import main

    monkeypatch.setattr(main, "JETON_PONT", "jeton-du-pont")
    client = TestClient(main.app)
    corps = {"payment_hash": "ab" * 32, "preimage": "cd" * 32}
    assert client.post("/paiements/confirmation", json=corps).status_code == 401
    faux = {"X-Jeton-Pont": "mauvais"}
    assert client.post("/paiements/confirmation", json=corps, headers=faux).status_code == 401
    bon = {"X-Jeton-Pont": "jeton-du-pont"}
    assert client.post("/paiements/confirmation", json=corps, headers=bon).status_code == 400


def test_vrai_lightning_exige_le_jeton_du_pont(monkeypatch):
    from app import main

    monkeypatch.delenv("PONT_JETON_BACKEND", raising=False)
    assert main.jeton_du_pont(False) == ""
    with pytest.raises(RuntimeError):
        main.jeton_du_pont(True)


def test_adresse_invalide_refusee_a_l_inscription():
    moteur = Moteur(LightningFactice(), CoursFixe(100_000))
    for adresse in ["awa", "awa@", "@wallet", "awa wallet@x", "a@b@c"]:
        with pytest.raises(ErreurTontine, match="Adresse"):
            moteur.creer_tontine("T", 1000, "mensuelle", 2, "Awa", adresse)
    t = moteur.creer_tontine("T", 1000, "mensuelle", 2, "Awa", " awa@wallet ")
    assert t.membres[0].adresse_lightning == "awa@wallet"
    with pytest.raises(ErreurTontine, match="Adresse"):
        moteur.rejoindre(t.code_invitation, "Ibou", "ibou")


def test_le_membre_corrige_son_adresse_et_la_cagnotte_y_part():
    moteur, ln, t = preparer()
    beneficiaire = t.membre(t.tour_actuel.beneficiaire_id)
    autre = next(m for m in t.membres if m.id != beneficiaire.id)
    with pytest.raises(ErreurTontine, match="membre lui-meme"):
        moteur.changer_adresse(t.id, beneficiaire.id, autre.jeton, "voleur@wallet")
    with pytest.raises(ErreurTontine, match="Adresse"):
        moteur.changer_adresse(t.id, beneficiaire.id, beneficiaire.jeton, "pas-une-adresse")
    moteur.changer_adresse(t.id, beneficiaire.id, beneficiaire.jeton, "nouvelle@wallet")
    payer_tous(moteur, ln, t)
    assert ln.versements[0][0] == "nouvelle@wallet"
    assert "adresse_modifiee" in [e.type for e in moteur.evenements(t.id)]


def test_adresse_bloquee_pendant_un_versement_en_vol():
    moteur, ln, t = preparer()
    beneficiaire = t.membre(t.tour_actuel.beneficiaire_id)
    payer_normal = en_attente_puis_normal(ln)
    payer_tous(moteur, ln, t)
    with pytest.raises(ErreurTontine, match="Versement en cours"):
        moteur.changer_adresse(t.id, beneficiaire.id, beneficiaire.jeton, "autre@wallet")
    ln.payer = payer_normal


def test_facture_expiree_remplacee_au_cours_du_moment():
    maintenant = [1_000.0]
    cours = CoursFixe(100_000)
    ln = LightningFactice()
    moteur = Moteur(ln, cours, horloge=lambda: maintenant[0], validite_facture_s=900)
    t = moteur.creer_tontine("T", 10_000, "mensuelle", 2, "Awa", "awa@wallet")
    moteur.rejoindre(t.code_invitation, "Ibou", "ibou@wallet")
    moteur.tirer_au_sort(t.id, t.jeton_organisateur)
    moteur.demarrer(t.id, t.jeton_organisateur)
    membre = t.membres[0]

    premiere = moteur.facture_cotisation(t.id, membre.id).payment_hash
    maintenant[0] += 900   # pas encore expiree, marge comprise
    assert moteur.facture_cotisation(t.id, membre.id).payment_hash == premiere

    maintenant[0] += 61
    cours.cours = 50_000   # le bitcoin a baisse : il faut plus de sats
    c = moteur.facture_cotisation(t.id, membre.id)
    assert c.payment_hash != premiere
    assert c.montant_sats == fcfa_vers_sats(10_000, 50_000)
    moteur.confirmer_paiement(c.payment_hash, ln.preimages[c.payment_hash])
    assert c.statut == StatutCotisation.PAYE


def test_sans_validite_la_facture_est_gardee():
    maintenant = [1_000.0]
    moteur, ln, t = preparer(horloge=lambda: maintenant[0])
    premiere = moteur.facture_cotisation(t.id, t.membres[0].id).payment_hash
    maintenant[0] += 30 * 86_400
    assert moteur.facture_cotisation(t.id, t.membres[0].id).payment_hash == premiere


def test_api_jetons_des_membres():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    r = client.post("/tontines", json={"nom": "T", "montant_fcfa": 1000, "nombre_membres": 2,
                                       "nom_organisateur": "Awa", "adresse_lightning": "a@w"}).json()
    tid, jeton_awa = r["tontine"]["id"], r["jeton_membre"]
    awa = r["tontine"]["organisateur_id"]
    ibou = client.post(r["lien_invitation"], json={"nom": "Ibou", "adresse_lightning": "i@w"}).json()
    lecture = str(client.get(f"/tontines/{tid}", headers={"X-Jeton": jeton_awa}).json())
    assert jeton_awa not in lecture and ibou["jeton_membre"] not in lecture

    url = f"/tontines/{tid}/membres/{awa}/adresse"
    assert client.put(url, json={"jeton_membre": ibou["jeton_membre"], "adresse_lightning": "x@w"}).status_code == 400
    ok = client.put(url, json={"jeton_membre": jeton_awa, "adresse_lightning": "awa@nouveau"})
    assert ok.status_code == 200
    assert ok.json()["membres"][0]["adresse_lightning"] == "awa@nouveau"


def test_ancienne_facture_reconnue_apres_redemarrage(tmp_path):
    chemin = str(tmp_path / "test.db")
    maintenant = [1_000.0]
    ln = LightningFactice()
    moteur = Moteur(ln, CoursFixe(100_000), stockage=Stockage(chemin),
                    horloge=lambda: maintenant[0], validite_facture_s=900)
    t = moteur.creer_tontine("T", 10_000, "mensuelle", 2, "Awa", "awa@wallet")
    moteur.rejoindre(t.code_invitation, "Ibou", "ibou@wallet")
    moteur.tirer_au_sort(t.id, t.jeton_organisateur)
    moteur.demarrer(t.id, t.jeton_organisateur)
    membre = t.membres[0]
    ancienne = moteur.facture_cotisation(t.id, membre.id).payment_hash
    maintenant[0] += 2_000
    nouvelle = moteur.facture_cotisation(t.id, membre.id).payment_hash
    assert nouvelle != ancienne

    # Le serveur redemarre, puis la notification du paiement de l'ancienne facture arrive.
    relance = Moteur(ln, CoursFixe(100_000), stockage=Stockage(chemin), horloge=lambda: maintenant[0])
    relance.confirmer_paiement(ancienne, ln.preimages[ancienne])
    c = relance.tontine(t.id).tour_actuel.cotisations[membre.id]
    assert c.statut == StatutCotisation.PAYE


def test_api_lecture_reservee_aux_membres():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    creer = lambda: client.post("/tontines", json={"nom": "T", "montant_fcfa": 1000, "nombre_membres": 2,
                                                   "nom_organisateur": "Awa", "adresse_lightning": "a@w"}).json()
    r, autre = creer(), creer()
    tid, awa = r["tontine"]["id"], r["tontine"]["organisateur_id"]
    ibou = client.post(r["lien_invitation"], json={"nom": "Ibou", "adresse_lightning": "i@w"}).json()

    lire = lambda jeton: client.get(f"/tontines/{tid}", headers={"X-Jeton": jeton} if jeton else {}).status_code
    assert lire(None) == 403
    assert lire("faux") == 403
    assert lire(autre["jeton_membre"]) == 403            # membre d'une autre tontine
    assert lire(ibou["jeton_membre"]) == 200
    assert lire(r["jeton_organisateur"]) == 200
    assert client.get(f"/tontines/{tid}/evenements").status_code == 403

    client.post(f"/tontines/{tid}/tirage", json={"jeton_organisateur": r["jeton_organisateur"]})
    client.post(f"/tontines/{tid}/demarrer", json={"jeton_organisateur": r["jeton_organisateur"]})
    facture = lambda jeton: client.post(f"/tontines/{tid}/membres/{awa}/facture",
                                        headers={"X-Jeton": jeton}).status_code
    assert facture(ibou["jeton_membre"]) == 403          # Ibou ne demande pas la facture d'Awa
    assert facture(r["jeton_membre"]) != 403
    assert facture(r["jeton_organisateur"]) != 403


def test_api_ne_montre_pas_le_jeton():
    from fastapi.testclient import TestClient
    from app.main import app

    client = TestClient(app)
    r = client.post("/tontines", json={"nom": "T", "montant_fcfa": 1000, "nombre_membres": 2,
                                       "nom_organisateur": "Awa", "adresse_lightning": "a@w"}).json()
    tid, jeton = r["tontine"]["id"], r["jeton_organisateur"]
    assert "jeton_organisateur" not in r["tontine"]
    assert jeton not in str(client.get(f"/tontines/{tid}", headers={"X-Jeton": jeton}).json())
    refus = client.post(f"/tontines/{tid}/tirage", json={"jeton_organisateur": r["tontine"]["organisateur_id"]})
    assert refus.status_code == 400
