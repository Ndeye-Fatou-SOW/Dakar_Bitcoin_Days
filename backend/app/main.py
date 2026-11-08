"""API Python de la tontine. Lancer avec : uvicorn app.main:app --reload"""

import os
import secrets
from dataclasses import asdict

from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from .conversion import SourceCours, fcfa_vers_sats
from .lightning import Facture, LightningFactice
from .stockage import Stockage
from .tontine import ErreurLightning, ErreurTontine, Moteur, Tontine

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


moteur = Moteur(lightning=service_lightning(), source_cours=SourceCours(),
                stockage=Stockage(os.environ.get("TONTINE_DB", "tontine.db")))
JETON_PONT = jeton_du_pont(MODE_LNBITS)     # apres service_lightning(), qui charge le fichier .env
moteur.reprendre_versements()


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
    donnees["situation"] = moteur.situation(t)
    return donnees


def executer(action):
    try:
        return action()
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
            "lien_invitation": f"/rejoindre/{t.code_invitation}"}


@app.get("/tontines/{tontine_id}")
def lire(tontine_id: str):
    return vue(executer(lambda: moteur.etat(tontine_id)))


@app.get("/tontines/{tontine_id}/evenements")
def evenements(tontine_id: str, depuis: int = Query(default=0, ge=0)):
    return [asdict(e) for e in executer(lambda: moteur.evenements(tontine_id, depuis))]


@app.post("/rejoindre/{code}")
def rejoindre(code: str, d: Inscription):
    t, m = executer(lambda: moteur.rejoindre(code, d.nom, d.adresse_lightning))
    return {"tontine_id": t.id, "membre_id": m.id}


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
def facture(tontine_id: str, membre_id: str):
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


@app.get("/conversion")
def conversion(fcfa: int = Query(gt=0)):
    cours = executer(moteur.source_cours.cours_btc_eur)
    return {"fcfa": fcfa, "cours_btc_eur": cours, "sats": fcfa_vers_sats(fcfa, cours)}
