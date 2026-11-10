"""Envoie une preuve signee sur plusieurs relais Nostr."""

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor

from nostr_sdk import Event
from websockets.exceptions import WebSocketException
from websockets.sync.client import connect

journal = logging.getLogger(__name__)


class PublicationInsuffisante(Exception):
    """Trop peu de relais ont accepte la preuve : elle doit etre republiee plus tard."""


def _envoyer(url: str, message: str, identifiant: str, delai: float) -> bool:
    try:
        with connect(url, open_timeout=delai, close_timeout=2,
                     user_agent_header="tontine-lightning") as ws:
            ws.send(message)
            fin = time.monotonic() + delai
            while (restant := fin - time.monotonic()) > 0:
                reponse = json.loads(ws.recv(timeout=restant))
                if reponse[:2] == ["OK", identifiant]:
                    # "duplicate:" : le relais possede deja cette preuve, c'est un succes.
                    accepte = reponse[2] is True or str(reponse[3]).startswith("duplicate:")
                    if not accepte:
                        journal.warning("Relais %s : preuve refusee (%s)", url, reponse[3])
                    return accepte
    except (OSError, TimeoutError, WebSocketException, ValueError, IndexError) as e:
        journal.warning("Relais %s injoignable : %s", url, e)
    return False


def publier(preuve: Event, relais: list[str], minimum: int = 2, delai: float = 8.0) -> dict[str, bool]:
    """Publie sur tous les relais en parallele et renvoie le resultat de chacun.

    Leve PublicationInsuffisante si moins de `minimum` relais ont accepte.
    """
    message = json.dumps(["EVENT", json.loads(preuve.as_json())])
    identifiant = preuve.id().to_hex()
    with ThreadPoolExecutor(max_workers=len(relais)) as groupe:
        reussites = list(groupe.map(lambda url: _envoyer(url, message, identifiant, delai), relais))
    resultats = dict(zip(relais, reussites))
    if sum(reussites) < minimum:
        raise PublicationInsuffisante(f"{sum(reussites)} relais sur {len(relais)} ont accepte {identifiant}")
    return resultats
