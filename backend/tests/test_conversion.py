import json
from io import BytesIO
from urllib.error import URLError
from unittest.mock import patch

import pytest

from app.conversion import SourceCours, URL_COURS_KRAKEN


def reponse(donnees: dict) -> BytesIO:
    return BytesIO(json.dumps(donnees).encode("utf-8"))


def test_source_cours_utilise_kraken_si_coingecko_est_indisponible():
    with patch(
        "app.conversion.urllib.request.urlopen",
        side_effect=[
            URLError("CoinGecko indisponible"),
            reponse({"error": [], "result": {"XXBTZEUR": {"c": ["56334.3", "0.1"]}}}),
        ],
    ) as urlopen:
        assert SourceCours().cours_btc_eur() == 56334.3

    assert urlopen.call_count == 2
    assert urlopen.call_args_list[1].args[0].full_url == URL_COURS_KRAKEN


def test_source_cours_signale_si_toutes_les_sources_sont_indisponibles():
    with patch(
        "app.conversion.urllib.request.urlopen",
        side_effect=URLError("Aucun acces reseau"),
    ):
        with pytest.raises(OSError, match="Aucune source du cours BTC/EUR"):
            SourceCours().cours_btc_eur()
