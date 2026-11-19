"""Conversion FCFA -> sats.

Le FCFA a une parite fixe avec l'euro : 1 EUR = 655,957 FCFA.
On recupere donc le cours BTC/EUR et on en deduit le nombre de sats.
"""

import json
import logging
import math
import time
import urllib.request

FCFA_PAR_EUR = 655.957
SATS_PAR_BTC = 100_000_000
URL_COURS = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=eur"
URL_COURS_KRAKEN = "https://api.kraken.com/0/public/Ticker?pair=XBTEUR"
DUREE_CACHE_S = 60
logger = logging.getLogger(__name__)


def fcfa_vers_sats(montant_fcfa: int, cours_btc_eur: float) -> int:
    """Convertit un montant FCFA en sats, arrondi au sat superieur."""
    if montant_fcfa <= 0:
        raise ValueError("Le montant doit etre positif")
    if cours_btc_eur <= 0:
        raise ValueError("Le cours BTC/EUR doit etre positif")
    euros = montant_fcfa / FCFA_PAR_EUR
    return math.ceil(euros / cours_btc_eur * SATS_PAR_BTC)


def _cours_coingecko(donnees: dict) -> float:
    return _valider_cours(donnees["bitcoin"]["eur"])


def _cours_kraken(donnees: dict) -> float:
    erreurs = donnees.get("error", [])
    if erreurs:
        raise ValueError(f"Kraken a renvoye une erreur : {erreurs}")
    resultats = donnees.get("result")
    if not isinstance(resultats, dict) or not resultats:
        raise ValueError("Reponse Kraken sans resultat BTC/EUR")
    ticker = next(iter(resultats.values()))
    if not isinstance(ticker, dict):
        raise ValueError("Reponse Kraken invalide pour BTC/EUR")
    dernier = ticker.get("c")
    if not isinstance(dernier, list) or not dernier:
        raise ValueError("Reponse Kraken sans dernier cours BTC/EUR")
    return _valider_cours(dernier[0])


def _valider_cours(valeur: object) -> float:
    cours = float(valeur)
    if not math.isfinite(cours) or cours <= 0:
        raise ValueError("Le cours BTC/EUR recu est invalide")
    return cours


class SourceCours:
    """Recupere le cours BTC/EUR, avec Kraken en secours, et le garde 60 secondes."""

    def __init__(self, url: str = URL_COURS):
        self.url = url
        self._cours: float | None = None
        self._date = 0.0

    def cours_btc_eur(self) -> float:
        if self._cours is None or time.time() - self._date > DUREE_CACHE_S:
            fournisseurs = [("CoinGecko", self.url, _cours_coingecko)]
            if self.url == URL_COURS:
                fournisseurs.append(("Kraken", URL_COURS_KRAKEN, _cours_kraken))
            derniere_erreur: Exception | None = None
            for nom, url, extraire in fournisseurs:
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "tontine-lightning"})
                    with urllib.request.urlopen(req, timeout=10) as rep:
                        cours = extraire(json.load(rep))
                except (OSError, ValueError, KeyError, TypeError, StopIteration) as erreur:
                    logger.warning("Source du cours BTC/EUR %s indisponible : %s", nom, erreur)
                    derniere_erreur = erreur
                    continue
                self._cours = cours
                self._date = time.time()
                break
            else:
                raise OSError("Aucune source du cours BTC/EUR n'est disponible") from derniere_erreur
        return self._cours


class CoursFixe:
    """Cours fixe, pour les tests et le travail hors ligne."""

    def __init__(self, cours: float):
        self.cours = cours

    def cours_btc_eur(self) -> float:
        return self.cours
