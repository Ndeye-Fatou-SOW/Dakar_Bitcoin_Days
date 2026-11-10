"""Cree nostr/.env avec la cle du service et le sel. N'ecrase jamais un fichier existant."""

import secrets
from pathlib import Path

from nostr_sdk import Keys

RELAIS = "wss://nos.lol,wss://relay.primal.net,wss://nostr.mom,wss://offchain.pub,wss://nostr.oxtr.dev"
CHEMIN = Path(__file__).parent / ".env"

if CHEMIN.exists():
    raise SystemExit(f"{CHEMIN} existe deja : rien n'a ete modifie.")

cles = Keys.generate()
CHEMIN.write_text(f"NOSTR_CLE_PRIVEE={cles.secret_key().to_bech32()}\n"
                  f"NOSTR_SEL={secrets.token_hex(32)}\n"
                  f"NOSTR_RELAIS={RELAIS}\n"
                  "NOSTR_MINIMUM_RELAIS=2\n", encoding="utf-8")
print(f"Cree : {CHEMIN}")
print(f"Identite publique du registre : {cles.public_key().to_bech32()}")
