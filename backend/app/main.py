"""API Python de la tontine. Lancer avec : uvicorn app.main:app --reload"""

import os
import secrets
import sys
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .conversion import SourceCours, fcfa_vers_sats
from .lightning import Facture, LightningFactice
from .stockage import ouvrir_stockage
from .tontine import ErreurAcces, ErreurLightning, ErreurTontine, Moteur, Tontine, empreinte_anonyme

app = FastAPI(title="Tontine Lightning")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

MODE_LNBITS = os.environ.get("LIGHTNING_MODE") == "lnbits"


def service_lightning():
    """LNbits si LIGHTNING_MODE=lnbits, sinon le faux service (tests, travail sans Docker)."""
    if MODE_LNBITS:
        from tontine_lightning import LightningLNbits
        ln = LightningLNbits.depuis_env(fabrique_facture=Facture)
        ln.reprendre_versements_en_cours()  # regle les versements interrompus par une panne
        return ln
    return LightningFactice()


def jeton_du_pont(mode_lnbits: bool) -> str:
    """Jeton que le pont doit presenter. Obligatoire des qu'on utilise le vrai Lightning."""
    jeton = os.environ.get("PONT_JETON_BACKEND", "")
    if mode_lnbits and not jeton:
        raise RuntimeError("PONT_JETON_BACKEND manque : le backend refuse de demarrer sans ce jeton")
    return jeton


lightning = service_lightning()
# Avec LNbits, le moteur connait la duree de vie des factures et remplace celles qui ont expire.
moteur = Moteur(lightning=lightning, source_cours=SourceCours(),
                # DATABASE_URL (PostgreSQL, par exemple sur Render), sinon un fichier SQLite.
                stockage=ouvrir_stockage(os.environ.get("DATABASE_URL")
                                         or os.environ.get("TONTINE_DB", "tontine.db")),
                validite_facture_s=lightning.reglages.expiration_facture_s if MODE_LNBITS else None)
JETON_PONT = jeton_du_pont(MODE_LNBITS)     # apres service_lightning(), qui charge le fichier .env
moteur.reprendre_versements()

NOSTR_ACTIF = os.environ.get("NOSTR_MODE") == "actif"


def demarrer_registre():
    """Publie les preuves sur Nostr si NOSTR_MODE=actif ; sinon le backend tourne sans Nostr."""
    if not NOSTR_ACTIF:
        return None
    dossier = Path(__file__).resolve().parents[2] / "nostr"
    sys.path.insert(0, str(dossier))
    from registre_nostr import Publieur, charger
    reglages = charger(Path(os.environ.get("NOSTR_ENV_FILE", dossier / ".env")))
    publieur = Publieur(moteur, reglages, lambda valeur: empreinte_anonyme(valeur, reglages.sel),
                        os.environ.get("NOSTR_CURSEURS", "publications.db"),
                        publier_retards=os.environ.get("NOSTR_PUBLIER_RETARDS") == "oui")
    publieur.demarrer()
    return publieur


registre = demarrer_registre()


class NouvelleTontine(BaseModel):
    nom: str
    montant_fcfa: int = Field(gt=0)
    frequence: str = "mensuelle"
    nombre_membres: int = Field(ge=2)
    delai_jours: int = Field(default=7, ge=1)
    amende_fcfa: int = Field(default=0, ge=0)
    nom_organisateur: str
    adresse_lightning: str


class Inscription(BaseModel):
    nom: str
    adresse_lightning: str


class NouvelleAdresse(BaseModel):
    jeton_membre: str
    adresse_lightning: str


class Organisateur(BaseModel):
    jeton_organisateur: str


class OrdreManuel(Organisateur):
    ordre: list[str]


class Confirmation(BaseModel):
    payment_hash: str
    preimage: str


def vue(t: Tontine) -> dict:
    donnees = asdict(t)
    del donnees["jeton_organisateur"]   # ce secret ne doit jamais etre visible des membres
    del donnees["evenements"]           # disponibles sur /tontines/{id}/evenements
    for membre in donnees["membres"]:
        del membre["jeton"]             # chaque jeton de membre reste secret
    donnees["situation"] = moteur.situation(t)
    # Permet aux membres de retrouver leur tontine dans le registre public Nostr.
    donnees["identifiant_registre"] = registre.anonymiser(t.id) if registre else None
    return donnees


def executer(action):
    try:
        return action()
    except ErreurAcces as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ErreurTontine as e:
        raise HTTPException(status_code=400, detail=str(e))
    except ErreurLightning:
        raise HTTPException(status_code=503, detail="Service Lightning indisponible, reessayez")
    except OSError:
        raise HTTPException(status_code=503, detail="Cours du bitcoin indisponible, reessayez")


