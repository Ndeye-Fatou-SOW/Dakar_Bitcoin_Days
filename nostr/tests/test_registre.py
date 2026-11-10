"""Tests sans reseau : vrai moteur de la tontine et faux relais Nostr en local."""

import hashlib
import json
import threading
from dataclasses import asdict
from types import SimpleNamespace

import pytest
from nostr_sdk import Event, Keys
from websockets.sync.server import serve

from app.lightning import LightningFactice
from app.tontine import Moteur, empreinte_anonyme
from registre_nostr import KIND_PREUVE, PublicationInsuffisante, contenu_preuve, publier, signer_preuve

SEL = "sel-de-test"
NOMS = ["Awa Diop", "Bineta Fall", "Coumba Sarr"]
ADRESSES = ["awa@portefeuille.sn", "bineta@portefeuille.sn", "coumba@portefeuille.sn"]


def anonymiser(identifiant):
    return empreinte_anonyme(identifiant, SEL)


@pytest.fixture
def tour_complet():
    """Joue un tour complet a 3 membres sur le vrai moteur."""
    cours = SimpleNamespace(cours_btc_eur=lambda: 90_000.0)
    lightning = LightningFactice()
    moteur = Moteur(lightning=lightning, source_cours=cours)
    t = moteur.creer_tontine("Tontine du marche", 5000, "mensuelle", 3, NOMS[0], ADRESSES[0], 7, 500)
    moteur.rejoindre(t.code_invitation, NOMS[1], ADRESSES[1])
    moteur.rejoindre(t.code_invitation, NOMS[2], ADRESSES[2])
    moteur.tirer_au_sort(t.id, t.jeton_organisateur)
    moteur.demarrer(t.id, t.jeton_organisateur)
    for m in list(t.membres):
        facture = moteur.facture_cotisation(t.id, m.id)
        moteur.confirmer_paiement(facture.payment_hash, lightning.preimages[facture.payment_hash])
    return moteur, t


def preuves_de(moteur, t):
    return [c for e in moteur.evenements(t.id) if (c := contenu_preuve(e, anonymiser))]


def test_un_tour_complet_produit_les_preuves_attendues(tour_complet):
    moteur, t = tour_complet
    preuves = preuves_de(moteur, t)
    assert [p["type"] for p in preuves] == ["cotisation_payee"] * 3 + ["versement_fait"]
    assert all(p["tontine"] == anonymiser(t.id) for p in preuves)
    assert all(hashlib.sha256(bytes.fromhex(p["preimage"])).hexdigest() == p["payment_hash"] for p in preuves)


def test_le_registre_ne_contient_aucune_donnee_personnelle(tour_complet):
    moteur, t = tour_complet
    texte = json.dumps(preuves_de(moteur, t))
    interdits = NOMS + ADRESSES + [t.id, t.code_invitation, t.jeton_organisateur, t.nom, SEL]
    interdits += [m.id for m in t.membres]
    assert not [valeur for valeur in interdits if valeur in texte]


def test_le_beneficiaire_du_versement_est_anonymise(tour_complet):
    moteur, t = tour_complet
    versement = preuves_de(moteur, t)[-1]
    assert versement["beneficiaire"] == anonymiser(t.tours[0].beneficiaire_id)


def test_un_retard_est_publie_avec_son_amende():
    e = SimpleNamespace(tontine_id="T1", numero=9, type="membre_en_defaut", date=1000.5, tour=2,
                        donnees={"membre_id": "M1", "amende_fcfa": 500})
    assert contenu_preuve(e, anonymiser) == {
        "v": 1, "application": "tontine-lightning", "type": "membre_en_defaut",
        "tontine": anonymiser("T1"), "numero": 9, "tour": 2, "date": 1000,
        "membre": anonymiser("M1"), "amende_fcfa": 500}


@pytest.mark.parametrize("type_evenement", ["membre_inscrit", "ordre_fixe", "nouveau_tour", "tontine_terminee"])
def test_les_autres_evenements_ne_sont_pas_publies(type_evenement):
    e = SimpleNamespace(tontine_id="T1", numero=1, type=type_evenement, date=1.0, tour=None, donnees={})
    assert contenu_preuve(e, anonymiser) is None


def preuve_exemple(cles=None):
    contenu = {"v": 1, "application": "tontine-lightning", "type": "versement_fait", "tontine": "ab" * 8,
               "numero": 5, "tour": 1, "date": 1_794_000_000, "beneficiaire": "cd" * 8,
               "montant_sats": 33606, "payment_hash": "11" * 32, "preimage": "22" * 32}
    return signer_preuve(contenu, cles or Keys.generate())


def test_la_preuve_est_signee_et_toute_modification_se_voit():
    preuve = preuve_exemple()
    assert preuve.verify() and preuve.kind().as_u16() == KIND_PREUVE
    falsifiee = json.loads(preuve.as_json())
    falsifiee["content"] = falsifiee["content"].replace("33606", "99999")
    assert not Event.from_json(json.dumps(falsifiee)).verify()


def test_republier_une_preuve_garde_le_meme_identifiant():
    cles = Keys.generate()
    assert preuve_exemple(cles).id().to_hex() == preuve_exemple(cles).id().to_hex()


@pytest.fixture
def relais_local():
    """Fabrique de faux relais : verifient la signature puis repondent comme un vrai relais."""
    serveurs, recus = [], []

    def demarrer(reponse=None):
        def traiter(ws):
            for brut in ws:
                _, evenement = json.loads(brut)
                recus.append(evenement)
                valide = Event.from_json(json.dumps(evenement)).verify()
                ws.send(json.dumps(["OK", evenement["id"], *(reponse or [valide, ""])]))

        serveur = serve(traiter, "127.0.0.1", 0)
        threading.Thread(target=serveur.serve_forever, daemon=True).start()
        serveurs.append(serveur)
        return f"ws://127.0.0.1:{serveur.socket.getsockname()[1]}"

    yield SimpleNamespace(demarrer=demarrer, recus=recus)
    for s in serveurs:
        s.shutdown()


RELAIS_MORT = "ws://127.0.0.1:9"


def test_publication_sur_plusieurs_relais(relais_local):
    a, b = relais_local.demarrer(), relais_local.demarrer()
    assert publier(preuve_exemple(), [a, b], delai=2) == {a: True, b: True}
    assert len(relais_local.recus) == 2


def test_un_relais_en_panne_ne_bloque_pas_les_autres(relais_local):
    a, b = relais_local.demarrer(), relais_local.demarrer()
    assert publier(preuve_exemple(), [a, b, RELAIS_MORT], delai=2)[RELAIS_MORT] is False


def test_trop_peu_de_relais_declenche_une_erreur(relais_local):
    a = relais_local.demarrer()
    with pytest.raises(PublicationInsuffisante):
        publier(preuve_exemple(), [a, RELAIS_MORT], delai=2)


def test_un_refus_du_relais_ne_compte_pas(relais_local):
    a, b = relais_local.demarrer(), relais_local.demarrer([False, "blocked: kind interdit"])
    with pytest.raises(PublicationInsuffisante):
        publier(preuve_exemple(), [a, b], delai=2)


def test_une_preuve_deja_connue_du_relais_est_un_succes(relais_local):
    a, b = relais_local.demarrer([False, "duplicate: deja vu"]), relais_local.demarrer()
    assert publier(preuve_exemple(), [a, b], delai=2) == {a: True, b: True}
