"""Interface entre le moteur et Lightning.

Le moteur ne parle jamais directement a LNbits : il passe par cette interface.
Alassane fournira la vraie implementation (LNbits) ; en attendant,
LightningFactice permet de developper et de tester sans noeud.
"""

import hashlib
import secrets
from dataclasses import dataclass
from typing import Protocol


@dataclass
class Facture:
    payment_request: str  # la facture BOLT11, affichee en QR code
    payment_hash: str     # empreinte SHA-256 de la preimage, en hexadecimal


class Lightning(Protocol):
    def creer_facture(self, montant_sats: int, description: str) -> Facture: ...

    def payer(self, adresse_lightning: str, montant_sats: int, description: str) -> str:
        """Envoie le paiement et renvoie la preimage (hexadecimal) en cas de succes."""
        ...


def preimage_valide(preimage_hex: str, payment_hash_hex: str) -> bool:
    """Verifie que SHA-256(preimage) correspond a l'empreinte de la facture."""
    try:
        empreinte = hashlib.sha256(bytes.fromhex(preimage_hex)).hexdigest()
    except ValueError:
        return False
    return secrets.compare_digest(empreinte, payment_hash_hex.lower())


class LightningFactice:
    """Faux service Lightning : garde les preimages pour simuler les paiements."""

    def __init__(self):
        self.preimages: dict[str, str] = {}   # payment_hash -> preimage
        self.versements: list[tuple[str, int]] = []

    def creer_facture(self, montant_sats: int, description: str) -> Facture:
        preimage = secrets.token_hex(32)
        payment_hash = hashlib.sha256(bytes.fromhex(preimage)).hexdigest()
        self.preimages[payment_hash] = preimage
        return Facture(payment_request=f"lntbfactice{montant_sats}n1{payment_hash[:20]}",
                       payment_hash=payment_hash)

    def payer(self, adresse_lightning: str, montant_sats: int, description: str) -> str:
        self.versements.append((adresse_lightning, montant_sats))
        return secrets.token_hex(32)