@app.post("/tontines")
def creer(d: NouvelleTontine):
    t = executer(lambda: moteur.creer_tontine(d.nom, d.montant_fcfa, d.frequence, d.nombre_membres,
                                              d.nom_organisateur, d.adresse_lightning,
                                              d.delai_jours, d.amende_fcfa))
    return {"tontine": vue(t), "jeton_organisateur": t.jeton_organisateur,
            "jeton_membre": t.membre(t.organisateur_id).jeton,
            "lien_invitation": f"/rejoindre/{t.code_invitation}"}


# Lecture reservee aux membres : en-tete X-Jeton = jeton_membre ou jeton_organisateur.
@app.get("/tontines/{tontine_id}")
def lire(tontine_id: str, x_jeton: str = Header(default="")):
    executer(lambda: moteur.verifier_acces(tontine_id, x_jeton))
    return vue(executer(lambda: moteur.etat(tontine_id)))


@app.get("/tontines/{tontine_id}/evenements")
def evenements(tontine_id: str, depuis: int = Query(default=0, ge=0), x_jeton: str = Header(default="")):
    executer(lambda: moteur.verifier_acces(tontine_id, x_jeton))
    return [asdict(e) for e in executer(lambda: moteur.evenements(tontine_id, depuis))]


@app.post("/rejoindre/{code}")
def rejoindre(code: str, d: Inscription):
    t, m = executer(lambda: moteur.rejoindre(code, d.nom, d.adresse_lightning))
    return {"tontine_id": t.id, "membre_id": m.id, "jeton_membre": m.jeton}


@app.put("/tontines/{tontine_id}/membres/{membre_id}/adresse")
def changer_adresse(tontine_id: str, membre_id: str, d: NouvelleAdresse):
    return vue(executer(lambda: moteur.changer_adresse(tontine_id, membre_id, d.jeton_membre,
                                                       d.adresse_lightning)))


@app.post("/tontines/{tontine_id}/ordre")
def fixer_ordre(tontine_id: str, d: OrdreManuel):
    return vue(executer(lambda: moteur.fixer_ordre(tontine_id, d.jeton_organisateur, d.ordre)))


@app.post("/tontines/{tontine_id}/tirage")
def tirage(tontine_id: str, d: Organisateur):
    return vue(executer(lambda: moteur.tirer_au_sort(tontine_id, d.jeton_organisateur)))


@app.post("/tontines/{tontine_id}/demarrer")
def demarrer(tontine_id: str, d: Organisateur):
    return vue(executer(lambda: moteur.demarrer(tontine_id, d.jeton_organisateur)))


@app.post("/tontines/{tontine_id}/membres/{membre_id}/facture")
def facture(tontine_id: str, membre_id: str, x_jeton: str = Header(default="")):
    # Le membre lui-meme, ou l'organisateur qui l'aide.
    executer(lambda: moteur.verifier_acces(tontine_id, x_jeton, membre_id))
    return asdict(executer(lambda: moteur.facture_cotisation(tontine_id, membre_id)))


@app.post("/tontines/{tontine_id}/membres/{membre_id}/exclure")
def exclure(tontine_id: str, membre_id: str, d: Organisateur):
    return vue(executer(lambda: moteur.exclure(tontine_id, d.jeton_organisateur, membre_id)))


@app.post("/tontines/{tontine_id}/versement/relancer")
def relancer_versement(tontine_id: str, d: Organisateur):
    return vue(executer(lambda: moteur.relancer_versement(tontine_id, d.jeton_organisateur)))


@app.post("/paiements/confirmation")
def confirmation(d: Confirmation, x_jeton_pont: str = Header(default="")):
    if JETON_PONT and not secrets.compare_digest(x_jeton_pont.encode(), JETON_PONT.encode()):
        raise HTTPException(status_code=401, detail="Reserve au pont Lightning")
    return vue(executer(lambda: moteur.confirmer_paiement(d.payment_hash, d.preimage)))


@app.get("/registre")
def infos_registre():
    """Ce qu'il faut pour verifier les preuves : l'identite du service et les relais."""
    if registre is None:
        return {"actif": False}
    return {"actif": True, "cle_publique": registre.cle_publique, "relais": registre.relais,
            "kind": registre.kind}


@app.get("/conversion")
def conversion(fcfa: int = Query(gt=0)):
    cours = executer(moteur.source_cours.cours_btc_eur)
    return {"fcfa": fcfa, "cours_btc_eur": cours, "sats": fcfa_vers_sats(fcfa, cours)}
