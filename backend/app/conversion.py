"""Conversion FCFA -> sats.

Le FCFA a une parite fixe avec l'euro : 1 EUR = 655,957 FCFA.
On recupere donc le cours BTC/EUR et on en deduit le nombre de sats.
"""

import json
import math
import time
import urllib.request

FCFA_PAR_EUR = 655.957
SATS_PAR_BTC = 100_000_000
URL_COURS = "https://api.coingecko.com/api/v3/simple/price?ids=bitcoin&vs_currencies=eur"
DUREE_CACHE_S = 60


def fcfa_vers_sats(montant_fcfa: int, cours_btc_eur: float) -> int:
    """Convertit un montant FCFA en sats, arrondi au sat superieur."""
    if montant_fcfa <= 0:
        raise ValueError("Le montant doit etre positif")
    if cours_btc_eur <= 0:
        raise ValueError("Le cours BTC/EUR doit etre positif")
    euros = montant_fcfa / FCFA_PAR_EUR
    return math.ceil(euros / cours_btc_eur * SATS_PAR_BTC)


class SourceCours:
    """Recupere le cours BTC/EUR et le garde en cache 60 secondes."""

    def __init__(self, url: str = URL_COURS):
        self.url = url
        self._cours: float | None = None
        self._date = 0.0

    def cours_btc_eur(self) -> float:
        if self._cours is None or time.time() - self._date > DUREE_CACHE_S:
            req = urllib.request.Request(self.url, headers={"User-Agent": "tontine-lightning"})
            with urllib.request.urlopen(req, timeout=10) as rep:
                donnees = json.load(rep)
            self._cours = float(donnees["bitcoin"]["eur"])
            self._date = time.time()
        return self._cours


class CoursFixe:
    """Cours fixe, pour les tests et le travail hors ligne."""

    def __init__(self, cours: float):
        self.cours = cours

    def cours_btc_eur(self) -> float:
        return self.cours
