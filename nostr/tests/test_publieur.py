"""Branchement du registre sur le vrai moteur (relais simules, aucun envoi reseau)."""

import json
import os
import threading
from types import SimpleNamespace

import pytest
from nostr_sdk import Keys

os.environ["TONTINE_DB"] = ":memory:"

from app.lightning import LightningFactice
from app.tontine import Moteur, empreinte_anonyme
from registre_nostr import PublicationInsuffisante, Publieur, Reglages

SEL = "sel-de-test"


def anonymiser(identifiant):
    return empreinte_anonyme(identifiant, SEL)


class FauxEnvoi:
    def __init__(self):
        self.preuves = []
        self.panne = False
        self.recu = threading.Event()

    def __call__(self, preuve, relais, minimum):
        if self.panne:
            raise PublicationInsuffisante("relais injoignables")
        assert preuve.verify()
        self.preuves.append(json.loads(preuve.content()))
        self.recu.set()

    @property
    def types(self):
        return [p["type"] for p in self.preuves]


class Scenario:
    def __init__(self, horloge=None):
        cours = SimpleNamespace(cours_btc_eur=lambda: 90_000.0)
        self.ln = LightningFactice()
        options = {"horloge": horloge} if horloge else {}
        self.moteur = Moteur(self.ln, cours, **options)
        self.reglages = Reglages(Keys.generate(), SEL, ["ws://relais-a", "ws://relais-b"], 2)
        self.envoi = FauxEnvoi()

    def publieur(self, chemin=":memory:", **options):
        return Publieur(self.moteur, self.reglages, anonymiser, chemin, envoyer=self.envoi, **options)

    def tontine(self, amende=0):
        t = self.moteur.creer_tontine("Marche", 5000, "mensuelle", 2, "Awa", "awa@w", 7, amende)
        self.moteur.rejoindre(t.code_invitation, "Ibou", "ibou@w")
        self.moteur.tirer_au_sort(t.id, t.jeton_organisateur)
        self.moteur.demarrer(t.id, t.jeton_organisateur)
        return t

    def payer(self, t, membre):
        c = self.moteur.facture_cotisation(t.id, membre.id)
        self.moteur.confirmer_paiement(c.payment_hash, self.ln.preimages[c.payment_hash])

    def payer_tous(self, t):
        for m in list(t.membres):
            self.payer(t, m)


ATTENDU = ["cotisation_payee", "cotisation_payee", "versement_fait"]


def test_un_tour_est_publie_une_seule_fois():
    s = Scenario()
    t = s.tontine()
    s.payer_tous(t)
    p = s.publieur()
    p.publier_en_attente()
    p.publier_en_attente()
    assert s.envoi.types == ATTENDU
    texte = json.dumps(s.envoi.preuves)
    assert "Awa" not in texte and "Ibou" not in texte and t.id not in texte


def test_une_panne_des_relais_ne_perd_aucune_preuve():
    s = Scenario()
    t = s.tontine()
    s.payer_tous(t)
    p = s.publieur()
    s.envoi.panne = True
    p.publier_en_attente()
    assert s.envoi.types == []
    s.envoi.panne = False
    p.publier_en_attente()
    assert s.envoi.types == ATTENDU
    assert [x["numero"] for x in s.envoi.preuves] == sorted(x["numero"] for x in s.envoi.preuves)


def test_apres_un_redemarrage_on_reprend_au_bon_endroit(tmp_path):
    s = Scenario()
    t = s.tontine()
    s.payer(t, t.membres[0])
    chemin = str(tmp_path / "publications.db")
    s.publieur(chemin).publier_en_attente()
    assert s.envoi.types == ["cotisation_payee"]

    s.payer(t, t.membres[1])
    s.publieur(chemin).publier_en_attente()
    assert s.envoi.types == ATTENDU


def test_une_tontine_en_echec_ne_bloque_pas_les_autres():
    s = Scenario()
    t1, t2 = s.tontine(), s.tontine()
    s.payer(t1, t1.membres[0])
    s.payer(t2, t2.membres[0])
    envoi_normal, attendue = s.envoi, anonymiser(t1.id)

    def envoi_selectif(preuve, relais, minimum):
        if json.loads(preuve.content())["tontine"] == attendue:
            raise PublicationInsuffisante("refus du relais")
        envoi_normal(preuve, relais, minimum)

    p = s.publieur()
    p.envoyer = envoi_selectif
    p.publier_en_attente()
    assert [x["tontine"] for x in s.envoi.preuves] == [anonymiser(t2.id)]


@pytest.mark.parametrize("publier_retards,attendu", [(False, []), (True, ["membre_en_defaut"] * 2)])
def test_retards_publies_seulement_si_demande(publier_retards, attendu):
    maintenant = [1000.0]
    s = Scenario(horloge=lambda: maintenant[0])
    t = s.tontine(amende=500)
    maintenant[0] += 8 * 86_400
    s.moteur.etat(t.id)
    s.publieur(publier_retards=publier_retards).publier_en_attente()
    assert s.envoi.types == attendu


def test_un_paiement_declenche_la_publication_automatiquement():
    s = Scenario()
    t = s.tontine()
    s.publieur().demarrer()
    s.payer(t, t.membres[0])
    assert s.envoi.recu.wait(5)
    assert s.envoi.types == ["cotisation_payee"]


def test_le_backend_demarre_le_registre_et_expose_son_identite(monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    from app import main

    cles = Keys.generate()
    env = tmp_path / ".env"
    env.write_text(f"NOSTR_CLE_PRIVEE={cles.secret_key().to_bech32()}\nNOSTR_SEL={SEL}\n"
                   "NOSTR_RELAIS=ws://127.0.0.1:9,ws://127.0.0.1:10\n", encoding="utf-8")
    monkeypatch.setenv("NOSTR_ENV_FILE", str(env))
    monkeypatch.setenv("NOSTR_CURSEURS", ":memory:")
    monkeypatch.setattr(main, "NOSTR_ACTIF", True)
    monkeypatch.setattr(main, "registre", main.demarrer_registre())

    client = TestClient(main.app)
    info = client.get("/registre").json()
    assert info["actif"] is True and info["cle_publique"] == cles.public_key().to_bech32()
    assert info["kind"] == 7860 and len(info["relais"]) == 2
    assert SEL not in str(info)

    r = client.post("/tontines", json={"nom": "T", "montant_fcfa": 1000, "nombre_membres": 2,
                                       "nom_organisateur": "Awa", "adresse_lightning": "a@w"}).json()
    assert r["tontine"]["identifiant_registre"] == anonymiser(r["tontine"]["id"])
