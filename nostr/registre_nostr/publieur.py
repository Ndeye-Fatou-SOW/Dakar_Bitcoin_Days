"""Publie sur Nostr les preuves du journal du moteur, dans l'ordre et sans en perdre.

Le journal de chaque tontine est la reference. Un curseur enregistre le dernier evenement
traite : apres une panne des relais ou un redemarrage, la publication reprend a cet endroit.
Republier une preuve est sans danger, car elle garde le meme identifiant Nostr.
"""

import logging
import sqlite3
import threading

from .preuves import KIND_PREUVE, contenu_preuve, signer_preuve
from .relais import PublicationInsuffisante, publier

journal = logging.getLogger(__name__)


class Publieur:
    def __init__(self, moteur, reglages, anonymiser, chemin: str = ":memory:",
                 intervalle: float = 30.0, publier_retards: bool = False, envoyer=publier):
        self.moteur = moteur
        self.reglages = reglages
        self.anonymiser = anonymiser
        self.intervalle = intervalle
        self.publier_retards = publier_retards
        self.envoyer = envoyer
        self.kind = KIND_PREUVE
        self.relais = reglages.relais
        self.cle_publique = reglages.cles.public_key().to_bech32()
        self._reveil = threading.Event()
        self._db = sqlite3.connect(chemin, check_same_thread=False)
        self._db.execute("CREATE TABLE IF NOT EXISTS curseurs (tontine_id TEXT PRIMARY KEY, numero INTEGER NOT NULL)")
        self._db.commit()

    def demarrer(self):
        """Lance la publication en arriere-plan ; chaque signal du moteur la reveille."""
        self.moteur.abonner(lambda evenement: self._reveil.set())
        threading.Thread(target=self._boucle, daemon=True).start()

    def _boucle(self):
        while True:
            self._reveil.clear()
            try:
                self.publier_en_attente()
            except Exception:   # le fil de publication ne doit jamais s'arreter
                journal.exception("Erreur pendant la publication des preuves")
            self._reveil.wait(self.intervalle)

    def publier_en_attente(self):
        for tontine_id in self.moteur.identifiants_tontines():
            self._publier_tontine(tontine_id)

    def _publier_tontine(self, tontine_id: str):
        for e in self.moteur.evenements(tontine_id, self._curseur(tontine_id)):
            contenu = None
            if e.type != "membre_en_defaut" or self.publier_retards:
                contenu = contenu_preuve(e, self.anonymiser)
            if contenu is not None:
                try:
                    self.envoyer(signer_preuve(contenu, self.reglages.cles),
                                 self.reglages.relais, self.reglages.minimum)
                except PublicationInsuffisante as erreur:
                    journal.warning("Preuve non publiee, nouvel essai plus tard : %s", erreur)
                    return      # on garde l'ordre : la suite attendra cette preuve
            self._avancer(tontine_id, e.numero)

    def _curseur(self, tontine_id: str) -> int:
        ligne = self._db.execute("SELECT numero FROM curseurs WHERE tontine_id = ?", (tontine_id,)).fetchone()
        return ligne[0] if ligne else 0

    def _avancer(self, tontine_id: str, numero: int):
        self._db.execute("INSERT OR REPLACE INTO curseurs (tontine_id, numero) VALUES (?, ?)", (tontine_id, numero))
        self._db.commit()
