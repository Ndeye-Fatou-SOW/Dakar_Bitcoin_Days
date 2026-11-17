"""Fabrique les preuves publiques du registre : anonymes, signees, reproductibles.

Le contenu est construit champ par champ : une donnee ajoutee plus tard au moteur
ne peut donc pas partir sur Nostr sans qu'on l'ait decide ici.
"""

import hashlib
import json
from collections.abc import Callable

from nostr_sdk import EventBuilder, Keys, Kind, Tag, Timestamp, Event

APPLICATION = "tontine-lightning"
VERSION = 1
# Plage 1000-9999 de Nostr : ces messages ne peuvent etre ni remplaces ni ecrases.
KIND_PREUVE = 7860
TYPES_PUBLIES = {"cotisation_payee", "versement_fait", "membre_en_defaut"}


def empreinte_paiement(preimage: str) -> str:
    """SHA-256 de la preimage : l'empreinte que le destinataire retrouve sur sa facture."""
    return hashlib.sha256(bytes.fromhex(preimage)).hexdigest()


def contenu_preuve(evenement, anonymiser: Callable[[str], str]) -> dict | None:
    """Contenu public d'un evenement du moteur, ou None s'il n'a pas a etre publie.

    Le tontine_id est anonymise lui aussi : avec l'identifiant en clair, n'importe qui
    pourrait lire les noms des membres sur GET /tontines/{id}.
    """
    if evenement.type not in TYPES_PUBLIES:
        return None
    d = evenement.donnees
    contenu = {
        "v": VERSION,
        "application": APPLICATION,
        "type": evenement.type,
        "tontine": anonymiser(evenement.tontine_id),
        "numero": evenement.numero,
        "tour": evenement.tour,
        "date": int(evenement.date),
    }
    if evenement.type == "cotisation_payee":
        contenu.update(membre=anonymiser(d["membre_id"]), montant_sats=d["montant_sats"],
                       payment_hash=d["payment_hash"], preimage=d["preimage"])
    elif evenement.type == "versement_fait":
        contenu.update(beneficiaire=anonymiser(d["beneficiaire_id"]), montant_sats=d["montant_sats"],
                       payment_hash=empreinte_paiement(d["preimage"]), preimage=d["preimage"])
    else:
        contenu.update(membre=anonymiser(d["membre_id"]), amende_fcfa=d["amende_fcfa"])
    return contenu


def signer_preuve(contenu: dict, cles: Keys) -> Event:
    """Signe la preuve. Une meme preuve garde le meme identifiant Nostr si on la republie."""
    texte = json.dumps(contenu, sort_keys=True, separators=(",", ":"))
    etiquettes = [Tag.parse(["t", APPLICATION]), Tag.parse(["t", f"tl-{contenu['tontine']}"])]
    constructeur = (EventBuilder(Kind(KIND_PREUVE), texte)
                    .tags(etiquettes)
                    .custom_created_at(Timestamp.from_secs(contenu["date"])))
    return cles.sign_event(constructeur.finalize_unsigned(cles.public_key()))
